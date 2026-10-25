from dataclasses import dataclass

INTERVAL_SECONDS = 15.0
SAMPLE_COUNT = 32
BATCH_SIZE = 2
PRECISION = "fp32"
PREFETCH_BATCHES = 2
BENCHMARK_SIZE = 100
SEED = 42
ACTIVITIES = (
    "Dancing", "Rapping", "Singing", "Playing sports", "Playing games",
    "Running", "Walking", "Sitting and listening", "Drawing or painting",
)


@dataclass(frozen=True)
class FrameJob:
    frame_id: str
    video_id: int
    frame_number: int
    source_time_seconds: float
    anchor_detection_id: int
