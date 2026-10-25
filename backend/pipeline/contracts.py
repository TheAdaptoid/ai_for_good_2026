from dataclasses import dataclass


@dataclass(frozen=True)
class ExpressionScores:
    positive: float
    neutral: float
    negative: float


@dataclass(frozen=True)
class ActivitySignal:
    """A raw activity-model prediction over a frame window (the Activity table)."""
    label: str
    start_frame: int
    end_frame: int
    confidence: float


@dataclass(frozen=True)
class DetectionSignal:
    detection_id: int
    person_id: str
    frame_number: int
    seconds: float
    expression: ExpressionScores | None
    activity: ActivitySignal | None


@dataclass(frozen=True)
class VideoSignals:
    """Read-only machine signals for one video, ordered by frame then participant."""
    video_id: int
    filename: str
    fps: float | None
    frame_count: int | None
    detections: tuple[DetectionSignal, ...]


@dataclass(frozen=True)
class ClipProposal:
    start_frame: int
    end_frame: int
    person_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnnotationProposal:
    """One label claim. ``clip_index`` points into the segmenter's list; with no participant and
    no span it is a clip-level annotation covering the clip."""
    label_name: str
    label_category: str
    clip_index: int | None = None
    person_id: str | None = None
    start_frame: int | None = None
    end_frame: int | None = None
    confidence: float | None = None  # model certainty in this prediction, never review priority


@dataclass(frozen=True)
class PipelineMetadata:
    name: str
    version: str
    generated_at: str | None = None
    models: tuple[tuple[str, str | None], ...] = ()  # (model name, revision)
    parameters: tuple[tuple[str, str | int | float | bool | None], ...] = ()  # run configuration
