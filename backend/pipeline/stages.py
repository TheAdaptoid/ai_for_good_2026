"""One typed interface per stage (Constitution VII): swapping a model touches only its stage."""

from collections.abc import Sequence
from typing import Protocol

from pipeline.contracts import AnnotationProposal, ClipProposal, VideoSignals


class ClipSegmenter(Protocol):
    def segment(self, video: VideoSignals) -> list[ClipProposal]: ...


class ClipAnnotator(Protocol):
    """Used for both activity annotators and visible-affect annotators."""

    def annotate(self, video: VideoSignals,
                 clips: Sequence[ClipProposal]) -> list[AnnotationProposal]: ...


class PriorityScorer(Protocol):
    method: str  # stored with each score, e.g. "positive-affect-per-participant@1"

    def score(self, video: VideoSignals, clip: ClipProposal,
              annotations: Sequence[AnnotationProposal]) -> float | None: ...
