"""Synthetic stages on a synthetic database: proves the contracts, not any real algorithm."""

import hashlib
from collections import Counter

import pytest

from analysis_db.annotations import list_annotations, list_clips
from analysis_db.contracts import DataError
from analysis_db.pipeline_import import import_file
from pipeline.builder import build_import_file, stable_key
from pipeline.contracts import AnnotationProposal, ClipProposal, PipelineMetadata
from pipeline.signals import load_video_signals

INFO = PipelineMetadata("synthetic-stages", "0.1", "2026-10-25T00:00:00Z", (("fake", "r1"),))


@pytest.fixture
def signals_db(review_db):
    """Video 1: Person_0001 at frames 0-48, Person_0002 joins at 24; one activity, one gap."""
    rows = [(1, "Person_0001", 0), (2, "Person_0001", 24), (3, "Person_0002", 24),
            (4, "Person_0001", 48), (5, "Person_0002", 96)]
    for detection_id, person, frame in rows:
        review_db.execute("INSERT OR IGNORE INTO Frame VALUES (?, 1, ?, ?)",
                          (f"F{frame}", frame, frame / 23.976))
        review_db.execute("INSERT INTO FaceDetection (detection_id, person_id, frame_id, x1, y1,"
                          " x2, y2, det_score) VALUES (?, ?, ?, 0, 0, 1, 1, 0.9)",
                          (detection_id, person, f"F{frame}"))
    review_db.executemany("INSERT INTO Engagement (detection_id, positive_score, neutral_score,"
                          " negative_score) VALUES (?, ?, ?, ?)",
                          [(1, 0.8, 0.1, 0.1), (2, 0.6, 0.3, 0.1), (3, 0.2, 0.7, 0.1),
                           (4, 0.9, 0.05, 0.05)])
    review_db.execute("INSERT INTO Activity (detection_id, start_frame, end_frame, activity_label,"
                      " confidence) VALUES (2, 8, 39, 'singing', 0.7)")
    return review_db


class PresenceSegmenter:
    """Toy segmenter: one clip per distinct frame, members are whoever is detected there."""

    def segment(self, video):
        frames: dict[int, set[str]] = {}
        for d in video.detections:
            frames.setdefault(d.frame_number, set()).add(d.person_id)
        return [ClipProposal(f, f + 23, tuple(sorted(p))) for f, p in sorted(frames.items())]


class ModeActivity:
    def annotate(self, video, clips):
        out = []
        for i, clip in enumerate(clips):
            labels = Counter(d.activity.label for d in video.detections
                             if d.activity and clip.start_frame <= d.frame_number <= clip.end_frame)
            if labels:
                label, _ = labels.most_common(1)[0]
                out.append(AnnotationProposal(label.title(), "activity", clip_index=i, confidence=0.7))
        return out


class TopAffect:
    names = {0: "Visible Positive Affect", 1: "Visible Neutral Affect", 2: "Visible Negative Affect"}

    def annotate(self, video, clips):
        out = []
        for i, clip in enumerate(clips):
            for d in video.detections:
                if d.expression and clip.start_frame <= d.frame_number <= clip.end_frame:
                    scores = (d.expression.positive, d.expression.neutral, d.expression.negative)
                    top = max(range(3), key=lambda k: scores[k])
                    out.append(AnnotationProposal(self.names[top], "observation", clip_index=i,
                                                  person_id=d.person_id, start_frame=clip.start_frame,
                                                  end_frame=clip.end_frame, confidence=scores[top]))
        return out


class CountScorer:
    method = "synthetic-count@1"

    def score(self, video, clip, annotations):
        return None if not clip.person_ids else 1.1 ** len(clip.person_ids)


def build(db, **stages):
    return build_import_file(INFO, [load_video_signals(db, 1)], PresenceSegmenter(), **stages)


def test_loader_reads_signals_without_writing(signals_db):
    before = signals_db.execute("SELECT total_changes()").fetchone()
    video = load_video_signals(signals_db, 1)
    assert signals_db.execute("SELECT total_changes()").fetchone() == before
    assert (video.filename, video.frame_count) == ("one.mp4", 2398)
    assert [(d.person_id, d.frame_number) for d in video.detections] == [
        ("Person_0001", 0), ("Person_0001", 24), ("Person_0002", 24), ("Person_0001", 48),
        ("Person_0002", 96)]
    assert video.detections[1].activity.label == "singing"
    assert video.detections[0].activity is None
    assert video.detections[4].expression is None  # missing signal values stay None
    with pytest.raises(LookupError):
        load_video_signals(signals_db, 99)


