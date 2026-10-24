from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionInfo:
    detection_id: int
    person_id: str
    video_id: int
    frame_id: str
    frame_number: int
    source_time_seconds: float
    bbox: tuple[float, float, float, float]
