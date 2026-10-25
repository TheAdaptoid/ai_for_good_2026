from dataclasses import dataclass, field
from pathlib import Path

TABLES = ("Video", "Frame", "Person", "FaceDetection", "Activity", "Engagement")


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