def test_built_file_imports_as_ai_suggestions(signals_db):
    parsed = build(signals_db, activity=[ModeActivity()], affect=[TopAffect()], scorer=CountScorer())
    run = import_file(signals_db, parsed, source_name="built.json", sha256="0" * 64)
    assert run.counts.clips_inserted == 4
    clips = list_clips(signals_db, video_id=1)
    assert [c.person_ids for c in clips] == [("Person_0001",), ("Person_0001", "Person_0002"),
                                             ("Person_0001",), ("Person_0002",)]
    assert [c.priority_score for c in clips] == pytest.approx([1.1, 1.21, 1.1, 1.1])
    labels = Counter(a.label_name for a in list_annotations(signals_db))
    assert labels == {"Singing": 1, "Visible Positive Affect": 3, "Visible Neutral Affect": 1}
    assert {(a.source, a.review_status) for a in list_annotations(signals_db)} == {("AI", "UNREVIEWED")}


def test_output_is_deterministic(signals_db):
    stages = dict(activity=[ModeActivity()], affect=[TopAffect()], scorer=CountScorer())
    first, second = build(signals_db, **stages).to_json(), build(signals_db, **stages).to_json()
    assert hashlib.sha256(first.encode()).digest() == hashlib.sha256(second.encode()).digest()
    assert stable_key("p", "clip", "a.mp4", 0, 1) == stable_key("p", "clip", "a.mp4", 0, 1)
    assert stable_key("p", "clip", "a.mp4", 0, 1) != stable_key("p", "clip", "a.mp4", 0, 2)


def test_rebuild_reimports_as_unchanged(signals_db):
    stages = dict(activity=[ModeActivity()], affect=[TopAffect()], scorer=CountScorer())
    import_file(signals_db, build(signals_db, **stages), source_name="a", sha256="0" * 64)
    again = import_file(signals_db, build(signals_db, **stages), source_name="a", sha256="0" * 64)
    assert (again.counts.inserted, again.counts.updated, again.counts.clips_inserted) == (0, 0, 0)


def test_no_activity_signals_means_no_activity_annotations(review_db):
    review_db.execute("INSERT INTO Frame VALUES ('G0', 1, 0, 0.0)")
    review_db.execute("INSERT INTO FaceDetection (person_id, frame_id, x1, y1, x2, y2, det_score)"
                      " VALUES ('Person_0001', 'G0', 0, 0, 1, 1, 0.9)")
    parsed = build(review_db, activity=[ModeActivity()])
    assert [len(v.annotations) for v in parsed.videos] == [0]  # nothing fabricated


def test_clip_level_proposals_take_the_clip_span(signals_db):
    parsed = build(signals_db, activity=[ModeActivity()])
    singing = [a for a in parsed.videos[0].annotations if a.label.name == "Singing"]
    clips = {c.key: c for c in parsed.videos[0].clips}
    assert all((a.start_frame, a.end_frame) == (clips[a.clip_key].start_frame,
                                                clips[a.clip_key].end_frame) for a in singing)


def test_unscored_clips_have_no_priority(signals_db):
    class NeverScores:
        method = "never@1"

        def score(self, video, clip, annotations):
            return None

    assert all(c.priority is None for c in build(signals_db, scorer=NeverScores()).videos[0].clips)


def test_category_mismatch_is_refused(signals_db):
    with pytest.raises(DataError, match="affect annotator ModeActivity proposed a 'activity'"):
        build(signals_db, affect=[ModeActivity()])


def test_bad_clip_reference_is_refused(signals_db):
    class Stray:
        def annotate(self, video, clips):
            return [AnnotationProposal("Singing", "activity", clip_index=99)]

    with pytest.raises(DataError, match="clip 99"):
        build(signals_db, activity=[Stray()])


def test_duplicate_proposals_are_refused(signals_db):
    class Twice(ModeActivity):
        def annotate(self, video, clips):
            return super().annotate(video, clips) * 2

    with pytest.raises(DataError, match="duplicate annotation keys"):
        build(signals_db, activity=[Twice()])


def test_concurrent_activity_labels_are_separate_records(signals_db):
    class TwoLabels:
        def annotate(self, video, clips):
            return [AnnotationProposal(name, "activity", clip_index=0, confidence=0.5)
                    for name in ("Singing", "Group Performance")]

    parsed = build(signals_db, activity=[TwoLabels()])
    import_file(signals_db, parsed, source_name="two", sha256="0" * 64)
    clip = list_clips(signals_db, video_id=1)[0]
    assert sorted(a.label_name for a in list_annotations(signals_db, clip_id=clip.clip_id)) == [
        "Group Performance", "Singing"]
