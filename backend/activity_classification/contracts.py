from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

type RGBFrames = NDArray[np.uint8] | Sequence[NDArray[np.uint8]]


@dataclass(frozen=True)
class PreparedBatch:
    """CPU tensors only; no torch import is required to import this contract."""

    inputs: dict
    candidates: tuple
    input_frame_counts: tuple[int, ...]
    selected_frame_indices: tuple[tuple[int, ...], ...]
    preprocessing_time_seconds: float


@dataclass(frozen=True)
class ActivityPrediction:
    label: str
    prompt: str
    logit: float
    score: float


@dataclass(frozen=True)
class ClassificationResult:
    predictions: tuple[ActivityPrediction, ...]
    model: str
    model_revision: str
    device: str
    dtype: str
    input_frame_count: int
    num_frames: int
    selected_frame_indices: tuple[int, ...]
    score_type: Literal["candidate_relative_softmax"]
    preprocessing_time_seconds: float
    inference_time_seconds: float
    total_time_seconds: float
    peak_gpu_memory_allocated_mib: float | None
    peak_gpu_memory_reserved_mib: float | None
