"""Local RGB sampling and prompted X-CLIP activity recognition."""

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from numbers import Integral
import os
from pathlib import Path
import re
from string import Formatter
from time import perf_counter
from traceback import clear_frames

import cv2
import numpy as np


MODEL_ID = "microsoft/xclip-base-patch16-zero-shot"
MODEL_REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"
NUM_FRAMES = 32
DEFAULT_PROMPT_TEMPLATE = "A video of people {activity}."
PROJECT_DIR = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_DIR / ".cache" / "huggingface" / "hub"


def configure_local_runtime() -> None:
    """Disable online access and tracking before loading ML dependencies."""
    os.environ.update({
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "WANDB_DISABLED": "true",
        "WANDB_MODE": "disabled",
        "COMET_MODE": "DISABLED",
        "TOKENIZERS_PARALLELISM": "false",
        "HF_HOME": str(PROJECT_DIR / ".cache" / "huggingface"),
    })


configure_local_runtime()


@dataclass(frozen=True)
class Candidate:
    key: str
    label: str
    prompt: str


def prepare_candidates(
    activities: list[str],
    *,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    descriptions: Mapping[str, str] | None = None,
) -> list[Candidate]:
    """Build stable ASCII keys and prompts from whitespace-trimmed labels."""
    if not isinstance(activities, list):
        raise TypeError("activities must be a nonempty list of strings")
    if not activities:
        raise ValueError("activities must be a nonempty list of strings")
    if not isinstance(prompt_template, str):
        raise TypeError("prompt_template must be a string")
    for _, field, spec, conversion in Formatter().parse(prompt_template):
        if field is not None and (field != "activity" or spec or conversion):
            raise ValueError("Only the plain {activity} template field is supported")

    labels = []
    seen_labels = set()
    for label in activities:
        if not isinstance(label, str):
            raise TypeError("Each activity label must be a string")
        label = label.strip()
        if not label:
            raise ValueError("Activity labels must not be blank")
        if label.casefold() in seen_labels:
            raise ValueError(f"Duplicate activity label: {label!r}")
        seen_labels.add(label.casefold())
        labels.append(label)

    if descriptions is not None:
        if not isinstance(descriptions, Mapping):
            raise TypeError("descriptions must map original labels to full descriptions")
        if set(descriptions) != set(labels):
            raise ValueError("descriptions must exactly cover the original activity labels")

    candidates = []
    seen_keys = set()
    for label in labels:
        key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        if not key or key in seen_keys:
            raise ValueError(f"Activity label has an empty or colliding ASCII key: {label!r}")
        seen_keys.add(key)
        if descriptions is not None:
            prompt = descriptions[label]
            if not isinstance(prompt, str):
                raise TypeError("Each description must be a nonempty string")
        else:
            activity = label.lower() if prompt_template == DEFAULT_PROMPT_TEMPLATE else label
            prompt = prompt_template.format(activity=activity)
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("Activity prompts must not be blank")
        candidates.append(Candidate(key, label, prompt))
    return candidates


def device_info() -> dict:
    """Report the auto-selected device and memory as reported by PyTorch."""
    import torch

    available = torch.cuda.is_available()
    device = torch.device("cuda" if available else "cpu")
    info = {
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "cuda_available": available,
        "gpu_name": None,
        "total_vram_mib": None,
        "free_vram_mib": None,
    }
    if available:
        free, total = torch.cuda.mem_get_info(device)
        info.update({
            "gpu_name": torch.cuda.get_device_name(device),
            "total_vram_mib": total / 2**20,
            "free_vram_mib": free / 2**20,
        })
    return info


