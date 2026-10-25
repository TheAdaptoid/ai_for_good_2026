"""Local generation stages (Spec 005). Each implements its Spec 004 Protocol and is testable without
a model: the activity stage takes any classifier with the ``XCLIPClassifier.classify`` shape.

Defaults come from the measured detection cadence (specs/005-local-analysis-generation/plan.md R1).
"""

import math
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean, median
from time import perf_counter
from typing import Protocol

import numpy as np

from pipeline.contracts import AnnotationProposal, ClipProposal, ExpressionScores, VideoSignals

PRIORITY_METHOD = "participant_count_positive_affect_v1"
# Tie order for affect: the most conservative reading wins a tie.
AFFECT_LABELS = (("neutral", "Visible Neutral Affect"), ("positive", "Visible Positive Affect"),
                 ("negative", "Visible Negative Affect"))


@dataclass(frozen=True)
class GenerationConfig:
    gap_seconds: float = 2.0            # 90.8% of same-person detection gaps are <= 2 s
    min_presence_seconds: float = 1.0   # shorter presence runs are detection flicker
    min_clip_seconds: float = 5.0       # shorter set changes merge into the previous clip
    max_clip_seconds: float = 60.0      # longer unchanged stretches are split evenly
    window_seconds: float = 4.0         # span of one activity window
    seconds_per_window: float = 15.0    # one more window per this much clip duration
    max_windows_per_clip: int = 4
    activity_support: float = 0.20      # representative label needs this mean score
    activity_multi_label: float = 0.30  # any further label needs this mean score

    def parameters(self) -> dict[str, float | int]:
        return asdict(self)


def video_fps(video: VideoSignals) -> float | None:
    """Stored fps, else the frame/time ratio of the detections."""
    if video.fps:
        return video.fps
    ratios = [d.frame_number / d.seconds for d in video.detections if d.seconds > 0]
    return median(ratios) if ratios else None


class _PersonIndex:
    """Per-participant detections sorted by frame, for range lookups."""

    def __init__(self, video: VideoSignals):
        rows: dict[str, list[tuple[int, ExpressionScores | None]]] = defaultdict(list)
        for d in video.detections:
            rows[d.person_id].append((d.frame_number, d.expression))
        self.frames = {p: [f for f, _ in sorted(r, key=lambda x: x[0])] for p, r in rows.items()}
        self.scores = {p: [e for _, e in sorted(r, key=lambda x: x[0])] for p, r in rows.items()}

    def expressions(self, person: str, start: int, end: int) -> list[ExpressionScores]:
        frames = self.frames.get(person, [])
        lo, hi = bisect_left(frames, start), bisect_right(frames, end)
        return [e for e in self.scores.get(person, [])[lo:hi] if e is not None]


class _IndexCache:
    def __init__(self) -> None:
        self._video: VideoSignals | None = None
        self._index: _PersonIndex | None = None

    def get(self, video: VideoSignals) -> _PersonIndex:
        if self._video is not video:
            self._video, self._index = video, _PersonIndex(video)
        return self._index


# --- Clip segmentation ---------------------------------------------------------------------

