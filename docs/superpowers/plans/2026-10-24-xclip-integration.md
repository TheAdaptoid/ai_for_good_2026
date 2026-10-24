# Self-Contained X-CLIP Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify an existing detection's local video clip and compare 32 consecutive frames against 32 uniform samples over 5, 10, and 15 seconds in a focused notebook.

**Architecture:** Port the working notebook inference code into an independent backend package that accepts RGB frames and loads its own local checkpoint. Add timestamp-based temporal sampling alongside the existing retrieval API. A backend-local notebook joins these APIs using read-only database discovery and human-reference quality comparisons.

**Tech Stack:** Python 3.13, uv, PyTorch 2.8.0, Transformers 4.57.6, PyAV, NumPy, SQLite, Jupyter, Matplotlib, pytest.

## Global Constraints

- Approved spec: `docs/superpowers/specs/2026-10-24-xclip-integration-design.md`.
- All paths below are repository-relative; all shell commands run from `backend/` unless stated otherwise.
- `backend/` must be self-contained except for the SQLite database and original video files.
- Port code from `notebooks/activity_recognition.py`; do not import it or depend on its environment, downloader, or model cache. Leave that project unchanged.
- Keep all sponsor data, frames, crops, predictions, and model inference local.
- Keep `VideoRetriever.get_clip()` and its index-based decoder unchanged.
- Use `microsoft/xclip-base-patch16-zero-shot`, revision `6746d6a5202bf24300cd9bf36f457f174483d41b`.
- Read the required frame count from `model.config.vision_config.num_frames`; the pinned checkpoint specifies 32 frames, 224-pixel image inputs, and a 77-token text context.
- Automatic device selection uses CUDA when available and CPU otherwise; CUDA FP16, CPU FP32. Do not silently switch devices after an inference error.
- Model inference uses local assets only; acquisition is an explicit separate command.
- The notebook makes no SQLite writes or automatic result exports. No persistent extracted-image dataset.
- Save the new notebook with outputs cleared and execution counts unset.
- Preserve existing user changes in `backend/notebooks/video_retrieval_validation.ipynb` and `notebooks/activity_recognition.ipynb`.
- Do not commit files unless explicitly requested. The commit steps in generic skill examples do not apply here.
- No batch processing, Activity writes/schema changes, tracking, person-centered cropping, or engagement implementation.

## Execution strategy and file ownership

Optimize for the hackathon: one foundation step, three bounded implementation lanes, one integration pass. Do not add a build system, general inference framework, persistent frame cache, or alternate video decoder.

```text
Task 1: backend environment + frozen classifier contracts (coordinator)
                          |
             +------------+------------+
             |            |            |
          Task 2       Task 3        Task 4
         classifier    temporal      notebook and
         + runtime     retrieval     synthetic notebook smoke
             |            |            |
             +------------+------------+
                          |
               Task 5: integration + local verification
```

Tasks 2 and 3 run concurrently. Task 4 can be authored concurrently against the contracts below; its end-to-end checks wait for Tasks 2 and 3. Assign exclusive ownership of files; the coordinator alone owns `pyproject.toml`, `uv.lock`, and final README integration. Do not run parallel `uv sync` processes or concurrent real-model GPU jobs.

| Owner | Files | Responsibility |
| --- | --- | --- |
| Coordinator | `backend/pyproject.toml`, `backend/uv.lock`, `backend/.gitignore`, `backend/README.md` | Environment, setup, final verification |
| Coordinator, then classifier worker | `backend/activity_classification/__init__.py`, `contracts.py` | Freeze public contract; export classifier after implementation |
| Classifier worker | `backend/activity_classification/runtime.py`, `classifier.py`, `download_model.py`; `backend/tests/test_activity_classification.py`, `test_activity_runtime.py` | Port inference, local assets, runtime isolation |
| Retrieval worker | `backend/video_retrieval/contracts.py`, `retrieval.py`, `__init__.py`; `backend/tests/conftest.py`, `test_video_retrieval.py`, `test_video_temporal_sampling.py` | Add sampler; share existing synthetic-video fixtures |
| Notebook worker | `backend/notebooks/activity_classification.ipynb`, `backend/tests/test_activity_notebook.py` | Four-condition experiment and in-memory execution smoke |