class XCLIPRecognizer:
    """Explicitly load one pinned X-CLIP checkpoint from the local cache."""

    def __init__(self, device: str = "auto"):
        started = perf_counter()
        configure_local_runtime()
        import torch

        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        ) if device == "auto" else torch.device(device)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is unavailable. Check the NVIDIA driver and PyTorch CUDA "
                "installation, or select device='cpu'."
            )
        self.dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.model_revision = MODEL_REVISION

        from huggingface_hub import snapshot_download
        from transformers import XCLIPModel, XCLIPProcessor

        try:
            local_dir = snapshot_download(
                repo_id=MODEL_ID,
                revision=MODEL_REVISION,
                cache_dir=CACHE_DIR,
                local_files_only=True,
            )
            snapshot_path = Path(local_dir)
            if not (snapshot_path / "tokenizer.json").is_file():
                missing = [
                    name for name in ("vocab.json", "merges.txt")
                    if not (snapshot_path / name).is_file()
                ]
                if missing:
                    raise FileNotFoundError(
                        f"Missing tokenizer assets in {snapshot_path}: {', '.join(missing)}; "
                        "provide these files or tokenizer.json."
                    )
            self.processor = XCLIPProcessor.from_pretrained(
                local_dir, local_files_only=True, trust_remote_code=False,
            )
            self.model = XCLIPModel.from_pretrained(
                local_dir,
                local_files_only=True,
                use_safetensors=True,
                trust_remote_code=False,
                dtype=self.dtype,
                attn_implementation="eager",
            )
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError(
                f"The local X-CLIP cache is missing or incomplete for {MODEL_REVISION}. "
                "From notebooks/, run `uv run --locked python download_model.py` "
                "to acquire the pinned checkpoint, then retry."
            ) from exc

        vision_config = getattr(self.model.config, "vision_config", None)
        if getattr(vision_config, "num_frames", None) != NUM_FRAMES:
            raise RuntimeError(
                f"The pinned X-CLIP checkpoint must use {NUM_FRAMES} native frames; "
                f"got {getattr(vision_config, 'num_frames', None)!r}."
            )
        self.model = self.model.to(self.device).eval()
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        self.load_time_seconds = float(perf_counter() - started)

    def classify(
        self,
        video_path: str,
        activities: list[str],
        *,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        descriptions: Mapping[str, str] | None = None,
        video_id: str | None = None,
    ) -> dict:
        """Rank candidates with relative softmax scores, not calibrated probabilities.

        Timings exclude model loading. CUDA peaks include the resident model.
        No per-call tensors are retained, including by failed forward tracebacks.
        """
        started = perf_counter()
        import torch

        cuda = self.device.type == "cuda"
        inputs = {}
        outputs = logits = probabilities = None
        try:
            if cuda:
                torch.cuda.synchronize(self.device)
                torch.cuda.reset_peak_memory_stats(self.device)
            candidates = prepare_candidates(
                activities, prompt_template=prompt_template, descriptions=descriptions,
            )
            if video_id is not None:
                if not isinstance(video_id, str):
                    raise TypeError("video_id must be a JSON-compatible string")
                if not video_id.strip():
                    raise ValueError("video_id must not be blank")
                try:
                    video_id.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ValueError("video_id must be a JSON-compatible Unicode string") from exc
            sampled = sample_video(video_path, num_frames=NUM_FRAMES)
            if video_id is None:
                video_id = Path(video_path).stem

            # Transformers 4.57.6's inherited processor call can drop videos=.
            # Use its checkpoint components directly to preserve video routing.
            inputs.update(self.processor.tokenizer(
                [candidate.prompt for candidate in candidates],
                padding=True, truncation=False, return_tensors="pt",
                return_token_type_ids=False,
            ))
            max_tokens = self.model.config.text_config.max_position_embeddings
            if inputs["input_ids"].shape[-1] > max_tokens:
                raise ValueError(
                    f"A prompt exceeds the checkpoint limit of {max_tokens} tokens; "
                    "shorten it. Prompts are never truncated."
                )
            # BaseImageProcessor.__call__ also requires images, not videos;
            # VideoMAE's preprocess accepts the correct videos keyword.
            inputs.update(self.processor.image_processor.preprocess(
                videos=sampled.frames, return_tensors="pt",
            ))
            if tuple(inputs["pixel_values"].shape) != (1, NUM_FRAMES, 3, 224, 224):
                raise ValueError("Expected pixel_values shape (1, 32, 3, 224, 224)")
            preprocessed = perf_counter()

            with torch.inference_mode():
                for name in inputs:
                    options = {"device": self.device}
                    if inputs[name].is_floating_point():
                        options["dtype"] = self.dtype
                    inputs[name] = inputs[name].to(**options)
                outputs = self.model(**inputs)
                logits = outputs.logits_per_video[0].float()
                if not torch.isfinite(logits).all().item():
                    raise ValueError("Model logits must all be finite before softmax")
                probabilities = torch.softmax(logits, dim=-1)
                logit_values = logits.cpu().tolist()
                score_values = probabilities.cpu().tolist()
                if cuda:
                    torch.cuda.synchronize(self.device)
            inferred = perf_counter()
            allocated = float(torch.cuda.max_memory_allocated(self.device) / 2**20) if cuda else None
            reserved = float(torch.cuda.max_memory_reserved(self.device) / 2**20) if cuda else None
            scores = dict(zip((candidate.key for candidate in candidates), score_values, strict=True))
            result = {
                "video_id": video_id,
                "clip_start": 0.0,
                "clip_end": float(sampled.duration_seconds),
                "model": MODEL_ID,
                "model_revision": self.model_revision,
                "activity": max(scores, key=scores.get),
                "scores": scores,
                "logits": dict(zip((candidate.key for candidate in candidates), logit_values, strict=True)),
                "labels": {candidate.key: candidate.label for candidate in candidates},
                "prompts": {candidate.key: candidate.prompt for candidate in candidates},
                "score_type": "candidate_relative_softmax",
                "num_frames": NUM_FRAMES,
                "unique_sampled_frames": len(set(sampled.indices)),
                "sampled_frame_indices": [int(index) for index in sampled.indices],
                "sampling_method": "uniform_frame_indices",
                "device": str(self.device),
                "dtype": str(self.dtype),
                "preprocessing_time_seconds": float(preprocessed - started),
                "inference_time_seconds": float(inferred - preprocessed),
                "total_time_seconds": 0.0,
                "peak_gpu_memory_allocated_mib": allocated,
                "peak_gpu_memory_reserved_mib": reserved,
            }
            if not all(isfinite(value) for value in score_values):
                raise ValueError("Softmax scores must all be finite")
            result["total_time_seconds"] = float(perf_counter() - started)
            if any(isinstance(value, float) and not isfinite(value) for value in result.values()):
                raise ValueError("Classification measurements must all be finite")
            return result
        except BaseException as exc:
            # A retained exception must not keep forward intermediates on GPU.
            clear_frames(exc.__traceback__)
            if cuda and isinstance(exc, torch.OutOfMemoryError):
                raise RuntimeError(
                    "CUDA ran out of memory during classification. Free GPU memory "
                    "or explicitly retry with device='cpu'. No CPU retry was attempted."
                ) from exc
            raise
        finally:
            inputs.clear()
            outputs = logits = probabilities = None