class PresenceSegmenter:
    """New clip when the set of present participants changes (D017), made practical by a gap
    tolerance, a minimum presence run, a minimum clip length, and a maximum clip length."""

    def __init__(self, config: GenerationConfig = GenerationConfig()):
        self.config = config

    def _runs(self, video: VideoSignals, fps: float) -> list[tuple[int, int, str]]:
        """Half-open frame runs [start, end) per participant that last at least the minimum."""
        gap, minimum = self.config.gap_seconds * fps, self.config.min_presence_seconds * fps
        frames: dict[str, set[int]] = defaultdict(set)
        for d in video.detections:
            frames[d.person_id].add(d.frame_number)
        runs = []
        for person in sorted(frames):
            ordered = sorted(frames[person])
            start = previous = ordered[0]
            for frame in ordered[1:] + [None]:
                if frame is None or frame - previous > gap:
                    if previous - start >= minimum:
                        runs.append((start, previous + 1, person))
                    start = frame
                previous = frame if frame is not None else previous
        return runs

    def segment(self, video: VideoSignals) -> list[ClipProposal]:
        fps = video_fps(video)
        if not video.detections or not fps:
            return []
        runs = self._runs(video, fps)
        events: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for start, end, person in runs:
            events[start].append((1, person))
            events[end].append((-1, person))
        active: Counter[str] = Counter()
        segments: list[tuple[int, int, frozenset[str]]] = []
        points = sorted(events)
        for a, b in zip(points, points[1:]):
            for delta, person in events[a]:
                active[person] += delta
            members = frozenset(p for p, n in active.items() if n > 0)
            if not members:
                continue
            if segments and segments[-1][1] == a and segments[-1][2] == members:
                segments[-1] = (segments[-1][0], b, members)
            else:
                segments.append((a, b, members))
        minimum = self.config.min_clip_seconds * fps
        merged: list[tuple[int, int, frozenset[str]]] = []
        for a, b, members in segments:
            if merged and merged[-1][1] == a and (b - a < minimum or a - merged[-1][0] < minimum):
                merged[-1] = (merged[-1][0], b, merged[-1][2] | members)
            else:
                merged.append((a, b, members))
        last = (video.frame_count - 1 if video.frame_count
                else max(d.frame_number for d in video.detections))
        longest = max(1, round(self.config.max_clip_seconds * fps))
        clips = []
        for a, b, members in merged:
            b = min(b, last + 1)
            if b <= a:
                continue
            parts = math.ceil((b - a) / longest)
            edges = [a + (b - a) * i // parts for i in range(parts + 1)]
            clips += [ClipProposal(edges[i], edges[i + 1] - 1, tuple(sorted(members)))
                      for i in range(parts)]
        return clips


# --- Visible affect ------------------------------------------------------------------------

def affect_label(scores: Sequence[ExpressionScores]) -> tuple[str, float] | None:
    """Mean each score over the detections; the highest mean wins (ties: neutral, positive,
    negative). Returns (label name, winning mean) or None without scores."""
    if not scores:
        return None
    means = {"positive": fmean(s.positive for s in scores),
             "neutral": fmean(s.neutral for s in scores),
             "negative": fmean(s.negative for s in scores)}
    best_key, best_name = AFFECT_LABELS[0]
    for key, name in AFFECT_LABELS[1:]:
        if means[key] > means[best_key]:
            best_key, best_name = key, name
    return best_name, means[best_key]


class ExpressionAffectAnnotator:
    """Per participant per clip, from that participant's own detections in the clip. These are
    observable-signal suggestions for staff review, not statements about internal emotion."""

    def __init__(self) -> None:
        self._cache = _IndexCache()

    def annotate(self, video: VideoSignals, clips: Sequence[ClipProposal]) -> list[AnnotationProposal]:
        index = self._cache.get(video)
        out = []
        for i, clip in enumerate(clips):
            for person in clip.person_ids:
                result = affect_label(index.expressions(person, clip.start_frame, clip.end_frame))
                if result is not None:
                    name, confidence = result
                    out.append(AnnotationProposal(
                        name, "observation", clip_index=i, person_id=person,
                        start_frame=clip.start_frame, end_frame=clip.end_frame,
                        confidence=round(min(max(confidence, 0.0), 1.0), 6)))
        return out


# --- Review priority -----------------------------------------------------------------------

def participant_positive_priority(per_participant_positive_means: Sequence[float],
                                  participant_count: int) -> float | None:
    """(1.1 ^ N) x mean of per-participant mean positive scores. Averaging per participant first
    keeps a frequently detected participant from outweighing the others."""
    if not per_participant_positive_means:
        return None
    return 1.1 ** participant_count * fmean(per_participant_positive_means)


class ParticipantPositivePriority:
    """A ranking heuristic for what staff look at first: not a confidence, not a probability."""
    method = PRIORITY_METHOD

    def __init__(self) -> None:
        self._cache = _IndexCache()

    def score(self, video: VideoSignals, clip: ClipProposal,
              annotations: Sequence[AnnotationProposal]) -> float | None:
        index = self._cache.get(video)
        means = []
        for person in clip.person_ids:  # N counts every member, even one with no scores in the clip
            scores = index.expressions(person, clip.start_frame, clip.end_frame)
            if scores:
                means.append(fmean(s.positive for s in scores))
        value = participant_positive_priority(means, len(clip.person_ids))
        return None if value is None else round(value, 6)


# --- Activity ------------------------------------------------------------------------------

class Classifier(Protocol):
    num_frames: int

    def classify(self, frames: np.ndarray, activities: list[str], *,
                 descriptions: Mapping[str, str] | None = None): ...


Decoder = Callable[[Path, float, Sequence[Sequence[int]]], Iterable[np.ndarray]]


def window_indices(clip: ClipProposal, fps: float, last_frame: int, frames_per_window: int,
                   config: GenerationConfig) -> list[list[int]]:
    """Deterministic windows: ceil(duration / seconds_per_window) of them (1..max), evenly centred;
    each spans window_seconds with frames_per_window evenly spaced indices, clamped to the video."""
    length = clip.end_frame - clip.start_frame + 1
    count = min(max(math.ceil(length / fps / config.seconds_per_window), 1),
                config.max_windows_per_clip)
    half = config.window_seconds * fps / 2
    windows = []
    for i in range(count):
        centre = clip.start_frame + (i + 0.5) * length / count
        raw = np.linspace(centre - half, centre + half, frames_per_window)
        windows.append([int(min(max(round(x), 0), last_frame)) for x in raw])
    return windows


def aggregate_activity(window_scores: Sequence[Mapping[str, float]], labels: Sequence[str],
                       support: float, multi_label: float) -> list[tuple[str, float]]:
    """Representative = most common top label across windows (ties: higher mean, then label order),
    kept if its mean >= support; any other label with mean >= multi_label is kept too."""
    if not window_scores:
        return []
    order = {label: i for i, label in enumerate(labels)}
    means = {label: fmean(w.get(label, 0.0) for w in window_scores) for label in labels}
    wins = Counter(max(labels, key=lambda l: (w.get(l, 0.0), -order[l])) for w in window_scores)
    representative = max(wins, key=lambda l: (wins[l], means[l], -order[l]))
    chosen = [representative] if means[representative] >= support else []
    chosen += [l for l in labels if l != representative and means[l] >= multi_label]
    return [(label, round(means[label], 4)) for label in chosen]


class ZeroShotActivityAnnotator:
    """Clip-level activity from a local zero-shot video model over sampled windows."""

    def __init__(self, classifier: Classifier, labels: Sequence[str], prompts: Mapping[str, str],
                 video_paths: Mapping[str, Path], decoder: Decoder,
                 config: GenerationConfig = GenerationConfig(),
                 template: str = "A video of people {activity}."):
        if not labels:
            raise ValueError("no active activity labels to classify against")
        self.classifier, self.labels, self.video_paths = classifier, list(labels), video_paths
        self.decoder, self.config = decoder, config
        self.descriptions = {l: prompts.get(l, template.format(activity=l.lower())) for l in labels}
        self.windows_classified = 0
        self.inference_seconds = 0.0
        self.decode_seconds = 0.0

    def annotate(self, video: VideoSignals, clips: Sequence[ClipProposal]) -> list[AnnotationProposal]:
        fps = video_fps(video)
        path = self.video_paths.get(video.filename)
        if not clips or not fps or path is None:
            return []
        last = (video.frame_count - 1 if video.frame_count
                else max(c.end_frame for c in clips))
        plan = [window_indices(c, fps, last, self.classifier.num_frames, self.config) for c in clips]
        flat = [w for windows in plan for w in windows]
        frames = iter(self.decoder(path, fps, flat))
        out = []
        for i, windows in enumerate(plan):
            scores = []
            for _ in windows:
                started = perf_counter()
                window = next(frames)
                self.decode_seconds += perf_counter() - started
                result = self.classifier.classify(window, self.labels, descriptions=self.descriptions)
                self.inference_seconds += result.inference_time_seconds
                self.windows_classified += 1
                scores.append({p.label: p.score for p in result.predictions})
            for label, confidence in aggregate_activity(
                    scores, self.labels, self.config.activity_support, self.config.activity_multi_label):
                out.append(AnnotationProposal(label, "activity", clip_index=i, confidence=confidence))
        return out