No worker modifies the existing notebooks. Workers return file lists, exact verification results, and any integration issue. The coordinator reviews each diff, checks the frozen interfaces, and resolves cross-lane issues before Task 5.

## Frozen interfaces

### Classifier contract

`backend/activity_classification/contracts.py`:

```python
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

type RGBFrames = NDArray[np.uint8] | Sequence[NDArray[np.uint8]]


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
```

`backend/activity_classification/classifier.py`:

```python
class XCLIPClassifier:
    def __init__(
        self, *, device: str = "auto",
        model_path: str | Path | None = None,
        cache_dir: str | Path | None = None,
    ) -> None: ...

    def classify(
        self, frames: RGBFrames, activities: list[str], *,
        prompt_template: str = "A video of people {activity}.",
        descriptions: Mapping[str, str] | None = None,
    ) -> ClassificationResult: ...
```

Expose `load_time_seconds`, `num_frames`, `device`, and `dtype` on the initialized classifier. Constructor invocation explicitly loads the checkpoint; repeated `.classify()` calls reuse it. Predictions are descending by score, with stable candidate order for ties. Selected indices refer to supplied input slots, not original video frame numbers.

### Temporal retrieval contract

Add to `backend/video_retrieval/contracts.py` and export from its package:

```python
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
```

Add to `VideoRetriever`:

```python
def get_temporal_clip(
    self, detection_id: int, interval_seconds: float, sample_count: int = 32,
) -> TemporalClip: ...
```

Temporal windows center on stored `source_time_seconds`. Returned source/reference times are relative to the first decoded frame's PTS. Include both target endpoints for counts above one; for count one, sample the center. Return actual source indices and strict out-of-range padding counts. With an even count, no slot is guaranteed to be the exact detection frame.

---

## Task 1: Prepare the backend environment and freeze contracts

**Owner:** Coordinator. **Dependency:** none.

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`, `backend/.gitignore`.
- Create: `backend/activity_classification/contracts.py`, `backend/activity_classification/__init__.py`.

**Consumes:** Existing backend uv project and approved frozen interfaces.
**Produces:** Backend-owned ML environment and the exact result types above.

- [ ] **1. Inspect status and baseline configuration.** Read `pyproject.toml`, `.python-version`, and the existing inference/downloader source. Run `git status --short` and preserve unrelated changes. Do not run or clear the old notebooks.
- [ ] **2. Declare the working ML stack locally.** Retain existing PyAV, NumPy, and dev dependencies. Add the following runtime requirements and uv index settings:

```toml
# Retain Python minimum 3.13; cap to the tested interpreter line for pinned torch.
requires-python = ">=3.13,<3.14"

# Add to project.dependencies:
"torch==2.8.0",
"transformers==4.57.6",
"huggingface-hub>=0.34,<1",
"safetensors>=0.4.3,<1",
"pillow>=10,<13",

