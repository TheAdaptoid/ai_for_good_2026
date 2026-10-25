from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

TABLES = ("Video", "Frame", "Person", "FaceDetection", "Activity", "Engagement")
REVIEW_TABLES = ("Label", "ReviewClip", "ReviewClipParticipant", "Annotation", "ReviewEvent")


class DataError(ValueError):
    """Invalid source values, conflicting records, or unavailable video metadata."""


class CsvImportError(Exception):
    def __init__(self, source: Path, line_number: int | None, reason: str):
        self.source = source
        self.line_number = line_number
        self.reason = reason
        location = str(source)
        if line_number is not None:
            location += f":{line_number}"
        super().__init__(f"{location}: {reason}")


@dataclass(frozen=True)
class DetectionRow:
    line_number: int
    video_title: str
    video_filename: str
    frame_number: int
    frame_id: str
    person_id: str
    source_time_seconds: float
    x1: float
    y1: float
    x2: float
    y2: float
    det_score: float


@dataclass(frozen=True)
class VideoMetadata:
    created_at: str | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class ClipInfo:
    clip_id: int
    video_id: int
    start_time_seconds: float
    end_time_seconds: float
    person_ids: tuple[str, ...]
    created_at: str
    file_path: str


def zero_counts() -> dict[str, int]:
    return dict.fromkeys(TABLES, 0)


@dataclass
class FileResult:
    source: Path
    committed: bool = False
    rows_read: int = 0
    rejected_rows: int = 0
    inserted: dict[str, int] = field(default_factory=zero_counts)
    skipped: dict[str, int] = field(default_factory=zero_counts)
    error: CsvImportError | None = None


class Source(StrEnum):
    AI = "AI"
    HUMAN = "HUMAN"


class ReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class ReviewAction(StrEnum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class LabelCategory(StrEnum):
    ACTIVITY = "activity"
    OBSERVATION = "observation"


@dataclass(frozen=True)
class Label:
    label_id: int
    name: str
    category: LabelCategory
    description: str | None
    is_active: bool


@dataclass(frozen=True)
class Annotation:
    annotation_id: int
    video_id: int
    clip_id: int | None
    person_id: str | None
    label_id: int
    label_name: str
    label_category: LabelCategory
    start_frame: int
    end_frame: int
    start_seconds: float | None  # None when the video's fps is unknown
    end_seconds: float | None
    confidence: float | None
    source: Source
    review_status: ReviewStatus
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ReviewClip:
    clip_id: int
    video_id: int
    start_frame: int
    end_frame: int
    start_seconds: float | None
    end_seconds: float | None
    person_ids: tuple[str, ...]
    priority_score: float | None  # review priority, unbounded; never a model confidence
    priority_method: str | None
    created_at: str


@dataclass(frozen=True)
class ReviewEvent:
    event_id: int
    annotation_id: int
    video_id: int
    action: ReviewAction
    prev_label_id: int | None
    new_label_id: int | None
    prev_start_frame: int | None
    prev_end_frame: int | None
    new_start_frame: int | None
    new_end_frame: int | None
    prev_person_id: str | None
    new_person_id: str | None
    prev_confidence: float | None
    new_confidence: float | None
    prev_source: Source | None
    new_source: Source
    prev_status: ReviewStatus | None
    new_status: ReviewStatus
    reviewer_id: str
    note: str | None
    created_at: str


@dataclass(frozen=True)
class ClipInput:
    import_key: str
    start_frame: int
    end_frame: int
    person_ids: tuple[str, ...] = ()
    priority_score: float | None = None
    priority_method: str | None = None


@dataclass(frozen=True)
class AnnotationInput:
    import_key: str
    label_id: int
    start_frame: int
    end_frame: int
    confidence: float | None
    person_id: str | None = None
    clip_import_key: str | None = None


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()  # distinguishes "leave person unchanged" from "set person to None"


@dataclass(frozen=True)
class AnnotationChanges:
    label_id: int | None = None
    start_frame: int | None = None
    end_frame: int | None = None
    person_id: str | None | _Unset = UNSET


@dataclass(frozen=True)
class ImportResult:
    inserted: int = 0
    updated: int = 0
    skipped_protected: int = 0
    clips_inserted: int = 0
    clips_updated: int = 0
    clips_skipped_protected: int = 0
    unchanged: int = 0
    clips_unchanged: int = 0


STAFF_TABLES = ("StaffAccount", "StaffSession")


@dataclass(frozen=True)
class StaffAccount:
    staff_id: int
    username: str  # doubles as the opaque reviewer_id in review history
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class VideoSummary:
    video_id: int
    title: str
    filename: str
    duration_seconds: float | None
    fps: float | None
    frame_count: int | None
    participant_count: int
    detection_count: int
    annotation_counts: dict[str, int]  # every ReviewStatus, zeros included
    clip_count: int
    person_clip_count: int = 0
    human_annotation_count: int = 0
    clip_status_counts: dict[str, int] = field(default_factory=dict)  # stored clips by review status


@dataclass(frozen=True)
class PresenceInterval:
    start_seconds: float
    end_seconds: float
    detection_count: int


@dataclass(frozen=True)
class VideoParticipant:
    person_id: str
    first_seconds: float
    last_seconds: float
    detection_count: int
    intervals: tuple[PresenceInterval, ...]


@dataclass(frozen=True)
class ParticipantSummary:
    person_id: str
    video_count: int
    detection_count: int


@dataclass(frozen=True)
class ParticipantVideo:
    video_id: int
    title: str
    first_seconds: float
    last_seconds: float
    detection_count: int


@dataclass(frozen=True)
class ParticipantDetail:
    person_id: str
    videos: tuple[ParticipantVideo, ...]


IMPORT_TABLES = ("ImportRun",)


@dataclass(frozen=True)
class ModelRef:
    name: str
    revision: str | None


@dataclass(frozen=True)
class ImportRun:
    """Audit record of one successful pipeline-output import."""
    run_id: int
    pipeline_name: str
    pipeline_version: str
    models: tuple[ModelRef, ...]
    generated_at: str | None
    imported_at: str
    source_name: str
    input_sha256: str
    counts: ImportResult
