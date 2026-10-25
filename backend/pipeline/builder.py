import hashlib
import json
from collections.abc import Sequence

from analysis_db.contracts import DataError
from analysis_db.pipeline_import import FORMAT, ImportFile, parse_import_file
from pipeline.contracts import AnnotationProposal, ClipProposal, PipelineMetadata, VideoSignals
from pipeline.stages import ClipAnnotator, ClipSegmenter, PriorityScorer


def stable_key(pipeline: str, kind: str, *content: object) -> str:
    """Deterministic import key from content. The pipeline version is deliberately left out, so
    a newer version updates unreviewed rows in place instead of adding new ones."""
    digest = hashlib.sha256(json.dumps(content, separators=(",", ":")).encode()).hexdigest()
    return f"{pipeline}:{kind}:{digest[:20]}"


def _annotations(video: VideoSignals, clips: Sequence[ClipProposal], annotators: Sequence[ClipAnnotator],
                 category: str, stage: str) -> list[AnnotationProposal]:
    proposals = []
    for annotator in annotators:
        for proposal in annotator.annotate(video, clips):
            if proposal.label_category != category:
                raise DataError(f"{stage} annotator {type(annotator).__name__} proposed a"
                                f" {proposal.label_category!r} label; expected {category!r}")
            if proposal.clip_index is not None and not 0 <= proposal.clip_index < len(clips):
                raise DataError(f"{stage} annotator {type(annotator).__name__} referenced"
                                f" clip {proposal.clip_index}, which does not exist")
            proposals.append(proposal)
    return proposals


def build_import_file(info: PipelineMetadata, videos: Sequence[VideoSignals],
                      segmenter: ClipSegmenter, *, activity: Sequence[ClipAnnotator] = (),
                      affect: Sequence[ClipAnnotator] = (),
                      scorer: PriorityScorer | None = None) -> ImportFile:
    """Run the stages and assemble a validated import file with content-derived keys."""
    entries = []
    for video in videos:
        clips = segmenter.segment(video)
        proposals = (_annotations(video, clips, activity, "activity", "activity")
                     + _annotations(video, clips, affect, "observation", "affect"))
        clip_keys = [stable_key(info.name, "clip", video.filename, c.start_frame, c.end_frame,
                                sorted(c.person_ids)) for c in clips]
        clip_entries = []
        for index, (clip, key) in enumerate(zip(clips, clip_keys)):
            entry = {"key": key, "start_frame": clip.start_frame, "end_frame": clip.end_frame,
                     "participants": sorted(clip.person_ids)}
            score = None if scorer is None else scorer.score(
                video, clip, [p for p in proposals if p.clip_index == index])
            if score is not None:
                entry["priority"] = {"score": score, "method": scorer.method}
            clip_entries.append(entry)
        annotation_entries = []
        for p in proposals:
            clip = clips[p.clip_index] if p.clip_index is not None else None
            start, end = p.start_frame, p.end_frame
            if start is None and clip is not None and p.person_id is None:
                start, end = clip.start_frame, clip.end_frame  # clip-level: the clip's span
            entry = {"key": stable_key(info.name, "annotation", video.filename, p.label_category,
                                       p.label_name, p.person_id, start, end),
                     "label": {"name": p.label_name, "category": p.label_category},
                     "start_frame": start, "end_frame": end, "person_id": p.person_id,
                     "confidence": p.confidence}
            if p.clip_index is not None:
                entry["clip_key"] = clip_keys[p.clip_index]
            annotation_entries.append(entry)
        entries.append({"filename": video.filename, "clips": clip_entries,
                        "annotations": annotation_entries})
    data = {"format": FORMAT,
            "pipeline": {"name": info.name, "version": info.version,
                         "generated_at": info.generated_at,
                         "models": [{"name": n, "revision": r} for n, r in info.models],
                         "parameters": dict(info.parameters)},
            "videos": entries}
    # Round-trip through the parser so a builder bug can never emit a file the importer rejects.
    return parse_import_file(json.dumps(data))
