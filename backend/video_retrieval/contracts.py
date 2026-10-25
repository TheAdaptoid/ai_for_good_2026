from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DetectionInfo:
    detection_id: int
    person_id: str
    video_id: int
    frame_id: str
    frame_number: int
    source_time_seconds: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class TemporalClip:
    frames: np.ndarray
    source_frame_indices: tuple[int, ...]
    source_timestamps_seconds: tuple[float, ...]
    target_timestamps_seconds: tuple[float, ...]
    requested_start_seconds: float
    requested_end_seconds: float
    reference_timestamp_seconds: float
    left_padding_count: int
    right_padding_count: int

    @property
    def unique_frame_count(self) -> int:
        return len(set(self.source_frame_indices))


@dataclass(frozen=True)
class VideoSegment:
    frames: np.ndarray
    source_frame_indices: tuple[int, ...]
    source_timestamps_seconds: tuple[float, ...]
    requested_start_seconds: float
    requested_end_seconds: float
