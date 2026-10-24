"""Single-instance X-CLIP classifier for in-memory RGB frame inputs.

Ported from the standalone notebook implementation. The combined
``XCLIPProcessor(...)`` call is deliberately avoided: Transformers 4.57.6 can
drop the ``videos`` keyword, so the tokenizer and image-processor components
are routed explicitly. On CUDA the local checkpoint runs in FP16 and always
with eager attention; on CPU it runs in FP32. Inference reads only local
backend assets at the pinned revision.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite
from numbers import Integral
from pathlib import Path
import re
from string import Formatter
from time import perf_counter
from traceback import clear_frames

import numpy as np

from activity_classification.contracts import (
    ActivityPrediction,
    ClassificationResult,
    RGBFrames,
)
from activity_classification.runtime import (
    ACQUISITION_COMMAND,
    DEFAULT_CACHE_DIR,
    DEFAULT_PROMPT_TEMPLATE,
    MODEL_ID,
    MODEL_REVISION,
    configure_runtime,
)


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


def validate_rgb_frames(frames: RGBFrames) -> np.ndarray | list[np.ndarray]:
    """Validate an RGB uint8 frame array or a consistent nonempty HWC sequence.

    Unselected frames are validated too, so callers learn about malformed input
    instead of silently classifying a partial selection.
    """
    if isinstance(frames, np.ndarray):
        if frames.ndim != 4 or frames.shape[-1] != 3:
            raise ValueError(
                "RGB frames must be a (T, H, W, 3) uint8 array; got shape "
                f"{frames.shape} with dtype {frames.dtype}"
            )
        if frames.dtype != np.uint8:
            raise ValueError(f"RGB frames must be uint8; got dtype {frames.dtype}")
        if frames.shape[0] == 0:
            raise ValueError("RGB frames must contain at least one frame")
        if frames.shape[1] == 0 or frames.shape[2] == 0:
            raise ValueError("RGB frame dimensions must be positive")
        return frames
    if isinstance(frames, (str, bytes)):
        raise TypeError(
            "frames must be an RGB uint8 (T, H, W, 3) array or a sequence of "
            "RGB uint8 (H, W, 3) arrays"
        )
    if isinstance(frames, Sequence):
        return _validate_frame_sequence(frames)
    raise TypeError(
        "frames must be an RGB uint8 (T, H, W, 3) array or a sequence of "
        "RGB uint8 (H, W, 3) arrays"
    )


def _validate_frame_sequence(frames: Sequence) -> list[np.ndarray]:
    if len(frames) == 0:
        raise ValueError("RGB frames must contain at least one frame")
    expected_shape: tuple[int, int] | None = None
    for index, frame in enumerate(frames):
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.dtype != np.uint8:
            raise ValueError(
                f"Frame {index} must be a uint8 (H, W, 3) numpy array; got "
                f"{type(frame).__name__} with dtype "
                f"{getattr(frame, 'dtype', None)} and ndim {getattr(frame, 'ndim', None)}"
            )
        if frame.shape[2] != 3:
            raise ValueError(
                f"Frame {index} must have three RGB channels; got shape {frame.shape}"
            )
        if frame.shape[0] == 0 or frame.shape[1] == 0:
            raise ValueError(f"Frame {index} dimensions must be positive")
        shape = (int(frame.shape[0]), int(frame.shape[1]))
        if expected_shape is None:
            expected_shape = shape
        elif shape != expected_shape:
            raise ValueError(
                f"Frame {index} must match the first frame's dimensions "
                f"{expected_shape}; got {shape}"
            )
    return list(frames)


def resolve_model_source(
    model_path: str | Path | None, cache_dir: str | Path | None
) -> tuple[bool, Path]:
    """Resolve exactly one local source: a direct snapshot or a hub cache."""
    if model_path is not None and cache_dir is not None:
        raise ValueError(
            "Provide either model_path (a directory holding the pinned checkpoint "
            "assets) or cache_dir (a Hugging Face hub cache), not both"
        )
    if model_path is not None:
        path = Path(model_path)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", str(model_path)):
            raise ValueError(
                f"model_path must be a local directory path; URI schemes are not allowed: {model_path}"
            )
        if not path.is_dir():
            raise ValueError(
                f"model_path must be an existing directory with the pinned "
                f"checkpoint assets: {path}"
            )
        return True, path
    return False, DEFAULT_CACHE_DIR if cache_dir is None else Path(cache_dir)


def _validate_checkpoint_dimensions(vision_config) -> tuple[int, int]:
    num_frames = getattr(vision_config, "num_frames", None)
    if isinstance(num_frames, bool) or not isinstance(num_frames, Integral) or num_frames <= 0:
        raise RuntimeError(
            f"The checkpoint must declare a positive integer vision_config.num_frames; "
            f"got {num_frames!r}."
        )
    image_size = getattr(vision_config, "image_size", None)
    if isinstance(image_size, bool) or not isinstance(image_size, Integral) or image_size <= 0:
        raise RuntimeError(
            f"The checkpoint must declare a positive integer vision_config.image_size; "
            f"got {image_size!r}."
        )
    return int(num_frames), int(image_size)


class XCLIPClassifier:
    """Explicitly load one pinned X-CLIP checkpoint from local backend assets.

    The constructor performs the (single) model load; repeated ``classify``
    calls reuse it. No factory, cache, or automatic CPU fallback exists.
    """

    def __init__(
        self,
        *,
        device: str = "auto",
        model_path: str | Path | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        started = perf_counter()
        use_direct_path, cache_root = resolve_model_source(model_path, cache_dir)
        configure_runtime(offline=True, cache_dir=cache_root)
        import torch

        if device == "auto":
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                self.device = torch.device("cuda", torch.cuda.current_device())
            else:
                self.device = torch.device("cpu")
        else:
            self.device = torch.device(device)
            # Normalize a bare CUDA choice to its actual current index.
            if self.device.type == "cuda" and self.device.index is None:
                self.device = torch.device("cuda", torch.cuda.current_device())
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is unavailable. Check the NVIDIA driver and PyTorch CUDA "
                "installation, or select device='cpu'."
            )
        self.dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.model_id = MODEL_ID
        self.model_revision = MODEL_REVISION

        from huggingface_hub import snapshot_download
        from transformers import XCLIPModel, XCLIPProcessor

        try:
            if use_direct_path:
                local_dir = str(model_path)
            else:
                local_dir = snapshot_download(
                    repo_id=MODEL_ID,
                    revision=MODEL_REVISION,
                    cache_dir=cache_root,
                    local_files_only=True,
                )
            snapshot_dir = Path(local_dir)
            if not (snapshot_dir / "tokenizer.json").is_file():
                missing = [
                    name for name in ("vocab.json", "merges.txt")
                    if not (snapshot_dir / name).is_file()
                ]
                if missing:
                    raise FileNotFoundError(
                        f"Missing tokenizer assets in {snapshot_dir}: {', '.join(missing)}; "
                        "provide these files or tokenizer.json."
                    )
            self.processor = XCLIPProcessor.from_pretrained(
                local_dir, local_files_only=True, trust_remote_code=False,
            )
            self.model = XCLIPModel.from_pretrained(
                local_dir, local_files_only=True, use_safetensors=True,
                trust_remote_code=False, dtype=self.dtype, attn_implementation="eager",
            )
        except (OSError, ValueError, KeyError) as exc:
            if use_direct_path:
                raise RuntimeError(
                    f"model_path '{local_dir}' did not yield loadable assets for the "
                    f"pinned checkpoint revision {MODEL_REVISION}. It must contain "
                    f"exactly the pinned revision {MODEL_REVISION} assets; run "
                    f"`{ACQUISITION_COMMAND}` from the backend directory to acquire "
                    "them, then retry with the resulting snapshot directory."
                ) from exc
            raise RuntimeError(
                f"The local X-CLIP cache is missing or incomplete for revision "
                f"{MODEL_REVISION} at {cache_root}. From the backend directory, run "
                f"`{ACQUISITION_COMMAND}` to acquire the pinned checkpoint, then retry."
            ) from exc

        vision_config = getattr(self.model.config, "vision_config", None)
        self.num_frames, self.image_size = _validate_checkpoint_dimensions(vision_config)

        self.model = self.model.to(self.device).eval()
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        self.load_time_seconds = float(perf_counter() - started)

    def classify(
        self,
        frames: RGBFrames,
        activities: list[str],
        *,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        descriptions: Mapping[str, str] | None = None,
    ) -> ClassificationResult:
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
            rgb = validate_rgb_frames(frames)
            indices = np.linspace(0, len(rgb) - 1, self.num_frames, dtype=np.int64)
            selected = [rgb[int(index)] for index in indices]

            # Transformers 4.57.6's inherited processor call can drop videos=.
            # Use its checkpoint components directly to preserve video routing.
            inputs.update(self.processor.tokenizer(
                [candidate.prompt for candidate in candidates],
                padding=True, truncation=False, return_tensors="pt",
                return_token_type_ids=False,
            ))
            limit = self.model.config.text_config.max_position_embeddings
            if inputs["input_ids"].shape[-1] > limit:
                raise ValueError(
                    f"A prompt exceeds the checkpoint limit of {limit} tokens; "
                    "shorten it. Prompts are never truncated."
                )
            inputs.update(self.processor.image_processor.preprocess(
                videos=selected, return_tensors="pt", input_data_format="channels_last",
            ))
            expected_shape = (1, self.num_frames, 3, self.image_size, self.image_size)
            if tuple(inputs["pixel_values"].shape) != expected_shape:
                raise ValueError(f"Expected pixel_values shape {expected_shape}")
            preprocessed = perf_counter()

            with torch.inference_mode():
                # Preserve integer token dtypes; cast floating inputs on CUDA.
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
            allocated = (
                float(torch.cuda.max_memory_allocated(self.device) / 2**20) if cuda else None
            )
            reserved = (
                float(torch.cuda.max_memory_reserved(self.device) / 2**20) if cuda else None
            )
            if not all(isfinite(value) for value in score_values):
                raise ValueError("Softmax scores must all be finite")
            if not all(isfinite(value) for value in logit_values):
                raise ValueError("Model logits must all be finite")
            # Stable sort: ties keep the original candidate order.
            order = sorted(range(len(candidates)), key=lambda index: -score_values[index])
            result = ClassificationResult(
                predictions=tuple(
                    ActivityPrediction(
                        label=candidates[index].label,
                        prompt=candidates[index].prompt,
                        logit=float(logit_values[index]),
                        score=float(score_values[index]),
                    )
                    for index in order
                ),
                model=MODEL_ID,
                model_revision=self.model_revision,
                device=str(self.device),
                dtype=str(self.dtype),
                input_frame_count=int(len(rgb)),
                num_frames=int(self.num_frames),
                selected_frame_indices=tuple(int(index) for index in indices),
                score_type="candidate_relative_softmax",
                preprocessing_time_seconds=float(preprocessed - started),
                inference_time_seconds=float(inferred - preprocessed),
                total_time_seconds=0.0,
                peak_gpu_memory_allocated_mib=allocated,
                peak_gpu_memory_reserved_mib=reserved,
            )
            result = replace(
                result, total_time_seconds=float(perf_counter() - started)
            )
            measured = {
                "preprocessing_time_seconds": result.preprocessing_time_seconds,
                "inference_time_seconds": result.inference_time_seconds,
                "total_time_seconds": result.total_time_seconds,
                "peak_gpu_memory_allocated_mib": result.peak_gpu_memory_allocated_mib,
                "peak_gpu_memory_reserved_mib": result.peak_gpu_memory_reserved_mib,
            }
            if any(isinstance(value, float) and not isfinite(value) for value in measured.values()):
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