# Add to dependency-groups.dev:
"ipykernel>=6.29,<8",
"nbformat>=5.10,<6",
"nbclient>=0.10,<1",

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cu128" }
```

The existing notebook lock includes a CPython 3.13 Linux wheel for this torch build. The Python upper bound prevents promising unverified Python 3.14 compatibility and universal-lock wheel conflicts. Pillow is a runtime dependency because the checkpoint image processor needs it even without Matplotlib. No OpenCV, torchvision, pandas, or sibling path dependencies.

- [ ] **3. Write the frozen contracts above.** Initially export `ActivityPrediction`, `ClassificationResult`, and `RGBFrames` from `__init__.py`. The classifier worker later adds `XCLIPClassifier`. No model or HF imports on package import.
- [ ] **4. Ensure backend model-cache ignores.** The existing `.cache` rule already covers the directory; add a labeled `/.cache/huggingface/` rule only if useful for clarity. Do not modify root ignore rules.
- [ ] **5. Resolve and verify the backend environment once.**

```bash
uv lock
uv sync --locked
uv run --locked python -c "import torch; from transformers import XCLIPModel, XCLIPProcessor; from activity_classification import ClassificationResult; print(torch.__version__, torch.cuda.is_available())"
uv run --locked pytest -q
```

Expected: lock resolves, imports succeed, existing tests pass. Record any baseline skip/failure and distinguish it from implementation failures. Existing historical test counts are not current verification evidence.

## Task 2: Port the standalone classifier and backend-local model setup

**Owner:** Classifier worker. **Dependency:** Task 1. **Parallel with:** Tasks 3 and 4 authoring.

**Files:**
- Create: `backend/activity_classification/runtime.py`, `classifier.py`, `download_model.py`.
- Modify: `backend/activity_classification/__init__.py`.
- Create: `backend/tests/test_activity_classification.py`, `test_activity_runtime.py`.

**Consumes:** `RGBFrames`, `ActivityPrediction`, `ClassificationResult` from Task 1.
**Produces:** `XCLIPClassifier` and `python -m activity_classification.download_model [--cache-dir PATH]`.

- [ ] **1. Write meaningful failing frame-input and inference tests.** Port the fake tokenizer/image processor/model patterns from `notebooks/tests/test_classification.py` and `test_runtime.py` by copying the necessary code, not importing it. Use real small CPU tensors and `XCLIPClassifier.__new__()` to attach fake model/processor components. Fake config must supply `vision_config.num_frames`, `vision_config.image_size`, and `text_config.max_position_embeddings`. The fake combined processor call must raise, detecting accidental use of broken routing.

Representative acceptance assertions, using a `fake_classifier` fixture with eight required frames and logits `[1.0, 3.0]`:

```python
def test_frames_are_adapted_and_labels_remain_aligned(fake_classifier):
    frames = np.zeros((32, 8, 12, 3), dtype=np.uint8)
    result = fake_classifier.classify(frames, ["Walking", "Dancing"])
    assert result.selected_frame_indices == (0, 4, 8, 13, 17, 22, 26, 31)
    assert [p.label for p in result.predictions] == ["Dancing", "Walking"]
    assert [p.logit for p in result.predictions] == [3.0, 1.0]
    assert sum(p.score for p in result.predictions) == pytest.approx(1.0)
    assert result.predictions[0].prompt == "A video of people dancing."
    assert result.score_type == "candidate_relative_softmax"


@pytest.mark.parametrize("frames", [
    np.empty((0, 8, 12, 3), dtype=np.uint8),
    np.zeros((32, 8, 12, 3), dtype=np.float32),
    np.zeros((32, 8, 12, 1), dtype=np.uint8),
])
def test_invalid_rgb_input_is_rejected(fake_classifier, frames):
    with pytest.raises(ValueError):
        fake_classifier.classify(frames, ["Walking", "Dancing"])
```

Also cover sequence inputs, inconsistent frame dimensions, shorter/repeated input, unchanged native frame count, duplicate/blank labels, prompt/description validation, stable ties, token limit 77/78, finite logits/scores, inference mode, and preserving integer token dtypes during transfer.

- [ ] **2. Run targeted tests to confirm failure.**

```bash
uv run --locked pytest tests/test_activity_classification.py tests/test_activity_runtime.py -q
```

Expected initial failure: missing classifier/runtime functionality. Do not claim a passing test cycle before the behavior exists.

- [ ] **3. Port candidate preparation, validation, and preprocessing.** Copy and adapt the relevant source logic. Validate `(T,H,W,3)` uint8 or consistent nonempty HWC sequences with positive dimensions, including unselected frames. Candidate descriptions must cover trimmed labels exactly. Keep original label case; prompts use the source template behavior. Use selected-frame views/references rather than advanced-index copying the full RGB clip:

```python
indices = np.linspace(0, len(frames) - 1, self.num_frames, dtype=np.int64)
selected = [frames[int(index)] for index in indices]
inputs = dict(self.processor.tokenizer(
    [candidate.prompt for candidate in candidates],
    padding=True, truncation=False, return_tensors="pt",
    return_token_type_ids=False,
))
limit = self.model.config.text_config.max_position_embeddings
if inputs["input_ids"].shape[-1] > limit:
    raise ValueError(f"A prompt exceeds the checkpoint limit of {limit} tokens")