@lru_cache(maxsize=1)
def get_recognizer(device: str = "auto") -> XCLIPRecognizer:
    """Reuse the initialized recognizer for repeated calls with the same device."""
    return XCLIPRecognizer(device=device)


def classify_activity(
    video_path: str,
    activities: list[str],
    *,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    descriptions: Mapping[str, str] | None = None,
    video_id: str | None = None,
    device: str = "auto",
) -> dict:
    """Classify a local video using the cached recognizer for the requested device."""
    recognizer = get_recognizer(device)
    return recognizer.classify(
        video_path, activities, prompt_template=prompt_template,
        descriptions=descriptions, video_id=video_id,
    )


@dataclass
class SampledVideo:
    frames: list[np.ndarray]
    indices: list[int]
    fps: float
    frame_count: int
    width: int
    height: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps


def sample_video(
    video_path: str | Path, *, num_frames: int = NUM_FRAMES
) -> SampledVideo:
    """Sample local video as native-size RGB uint8 frames with bounded memory.

    Prefer indexed decoding. If frame count or seeking is unreliable, reopen
    once to count frames and once to retain only the requested unique samples.
    Short clips repeat references to the same decoded RGB arrays.
    """
    if isinstance(num_frames, bool) or not isinstance(num_frames, Integral) or num_frames <= 0:
        raise ValueError("num_frames must be a positive integer (not a boolean)")
    if not isinstance(video_path, (str, Path)):
        raise TypeError("video_path must be a local file path (str or Path)")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", str(video_path)):
        raise ValueError("Only local file paths are supported; URI schemes are not allowed")
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Video path must be a readable regular file: {path}")
    with path.open("rb"):
        pass

    try:
        # VideoCapture can otherwise treat a still image as a one-frame video.
        if cv2.haveImageReader(str(path)):
            raise ValueError(f"Expected a video file, not a still image: {path}")
        decoded = None
        with _video_capture(path) as capture:
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if not isfinite(fps) or fps <= 0:
                raise ValueError(f"Video FPS must be finite and positive: {path} (FPS={fps})")
            count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if isfinite(count) and count > 0 and count.is_integer():
                frame_count = int(count)
                indices = _sample_indices(frame_count, num_frames)
                decoded = _try_indexed_frames(capture, indices)

        if decoded is None:
            frame_count = _count_frames(path)
            indices = _sample_indices(frame_count, num_frames)
            decoded = _sequential_frames(path, indices)

        frames = [decoded[index] for index in indices]
        height, width = frames[0].shape[:2]
        return SampledVideo(frames, indices, fps, frame_count, width, height)
    except cv2.error as exc:
        raise ValueError(f"OpenCV could not sample video {path}: {exc}") from exc


@contextmanager
def _video_capture(path: Path):
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open video file: {path}")
        orientation = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
        if orientation is not None:
            capture.set(orientation, 1)
        yield capture
    finally:
        capture.release()


def _sample_indices(frame_count: int, num_frames: int) -> list[int]:
    return np.linspace(0, frame_count - 1, num_frames, dtype=np.int64).tolist()


def _try_indexed_frames(capture, indices: list[int]) -> dict[int, np.ndarray] | None:
    decoded = {}
    try:
        for index in sorted(set(indices)):
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                return None
            position = capture.get(cv2.CAP_PROP_POS_FRAMES)
            if not isfinite(position) or abs(position - index) > 0.5:
                return None
            ok, frame = capture.read()
            if not ok or frame is None:
                return None
            decoded[index] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    except cv2.error:
        # Some backends raise rather than returning False for unsupported seeks.
        return None
    return decoded


def _count_frames(path: Path) -> int:
    count = 0
    with _video_capture(path) as capture:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            count += 1
    if count == 0:
        raise ValueError(f"Empty video stream (no frames decoded): {path}")
    return count


def _sequential_frames(path: Path, indices: list[int]) -> dict[int, np.ndarray]:
    requested = set(indices)
    decoded = {}
    with _video_capture(path) as capture:
        for index in range(indices[-1] + 1):
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError(
                    f"Cannot reproduce requested video frame range; stopped at frame {index}: {path}"
                )
            if index in requested:
                decoded[index] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return decoded