inputs.update(self.processor.image_processor.preprocess(
    videos=selected, return_tensors="pt", input_data_format="channels_last",
))
```

Do not call the combined `XCLIPProcessor(...)` or `image_processor(videos=...)`; Transformers 4.57.6 can misroute these inputs. Check pixel shape against `(1, self.num_frames, 3, configured_size, configured_size)`. A real `VideoMAEImageProcessor` routing test needs no model weights; production always loads the checkpoint processor and its normalization settings.

- [ ] **4. Port inference, rankings, and measurement.** Preserve `eval()`, `torch.inference_mode()`, float32 logits before softmax, and finite checks. Synchronize CUDA before timing/reset and after model work/CPU copies. Return the frozen result type with stable sorted predictions. Include peak allocated/reserved MiB, or `None` on CPU. Peaks include the resident model. Clean tensors in `finally`; clear failed-forward traceback frames as in the source so retained notebook exceptions do not retain GPU intermediates. Provide actionable CUDA OOM messages; no automatic CPU retry.

- [ ] **5. Implement local runtime and explicit acquisition.** Keep these defaults entirely backend-derived:

```python
BACKEND_DIR = Path(__file__).resolve().parents[1]
HF_HOME = BACKEND_DIR / ".cache" / "huggingface"
DEFAULT_CACHE_DIR = HF_HOME / "hub"
MODEL_ID = "microsoft/xclip-base-patch16-zero-shot"
MODEL_REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"
```

Use an internal `configure_runtime(*, offline: bool, cache_dir: Path) -> None` helper to set offline and telemetry flags before lazy HF/Transformers imports. Package import must not load weights or force the downloader offline. Inference uses `local_files_only=True` explicitly for snapshot resolution, processor, and model; never fall back to sibling/global caches. Accept either a direct `model_path` directory or a hub `cache_dir`, not both; reject URI schemes and absent local paths. The direct path is documented as assets for the pinned checkpoint, not a way to relabel arbitrary checkpoints as this revision.

Check for `tokenizer.json` or both `vocab.json` and `merges.txt`. Port the actual loader options:

```python
self.processor = XCLIPProcessor.from_pretrained(
    local_dir, local_files_only=True, trust_remote_code=False,
)
self.model = XCLIPModel.from_pretrained(
    local_dir, local_files_only=True, use_safetensors=True,
    trust_remote_code=False, dtype=self.dtype, attn_implementation="eager",
).to(self.device).eval()
```

Read and validate positive integer `num_frames` from loaded config, not a hard-coded 32 assertion. Normalize an automatic CUDA choice to its actual index. The acquisition CLI sets online acquisition mode before HF imports, keeps telemetry disabled, and calls `snapshot_download` with the pinned ID/revision, explicit cache, and `allow_patterns=["*.json", "merges.txt", "model.safetensors"]`. Its import alone does not download. Missing-cache errors name the backend command, cache, and revision. Keep genuine CUDA/programming errors distinct from missing-cache errors.

- [ ] **6. Verify isolation and loader/device behavior.** Mock external loaders to assert revision, local-only options, eager/safetensors, checkpoint config use, auto CPU/CUDA, forced CPU, and unavailable CUDA. Mock downloader calls; no downloads in unit tests. Run a subprocess against an isolated copy of `activity_classification/`, with sibling imports denied, socket connections blocked, and poisoned inherited HF cache variables. Assert backend-derived cache defaults, no sibling fallback, import without model loading/HF imports, and frame classification with fake components. Cover missing tokenizer assets and CUDA forward/initialization OOM cleanup.

```bash
uv run --locked pytest tests/test_activity_classification.py tests/test_activity_runtime.py -q
```

Expected: tests pass without weights, sponsor data, or network. Return exact results and any contract discrepancy to the coordinator.

## Task 3: Add timestamp-based temporal retrieval

**Owner:** Retrieval worker. **Dependency:** Frozen temporal interface. **Parallel with:** Tasks 2 and 4 authoring.

**Files:**
- Modify: `backend/video_retrieval/contracts.py`, `retrieval.py`, `__init__.py`.
- Modify: `backend/tests/conftest.py`, `test_video_retrieval.py`.
- Create: `backend/tests/test_video_temporal_sampling.py`.

**Consumes:** Existing `DetectionInfo`, `_video_path()`, read-only storage, and PyAV.
**Produces:** `TemporalClip`, `VideoRetriever.get_temporal_clip(...)` as frozen above.

- [ ] **1. Share the existing synthetic-video fixtures mechanically.** Move `patterned_frames`, `encode_video`, `SyntheticVideo`, `video_factory`, and `video` from `tests/test_video_retrieval.py` into `tests/conftest.py`, preserving existing default behavior. Existing tests import helper functions from `conftest` only where directly used; pytest continues injecting fixtures normally. Add test-only explicit timestamp support without changing the default 24-FPS FFV1 fixtures. No production rewrite.
- [ ] **2. Add exact failing timestamp/edge tests.** These tests use the existing 48-frame 24-FPS `video` fixture:

```python
@pytest.mark.parametrize("center, expected, padding", [
    (24, (12, 18, 24, 30, 36), (0, 0)),
    (0, (0, 0, 0, 6, 12), (2, 0)),
    (36, (24, 30, 36, 42, 47), (0, 1)),
])
def test_exact_temporal_samples(video, center, expected, padding):
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(center), interval_seconds=1.0, sample_count=5,
    )
    assert result.source_frame_indices == expected
    assert (result.left_padding_count, result.right_padding_count) == padding
    assert result.unique_frame_count == len(set(expected))
    np.testing.assert_array_equal(
        result.frames, np.stack([video.frames[i] for i in expected]),
    )
```

For VFR, encode four FFV1 frames with `time_base=Fraction(1, 1000)` and PTS `(2000, 2250, 2750, 3250)`. Assert the decoded relative times are `(0, .25, .75, 1.25)`; muxers may rescale time bases. Set the reference frame to index 2 and stored source time `.75`. Request duration `2.0`, count `9` and assert indices `(0, 0, 1, 1, 2, 2, 3, 3, 3)`, targets `(-.25, 0, .25, .5, .75, 1, 1.25, 1.5, 1.75)`, reference time `.75`, and padding `(1, 2)`. Midpoint targets must select the earlier frame. Explicitly update existing synthetic Frame rows when changing their source times: the existing helper uses `INSERT OR IGNORE`.

```bash
uv run --locked pytest tests/test_video_temporal_sampling.py -q
```

Expected initial failure: missing temporal API.

- [ ] **3. Implement the additive sampler with bounded RGB memory.** Reuse record/file lookup and add one private `_decode_temporal_window` helper taking path, reference index, stored center, duration, and count. Reject boolean/non-integer/nonpositive sample counts, boolean/nonfinite/nonpositive durations, and nonfinite/negative stored centers. Use `operator.index` for integer-compatible counts. Count one selects the center while interval metadata retains both bounds.

For hackathon simplicity, make one sequential decode pass through EOF per temporal call. This establishes real boundaries, validates the reference, and checks timestamps without seeking or a dense RGB clip. Keep previous/current decoded frames and preallocated output. Build exact rational target times from validated input values and retain rational `pts * time_base` values until returning float metadata. Require PTS and positive time base; subtract the first decoded PTS and reject nonincreasing times.

```python
# Pending targets are resolved as soon as the current time brackets them.
choose_previous = target - previous_time <= current_time - target
chosen = previous_frame if choose_previous else current_frame
# Convert a chosen frame lazily; reuse its RGB conversion for repeated slots.
# Copy into the preallocated (sample_count, H, W, 3) uint8 output.
```

Assign targets at/before zero to frame zero. At EOF, validate that the reference frame was encountered before filling pending slots with the last actual frame. Empty sources and references beyond EOF raise `ValueError`. Count padding using targets strictly below zero or above the final decoded timestamp; ordinary nearest-neighbor repeats are not padding. Return decoded reference time to expose stored-time disagreement; do not silently recenter on it or on `frame_number / fps`.

- [ ] **4. Add validation/resource/error coverage.** Cover default 32 samples, count one, one-frame videos, long padded windows, NaN/infinity, invalid counts, invalid reference beyond EOF, missing records/files, timestamp-origin invariance, and stored-versus-decoded reference mismatch. Use small test-only PyAV frame/container proxies for missing/duplicate/decreasing PTS and invalid time bases; real encoders may repair invalid timestamps. Verify a single opened/closed container, decoder-error context, and no RGB conversion for unrelated frames. Preserve `ValueError` for invalid input/timestamps and wrap actual open/decode failures in contextual `RuntimeError` rather than catching all intentional validation errors.
- [ ] **5. Verify old retrieval behavior and new sampler together.**

```bash
uv run --locked pytest tests/test_video_retrieval.py tests/test_video_temporal_sampling.py -q
```

Expected: existing index/crop/edge/B-frame checks and new temporal tests pass. Return exact outcomes. EOF decoding is a deliberate simple trade-off; the notebook defaults to short sources. Do not add caching/seeking/batch methods to optimize the experiment.

## Task 4: Build the four-condition evaluation notebook

**Owner:** Notebook worker. **Dependency:** Frozen APIs; integration tests wait for Tasks 2 and 3.

**Files:**
- Create: `backend/notebooks/activity_classification.ipynb`.
- Create: `backend/tests/test_activity_notebook.py`.

**Consumes:** `XCLIPClassifier.classify(...) -> ClassificationResult`, `get_clip(...) -> np.ndarray`, `get_temporal_clip(...) -> TemporalClip`, `get_detection_info(...) -> DetectionInfo`, and `connect_database(..., read_only=True)`.
**Produces:** Executable experimental notebook with in-memory tables/figures, no database writes, and an offline synthetic execution smoke.

- [ ] **1. Create a focused notebook with tagged configuration.** Use nbformat 4 and code cells with `execution_count=None` and `outputs=[]`. Include kernel metadata for the backend Python environment. Resolve imports only from `Path.cwd()` when it contains `analysis_db/`, or its immediate parent when launched from `backend/notebooks/`; otherwise give an actionable launch error. Do not scan arbitrary ancestors or the sibling notebook project.

```python
DB_PATH = None
DETECTION_IDS = None  # Auto-select one detection in a short, available original.
ACTIVITIES = [
    "Dancing", "Rapping", "Singing", "Playing sports", "Playing games",
    "Running", "Walking", "Sitting and listening", "Drawing or painting",
]
DESCRIPTIONS = None
DEVICE = "auto"
MODEL_PATH = None
CACHE_DIR = None
REFERENCE_LABELS = {}  # detection_id -> exact label from ACTIVITIES
MAX_VIDEO_SECONDS = 120.0
TOP_K = 3
```

Use fixed conditions `(("consecutive_32", None), ("uniform_5s", 5.0), ("uniform_10s", 10.0), ("uniform_15s", 15.0))`. Candidate labels remain editable in one cell. Reference labels describe the intended activity at the detection moment, assigned manually, not inferred from filenames/model predictions.

- [ ] **2. Implement read-only discovery and preview cells.** Query joins of `FaceDetection`, `Frame`, and `Video` through `connect_database(..., read_only=True)` in `closing(...)`. Auto-selection orders by positive duration then video/detection ID, filters to duration at most `MAX_VIDEO_SECONDS`, and verifies the original path exists using existing `REPOSITORY_ROOT` path semantics. Try a small bounded candidate list, validating the selected detection with `get_clip()`; release failed/unused clips. Explicit detection IDs bypass auto-selection duration filtering. Missing data should produce an actionable message rather than creating an empty database. Show metadata and representative frames in memory; reuse the first consecutive clip instead of decoding it twice when practical.
- [ ] **3. Add a synthetic end-to-end notebook test before completing inference cells.** Use the shared synthetic `video` fixture. Read the notebook with nbformat, replace the tagged configuration in memory, and insert a cell before notebook imports that patches `activity_classification.XCLIPClassifier` with a small fake. The fake returns real `ClassificationResult`/`ActivityPrediction` objects, native count 32, and deterministic ranks, without weights or network. Execute with `nbclient.NotebookClient` and backend working directory; never write the executed document.

The execution test must assert the outputs of the workflow, not just notebook text:

```python
# Append this assertion cell to the in-memory notebook used by the test.
assert {row["condition"] for row in comparison_rows} == {
    "consecutive_32", "uniform_5s", "uniform_10s", "uniform_15s",
}
assert len(comparison_rows) == 4
assert all(row["num_frames"] == 32 for row in comparison_rows)
assert all(row["reference_label"] == "Dancing" for row in comparison_rows)
assert all(row["top1_correct"] is True for row in comparison_rows)
assert all(row["top3_correct"] is True for row in comparison_rows)
assert len(quality_summary) == 4
```

In the host test, compare Activity/Engagement row counts and synthetic database bytes before/after execution. Patch/block network in the kernel. Assert saved source notebook has no outputs/execution counts. Add a second small execution or pure cell-function check for missing references and one failed condition; summaries must use a disclosed common successful labeled detection set, not count an error as a wrong prediction or silently compare different sets.

- [ ] **4. Add explicit loading, initial prediction, and experiment cells.** Load `XCLIPClassifier` once, show model ID/revision, frame count, device/dtype, and load time. Run one unmeasured warmup using the first consecutive clip, then show an initial ranked prediction. Process each selected detection/condition one at a time with `sample_count=32`. Time retrieval with `perf_counter`; classifier results already time preprocessing/inference. Reuse the initial consecutive result in the experiment table if it has the same labels/settings.

Keep compact dictionaries in `comparison_rows`, with these fixed keys so the execution test can inspect them:

```python
row = {
    "detection_id": detection_id,
    "condition": condition,
    "num_frames": result.num_frames,
    "predictions": [asdict(prediction) for prediction in result.predictions],
    "reference_label": reference_label,
    "reference_rank": reference_rank,
    "reference_score": reference_score,
    "top1_correct": top1_correct,
    "top3_correct": top3_correct,
    "retrieval_time_seconds": retrieval_seconds,
    "preprocessing_time_seconds": result.preprocessing_time_seconds,
    "inference_time_seconds": result.inference_time_seconds,
    "source_span_seconds": source_span_seconds,
    "unique_frame_count": unique_frame_count,
    "left_padding_count": left_padding_count,
    "right_padding_count": right_padding_count,
}
```

For temporal conditions these diagnostics come from `TemporalClip`. For consecutive diagnostics, do at most one lightweight PyAV pass per selected video to collect reference/start/end PTS and actual last index (no RGB conversion or retained frames). Use clamped indices from `[f-16, f+15]` to obtain actual span, repeats, and strict boundary counts. This avoids falsely using approximate FPS/duration as exact source metadata or changing `get_clip()`.

Maintain `experiment_errors` as compact condition-specific dictionaries. On a failed retrieval/inference, record it, release clip/tensor references, and proceed without pretending it generated a prediction. Invalid reference labels should raise a clear configuration error; absent references produce `None` metrics. Avoid storing exceptions/tracebacks in records.

- [ ] **5. Display quality and timing comparisons with bounded memory.** Use IPython/Markdown and Matplotlib without adding pandas. Show a compact contact sheet per condition, top three labels/scores, and the table. Resize representative images into small in-memory previews; close Matplotlib figures and delete full-resolution arrays before the next condition. Do not leave dense clips in result lists or final notebook expressions.

Create `quality_summary` containing one dictionary per condition: `condition`, `evaluated_detections`, `top1_accuracy`, `top3_accuracy`, and excluded/failed detection information. Compute accuracy only across labeled detections with all four successful conditions; disclose the denominator and exclusions. If none are labeled, state that accuracy was not measured and show rankings only. An unknown/other text candidate is not a rejection mechanism, and larger softmax values do not establish higher quality. Include scene changes, unrelated-person/scene attribution, center-crop effects, stored/decoded timestamp disagreement, and boundary repeats in interpretation notes. Add an editable observations markdown cell.

- [ ] **6. Run notebook integration tests once APIs are available.**

```bash
uv run --locked pytest tests/test_activity_notebook.py -q
```

Expected: four-condition synthetic execution passes without weights/network; database unchanged; source notebook clean. Return exact results and any API mismatch, without rewriting another worker's files.

## Task 5: Integrate, verify local inference, and document operation

**Owner:** Coordinator. **Dependency:** Tasks 2, 3, and 4 complete.

**Files:**
- Modify: `backend/README.md`.
- Review/fix: new files and touched backend files from Tasks 1–4.
- Update progress: this plan's checkboxes and the session task list.

**Consumes:** Integrated classifier, temporal sampler, and notebook.
**Produces:** Verified backend-local proof of concept, clear launch/setup instructions, and factual experiment status.

- [ ] **1. Review integration against the frozen APIs.** Check imports/cache paths do not cross backend boundaries; check notebook/README agree on argument names and fields. Confirm the old notebooks and `get_clip()` implementation remain untouched. The current Activity schema enforces `end_frame = start_frame + 31`; this reinforces why no sampled-clip writes or schema changes belong in this work.
- [ ] **2. Write concise backend setup and usage instructions.** Replace README claims that the backend never performs inference; keep ingestion behavior descriptions accurate. Document:

```bash
uv sync --locked
uv run --locked python -m activity_classification.download_model
uv run --locked jupyter lab notebooks/activity_classification.ipynb
```

```python
from activity_classification import XCLIPClassifier
from video_retrieval import VideoRetriever

retriever = VideoRetriever()  # Or an explicit existing database path.
classifier = XCLIPClassifier(device="auto")
clip = retriever.get_clip(detection_id)
result = classifier.classify(clip, ["Dancing", "Walking", "Singing"])
for prediction in result.predictions:
    print(prediction.label, prediction.score, prediction.logit)

sampled = retriever.get_temporal_clip(detection_id, interval_seconds=10.0)
sampled_result = classifier.classify(sampled.frames, ["Dancing", "Walking", "Singing"])
```

Explain editable reference labels/quality summaries, PTS origin, nearest-frame and boundary behavior, backend cache, initial download versus offline inference, CPU selection, finite/token validation, CUDA memory errors, and sequential-decoding costs. State that direct model paths must contain the pinned assets. No measured dataset accuracy claim unless manually labeled comparisons were actually performed.

- [ ] **3. Run the integrated automated checks.**

```bash
uv lock --check
uv run --locked pytest -q
```

Expected: dependency lock consistent; full synthetic suite passes, including notebook integration and legacy regression tests. If failure occurs, diagnose before editing and rerun the affected tests; repeat the full suite only after a relevant fix.

- [ ] **4. Acquire public weights explicitly into the backend cache and run a small real smoke.** The downloader is the only model-acquisition step. Do not use the sibling cache as a runtime shortcut. Run CUDA and CPU model checks sequentially, releasing the GPU classifier before constructing another instance. Use a small synthetic RGB clip to prove CPU support; use one actual available detection and four conditions to exercise the target workflow. Record actual device/dtype, input/output shapes, finite ranked scores, and timings. Do not expand into full-dataset processing or save derived result files.

If dependencies/assets cannot be acquired, report that blocker rather than claiming real inference was validated. If a 15-second window crosses a source boundary, retain and report repeats; do not silently select a different window.

- [ ] **5. Execute the new notebook in memory, inspect comparisons, and keep saved source clear.** Run through the backend environment:

```bash
uv run --locked python -c "from pathlib import Path; import nbformat; from nbclient import NotebookClient; p=Path('notebooks/activity_classification.ipynb'); nb=nbformat.read(p, as_version=4); NotebookClient(nb, timeout=600, kernel_name='python3', resources={'metadata': {'path': str(Path.cwd())}}).execute(); print('Notebook executed in memory; saved source unchanged')"
```

Use an ephemeral local interactive kernel for visual inspection if needed; never export frames or persist executed notebooks. Verify saved state:

```bash
uv run --locked python -c "import nbformat; nb=nbformat.read('notebooks/activity_classification.ipynb', as_version=4); assert all(c.get('execution_count') is None and not c.get('outputs') for c in nb.cells if c.cell_type == 'code'); print('New notebook outputs are clear')"
git diff --check
git status --short
```

The source was never overwritten by execution, so no output-clearing operation should touch the user's existing notebooks. Check that weights, videos, database files, and identifying outputs are absent from the intended diff.

- [ ] **6. Final handoff.** Summarize changed backend paths, launch commands, tests actually run, real smoke status, and any observed quality limitations. Mark completed tasks only after verification. Do not commit, batch infer, or write Activity records.

## Plan self-review checklist

- [x] Every approved spec section maps to Tasks 1–5; independence and temporal experiments have explicit acceptance checks.
- [x] No placeholder steps, unstated cross-worker APIs, or conflicting ownership.
- [x] All classifier/result/temporal names used by the notebook match the frozen interfaces.
- [x] Backend-local code, dependencies, cache, downloader, notebook, and tests do not require the sibling project.
- [x] Fixed-candidate human-reference quality comparisons disclose failures/denominators and do not treat score magnitude as accuracy.
- [x] Parallel workers share contracts, not editable files; heavyweight environment/GPU operations are serialized.

Coverage: backend independence/setup → Tasks 1–2; frame inference, candidate scores,
device handling, and errors → Task 2; temporal sampling and boundaries → Task 3;
read-only selection, previews, four-condition comparisons, reference metrics,
and bounded notebook memory → Task 4; real offline inference, regression checks,
saved-output hygiene, and operational instructions → Task 5. Implementation
checkboxes remain unset because this deliverable is the plan, not executed code.
