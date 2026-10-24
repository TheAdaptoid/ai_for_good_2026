# Local Video Activity Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` for inline implementation, or `subagent-driven-development` if the user explicitly chooses delegated execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a local, offline-capable X-CLIP notebook that classifies video clips using 32 uniformly sampled frames and records interpretable results, latency, and GPU memory.

**Architecture:** Extend the existing `notebooks/` uv project. Keep video decoding, model ownership, prompts, inference, and metadata in one reusable Python module; keep experiment configuration and visualization in the notebook. A separate download script acquires pinned model artifacts before offline inference.

**Tech Stack:** Python 3.11–3.13, uv, CUDA-enabled PyTorch, Transformers, Hugging Face Hub, headless OpenCV, NumPy, Matplotlib, Pandas, JupyterLab, pytest, nbformat, and nbclient.

## Execution Record — 2026-10-24

Tasks 1–7 were implemented and reviewed on `feat/local-xclip-activity-recognition`
and fast-forwarded into local `main` as commit `b4e7bba` with user approval.
Final verification: **123 fast tests passed**; the **2 real-model CPU/CUDA** and
**3 notebook acceptance cases** passed separately with explicit opt-in. The
delivered notebook has no saved outputs. CUDA acceptance used a 12-second MP4,
all nine initial labels, and the native 32 frames. Weights are cached locally.
The committed notebook has default inputs and no saved outputs; the user's
subsequent executed working copy was preserved as a local change. The README
records commands, measurements, and interpretation limits. Detailed task reports are in the ignored local directory
`.superpowers/sdd/2026-10-24-activity-recognition/`.

## Global Constraints

- Source specification: `docs/superpowers/specs/2026-10-24-activity-recognition-design.md`, approved by the user on 2026-10-24.
- Project location: `notebooks/`.
- “Support Python 3.11–3.13, retain Python 3.13 as the selected development interpreter, and verify dependency resolution with `uv`.”
- “Manage every dependency and notebook command through `uv`.”
- “The user approved the notebook-plus-module design and fixed 32-frame sampling.”
- “Use the pretrained model without fine-tuning.”
- Model: `microsoft/xclip-base-patch16-zero-shot`.
- “All sponsor video processing, visualization, and inference run locally.”
- “Normal model loading uses `local_files_only=True` and offline Hugging Face settings.”
- “Use evaluation mode and `torch.inference_mode()`.”
- “Process one clip at a time.”
- “Never write extracted frames to disk by default.”
- “The scores are candidate-relative, uncalibrated similarities.”
- “Deliver the notebook with empty outputs and no execution counts.”
- “Face detection, identity recognition, engagement scoring, individual participation attribution, databases, web interfaces, training, and timeline generation are outside scope.”
- User-created `.gitignore` files exist at repository root and in `notebooks/`. Add targeted rules without replacing their contents. Preserve root `docs/superpowers/*`; the spec and plan intentionally remain ignored local files.
- Do not commit, stage, or force-add files unless the user explicitly asks. Review changes after each task instead of making automatic commits.
- Use dedicated read/search tools and `apply_patch` for file changes. Run shell commands with an explicit working directory; do not use `cd ... && ...`.

---

## File Map and Execution Conventions

| Path | Responsibility |
| --- | --- |
| `.gitignore` | General video, dataset, and derived-data exclusions, appended to the user's existing rules |
| `notebooks/.gitignore` | Python environment rules already supplied by the user, plus local model/cache/output exclusions |
| `notebooks/pyproject.toml` | Runtime dependencies, development dependencies, explicit PyTorch index, pytest configuration |
| `notebooks/uv.lock` | Resolved dependency versions |
| `notebooks/.python-version` | Existing Python 3.13 selection |
| `notebooks/activity_recognition.py` | Local runtime policy, frame sampling, candidates, recognizer, timings, metadata, public convenience function |
| `notebooks/download_model.py` | Explicit network-enabled model acquisition, isolated from offline inference |
| `notebooks/activity_recognition.ipynb` | Editable experiments, local previews, charts, comparisons, batch results, optional exports |
| `notebooks/README.md` | Setup, download, offline notebook use, measurements, data handling, verification |
| `notebooks/tests/conftest.py` | Small synthetic-video fixture |
| `notebooks/tests/test_video_sampling.py` | Decode, RGB, sampling, fallback, and local-input contracts |
| `notebooks/tests/test_runtime.py` | Offline loading, precision/device selection, import behavior, and missing-cache errors |
| `notebooks/tests/test_classification.py` | Candidate validation, inference plumbing, finite metadata, timing boundaries, and errors |
| `notebooks/tests/test_model_smoke.py` | Explicitly enabled real-checkpoint CPU/CUDA checks, including denied network connections |
| `notebooks/tests/test_notebook_smoke.py` | Opt-in, in-memory synthetic notebook and export acceptance |

Unless stated otherwise, run commands from `notebooks/`. Commands that check repository ignore rules run from the repository root. Do not download weights or install packages merely to finish writing this plan; those are implementation steps below.

Use red/green tests for substantive sampling and inference behavior. Check reversible configuration, notebook formatting, and documentation with direct commands rather than tests that copy their contents. Normal tests must not download model weights or use sponsor videos.

### Shared Interfaces

Define these in `activity_recognition.py`; subsequent tasks use the same names:

```python
MODEL_ID = "microsoft/xclip-base-patch16-zero-shot"
MODEL_REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"
NUM_FRAMES = 32
DEFAULT_PROMPT_TEMPLATE = "A video of people {activity}."
PROJECT_DIR = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_DIR / ".cache" / "huggingface" / "hub"

@dataclass
class SampledVideo:
    frames: list[np.ndarray]  # RGB uint8, original oriented dimensions
    indices: list[int]
    fps: float
    frame_count: int
    width: int
    height: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps

@dataclass(frozen=True)
class Candidate:
    key: str
    label: str
    prompt: str

# All public functions below have complete signatures in their owning tasks.
```

The pinned revision was checked against Hugging Face's model API while planning. It contains `model.safetensors`, configuration, and tokenizer/processor assets. Record this revision in results; do not download the duplicate `pytorch_model.bin`.

## Task 1: Reproducible CUDA Environment and Data Exclusions

**Files:** Modify `notebooks/pyproject.toml`, `notebooks/README.md`, `.gitignore`, and `notebooks/.gitignore`; generate `notebooks/uv.lock`. Retain `notebooks/.python-version` at `3.13`.

**Interfaces:** Produces a reproducible `uv sync --locked` environment and a working CUDA tensor operation on the GTX 1650. No application API yet.

- [ ] **Step 1: Review current files and hardware.** Read both user-created ignore files, the project manifest, and interpreter selection. Run `git status --short --untracked-files=all` from the root and `nvidia-smi` from `notebooks/`. Inspect any new user changes before editing.

- [ ] **Step 2: Declare the initial CUDA-enabled baseline in the existing manifest.** Keep the project name/version and set a useful description. Use this dependency configuration, then let `uv.lock` record exact transitive versions:

```toml
[project]
name = "notebooks"
version = "0.1.0"
description = "Local zero-shot video activity recognition experiments with X-CLIP"
readme = "README.md"
requires-python = ">=3.11,<3.14"
dependencies = [
  "torch==2.8.0",
  "transformers==4.57.6",
  "huggingface-hub>=0.34,<1",
  "safetensors>=0.4.3,<1",
  "opencv-python-headless>=4.11,<5",
  "numpy>=2,<3",
  "matplotlib>=3.10,<4",
  "pandas>=2.2,<3",
  "jupyterlab>=4.4,<5",
  "ipykernel>=6.29,<8",
]

[dependency-groups]
dev = ["pytest>=8,<10", "nbformat>=5.10,<6", "nbclient>=0.10,<1"]

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cu128" }

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
markers = ["model_smoke: explicit local-cache checks using real X-CLIP weights"]
```

The CUDA 12.8 baseline avoids inferring a PyTorch wheel version from the driver's displayed CUDA 13.2. Verify this choice on the actual GPU; if dependency resolution or GPU architecture support fails, select another stable CUDA-enabled build with Python 3.13 and GTX 1650 support and record the observed reason in the README.

- [ ] **Step 3: Append focused ignore rules.** Add this general block to the root file after the existing planning-document rule:

```gitignore
# Local sponsor data and generated artifacts
data/
datasets/
sponsor_videos/
videos/
outputs/
results/
*.mp4
*.MP4
*.mov
*.MOV
*.avi
*.AVI
*.mkv
*.MKV
*.webm
*.WEBM
*.m4v
*.M4V
*.mpeg
*.mpg
```

Append this notebook-specific block to `notebooks/.gitignore`:

```gitignore
# Local X-CLIP models, runtime state, and notebook exports
.cache/
models/
checkpoints/
*.safetensors
*.pt
*.pth
pytorch_model*.bin
tmp/
activity_recognition.html
activity_recognition_files/
```

Use `results/` or `outputs/` for all derived-data exports. Keep `uv.lock` and `.python-version` eligible for version control.

- [ ] **Step 4: Resolve and sync through uv.** Run `uv lock`, then `uv sync --locked`. Expected: a Python 3.13 environment, CUDA-enabled torch, and a resolved lock covering the declared Python range. Add those setup commands to the README immediately so this task is independently reproducible.

- [ ] **Step 5: Verify actual CUDA execution.** Run:

```bash
uv run --locked python -c 'import torch; print("torch:", torch.__version__); print("runtime CUDA:", torch.version.cuda); print("CUDA available:", torch.cuda.is_available()); assert torch.version.cuda is not None; assert torch.cuda.is_available(); print("GPU:", torch.cuda.get_device_name(0)); print("architectures:", torch.cuda.get_arch_list()); print("free/total bytes:", torch.cuda.mem_get_info()); x = torch.ones((8, 8), device="cuda"); y = x @ x; torch.cuda.synchronize(); assert y.sum().item() == 512.0; print("CUDA operation passed")'
```

Expected: GTX 1650, a non-null runtime CUDA version, and `CUDA operation passed`. Record actual output rather than claiming model inference has already passed.

- [ ] **Step 6: Check ignore coverage and review the task.** From the root run:

```bash
git check-ignore -v data/example.mp4 notebooks/videos/example.MOV notebooks/.cache/huggingface/hub/model.safetensors notebooks/results/run.json notebooks/.venv/pyvenv.cfg notebooks/.ipynb_checkpoints/example.ipynb notebooks/activity_recognition.html
```

All listed paths must be ignored. `git check-ignore notebooks/uv.lock notebooks/activity_recognition.ipynb` must produce no matching paths (exit 1 is expected). Run `git diff --check` and inspect intended manifest/ignore changes.

## Task 2: Bounded-Memory Local Video Sampling

**Files:** Create `notebooks/activity_recognition.py`, `notebooks/tests/conftest.py`, and `notebooks/tests/test_video_sampling.py`.

**Interfaces:** Consumes OpenCV and NumPy from Task 1. Produces `SampledVideo` and `sample_video(video_path: str | Path, *, num_frames: int = NUM_FRAMES) -> SampledVideo`.

- [ ] **Step 1: Add a synthetic-video fixture and failing sampling tests.** Use pytest `tmp_path`, OpenCV `VideoWriter` with MJPG/AVI, 30 FPS, and dimensions `(96, 64)` and `(64, 96)`. Release the writer in `finally`; assert it opened. A solid red BGR frame `(0, 0, 255)` gives an independently checkable RGB result despite lossy encoding. Expose a fixture `make_video(*, frames=60, size=(96, 64)) -> Path` that creates unique temporary files. Include:

```python
def test_samples_full_clip_and_converts_to_rgb(make_video):
    sampled = sample_video(str(make_video()))
    assert len(sampled.frames) == 32
    assert sampled.indices == np.linspace(0, 59, 32, dtype=np.int64).tolist()
    assert sampled.duration_seconds == pytest.approx(2.0)
    assert sampled.frames[0].shape == (64, 96, 3)
    assert sampled.frames[0][20, 20, 0] > 240
    assert sampled.frames[0][20, 20, 2] < 15

def test_repeats_indices_for_short_video(make_video):
    sampled = sample_video(str(make_video(frames=3)))
    assert len(sampled.frames) == 32
    assert len(set(sampled.indices)) == 3
    assert sampled.indices[0] == 0
    assert sampled.indices[-1] == 2

def test_preserves_portrait_dimensions(make_video):
    sampled = sample_video(str(make_video(size=(64, 96))))
    assert sampled.frames[0].shape == (96, 64, 3)
```

Add rejection cases for URLs, missing files, non-video files, nonpositive or noninteger sample counts, zero/NaN FPS, and an empty decoded stream. Mock the capture only for metadata/seek failures that synthetic files cannot reliably reproduce. Verify release on failure.

- [ ] **Step 2: Run the tests before implementation.** Run `uv run --locked pytest tests/test_video_sampling.py -q`. Expected initially: missing module or missing `sample_video`, not missing dependencies.

- [ ] **Step 3: Implement sampling and metadata.** Add constants and `SampledVideo` from the shared interface. Resolve and validate local regular files before constructing `cv2.VideoCapture`; explicitly reject strings containing URI schemes. Require finite positive FPS. Derive indices using:

```python
indices = np.linspace(0, frame_count - 1, num_frames, dtype=np.int64)
# Decode each unique index once, then reconstruct frames in indices order.
rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
```

Enable `CAP_PROP_ORIENTATION_AUTO` where the backend exposes it. Read actual frame dimensions after orientation, not only metadata. Use `try/finally` for each capture. Attempt indexed reads when count metadata is valid; if requested reads fail or metadata is absent, reopen for a counting scan and a second sequential scan that retains only requested unique RGB frames. If a stream changes between passes or still cannot provide the requested frames, raise a descriptive `ValueError` with its original cause. Do not fall back to retaining the whole video in RAM.

- [ ] **Step 4: Exercise sequential fallback explicitly.** Wrap a real capture in a test double that reports an unknown frame count or rejects seeking, delegating sequential reads to the real capture. Assert the same indices, duration, RGB conversion, and frame shapes as the normal path. A fake invalid-FPS capture must be released even when sampling raises.

- [ ] **Step 5: Verify and review.** Run `uv run --locked pytest tests/test_video_sampling.py -q`. Expected: all sampling tests pass, no persistent videos or extracted-frame files. Inspect the module for URL rejection, capture cleanup, and bounded retained frames before continuing.

## Task 3: Explicit Model Download and Offline Recognizer Initialization

**Files:** Modify `notebooks/activity_recognition.py`; create `notebooks/download_model.py` and `notebooks/tests/test_runtime.py`; extend `notebooks/README.md`.

**Interfaces:** Produces `configure_local_runtime() -> None`, `device_info() -> dict`, `XCLIPRecognizer(device: str = "auto")`, and `get_recognizer(device: str = "auto") -> XCLIPRecognizer`. The recognizer exposes `model`, `processor`, `device`, `dtype`, `model_revision`, and `load_time_seconds`.

- [ ] **Step 1: Add failing runtime-contract tests.** Test that importing the module does not invoke `from_pretrained`, download assets, or open videos. Monkeypatch the model and processor factories to capture keyword arguments; check offline/local loading, evaluation mode, CUDA FP16 versus CPU FP32, and a clear missing-cache error. Mock CUDA availability when testing device selection without requiring hardware. Explicit `device="cuda"` must raise when CUDA is unavailable; `device="auto"` must choose CPU. Test a checkpoint configuration with `vision_config.num_frames != 32` is rejected. Run `uv run --locked pytest tests/test_runtime.py -q` and confirm the expected missing-API failures.

For the missing-cache contract, use a real Hub exception and assert the user-facing action:

```python
def test_missing_cache_explains_explicit_download(monkeypatch):
    from huggingface_hub.errors import LocalEntryNotFoundError

    def missing_snapshot(*args, **kwargs):
        assert kwargs["local_files_only"] is True
        raise LocalEntryNotFoundError("No cached model snapshot")

    monkeypatch.setattr("huggingface_hub.snapshot_download", missing_snapshot)
    with pytest.raises(RuntimeError, match="download_model.py"):
        XCLIPRecognizer(device="cpu")
```

- [ ] **Step 2: Configure inference privacy before ML imports.** Call `configure_local_runtime()` at module import, before importing Transformers or Hugging Face Hub. Set, rather than merely default, these flags:

```python
flags = {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "WANDB_DISABLED": "true",
    "WANDB_MODE": "disabled",
    "COMET_MODE": "DISABLED",
    "TOKENIZERS_PARALLELISM": "false",
}
os.environ.update(flags)
os.environ["HF_HOME"] = str(PROJECT_DIR / ".cache" / "huggingface")
```

Setting environment flags may happen on import; creating a model, cache download, directory, or video capture may not. Keep optional Transformers/model imports inside the initialization path if needed to make import behavior easy to inspect.

- [ ] **Step 3: Implement the separate downloader.** `download_model.py` uses only stdlib imports until it sets telemetry-disabled flags and explicitly sets both offline flags to `0`. It must not import `activity_recognition`, which would enforce offline mode. Use the same model ID, revision, and resolved project-local cache path, and acquire only:

```python
snapshot_download(
    repo_id="microsoft/xclip-base-patch16-zero-shot",
    revision="6746d6a5202bf24300cd9bf36f457f174483d41b",
    cache_dir=Path(__file__).resolve().parent / ".cache" / "huggingface" / "hub",
    allow_patterns=["*.json", "merges.txt", "model.safetensors"],
)
```

Give it a main guard. Print the resolved snapshot directory and revision after success. Downloading must happen only when the user runs `uv run --locked python download_model.py`, never during module import or ordinary inference.

- [ ] **Step 4: Implement local loading, device ownership, and diagnostics.** Resolve the pinned snapshot using `snapshot_download(..., local_files_only=True)`; initialize `XCLIPProcessor` and `XCLIPModel` from that local directory with `local_files_only=True`, `trust_remote_code=False`, and `use_safetensors=True` for the model. Select `torch.float16` on CUDA and `torch.float32` on CPU, use the supported `torch_dtype` argument for the pinned Transformers release, move the model to the selected device, and call `.eval()`. Confirm the native frame count is 32. Return native Python diagnostics, including GPU total/free MiB when available and null values on CPU. Measure model initialization independently, synchronizing CUDA before completing the load measurement.

Cache the convenience recognizer with `functools.lru_cache(maxsize=1)`. Do not build separate models for each clip. Wrap missing-cache failures with the explicit download command and preserve the cause. Do not retry model downloads or silently replace a requested CUDA device with CPU.

- [ ] **Step 5: Verify local contracts and document acquisition.** Run `uv run --locked pytest tests/test_runtime.py tests/test_video_sampling.py -q`. Expected: both pass without downloading weights. Add the explicit download command, local cache location, and offline loading description to the README. Real model download and inference are reserved for Task 7.

## Task 4: Prompted Classification, Timings, and JSON-Compatible Metadata

**Files:** Modify `notebooks/activity_recognition.py`; create `notebooks/tests/test_classification.py`.

**Interfaces:** Consumes `SampledVideo`, `sample_video`, the recognizer state, and the pinned model. Produces:

```python
def prepare_candidates(
    activities: list[str],
    *,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    descriptions: Mapping[str, str] | None = None,
) -> list[Candidate]: ...

# Add this instance method to XCLIPRecognizer:
def classify(
    self,
    video_path: str,
    activities: list[str],
    *,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    descriptions: Mapping[str, str] | None = None,
    video_id: str | None = None,
) -> dict: ...

def classify_activity(
    video_path: str,
    activities: list[str],
    *,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    descriptions: Mapping[str, str] | None = None,
    video_id: str | None = None,
    device: str = "auto",
) -> dict: ...
```

Ellipses above describe interfaces, not implementation stubs to leave in the module. `descriptions` maps original label strings to complete prompt strings; when supplied it must cover exactly the candidate labels.

- [ ] **Step 1: Add independent classification tests and confirm red.** Build a small fake processor/model using real CPU torch tensors. The fake processor returns 32-frame pixel values and integer token tensors; the fake model returns known `logits_per_video`, for example `[2.0, 1.0]`. Instantiate the recognizer without invoking real weight loading by injecting its state in a fixture. Include:

```python
def test_candidates_keep_keys_across_prompt_strategies():
    labels = ["Dancing", "Playing games"]
    short = prepare_candidates(labels, prompt_template="{activity}")
    detailed = prepare_candidates(labels, descriptions={
        "Dancing": "A group of teenagers dancing to music.",
        "Playing games": "A group of people playing board games.",
    })
    assert [c.key for c in short] == ["dancing", "playing_games"]
    assert [c.key for c in detailed] == [c.key for c in short]
    assert detailed[0].prompt == "A group of teenagers dancing to music."

def test_classification_is_candidate_relative_and_json_safe(fake_recognizer, make_video):
    result = fake_recognizer.classify(
        str(make_video()), ["Dancing", "Singing"], video_id="synthetic_001"
    )
    expected = torch.tensor([2.0, 1.0]).softmax(dim=-1).tolist()
    assert result["activity"] == "dancing"
    assert result["scores"]["dancing"] == pytest.approx(expected[0])
    assert sum(result["scores"].values()) == pytest.approx(1.0)
    assert result["num_frames"] == 32
    assert result["peak_gpu_memory_allocated_mib"] is None
    assert result["total_time_seconds"] >= result["inference_time_seconds"] >= 0
    json.dumps(result, allow_nan=False)
```

Add cases for empty/non-string/duplicate labels, slug collisions (`Playing games` versus `Playing-games`), empty prompts, missing descriptions, bad template fields, prompts longer than the model's token limit, unexpected video tensor temporal shape, nonfinite model logits, and a simulated CUDA out-of-memory error. Run `uv run --locked pytest tests/test_classification.py -q`; expected initially: missing functions/methods.

- [ ] **Step 2: Implement candidate validation and processor inputs.** Strip labels, reject duplicates ignoring case, and create keys with lowercase ASCII alphanumeric runs joined by underscores; reject empty keys and collisions. Format default activities in lowercase while preserving original labels. For `prompt_template="{activity}"`, preserve the label text so this is a genuine raw-label comparison. Validate descriptions contain nonempty strings and cover the candidates exactly. Use `processor.tokenizer(..., truncation=False)` to check every sequence against `model.config.text_config.max_position_embeddings` before the processor builds the padded batch. Raise rather than truncate.

Call `sample_video(video_path, num_frames=NUM_FRAMES)` and then:

```python
inputs = self.processor(
    text=[candidate.prompt for candidate in candidates],
    videos=sampled.frames,
    return_tensors="pt",
    padding=True,
    truncation=False,
)
if inputs["pixel_values"].shape[1] != NUM_FRAMES:
    raise ValueError("X-CLIP requires exactly 32 sampled frames")
```

The checkpoint processor owns spatial resize/crop/normalization. Do not add a custom square stretch.

- [ ] **Step 3: Implement measured inference.** Initialize/cache the model before starting a classification measurement. Synchronize CUDA, reset peak-memory statistics, and record the call's monotonic start before validation/sampling. Record preprocessing completion before transfers. Only floating tensors are cast:

```python
device_inputs = {
    key: value.to(device=self.device, dtype=self.dtype)
    if value.is_floating_point() else value.to(device=self.device)
    for key, value in inputs.items()
}
with torch.inference_mode():
    logits = self.model(**device_inputs).logits_per_video[0].float()
    if not torch.isfinite(logits).all():
        raise ValueError("X-CLIP returned nonfinite similarity logits")
    relative_scores = logits.softmax(dim=-1)
    logits_cpu = logits.cpu().tolist()
    scores_cpu = relative_scores.cpu().tolist()
# Synchronize CUDA before recording inference completion and reading peaks.
```

Keep transfer, forward, normalization, and score copy inside inference timing. Build plain-Python metadata, then stamp total time just before returning. Read peak allocated/reserved bytes and divide by `1024 ** 2`; CPU fields are null. Include the resident model in GPU peak interpretation. Release per-call tensors, especially on exceptions. Catch CUDA allocation failures separately, clean up transient references, and raise an error that suggests explicit CPU execution; never silently rerun on CPU.

- [ ] **Step 4: Return the complete schema and convenience API.** Populate every field from specification section 7: IDs/clip bounds, model/revision, winning activity, scores/logits/labels/prompts, `score_type="candidate_relative_softmax"`, frame count/unique count/indices, `sampling_method="uniform_frame_indices"`, device/dtype, all three timings, and both GPU memory fields. Use `clip_start=0.0` and `clip_end=sampled.duration_seconds`; do not infer offsets in an original longer video. Exclude absolute input paths, frames, and embeddings. `classify_activity` delegates to `get_recognizer(device).classify(...)`. Verify a second convenience call reuses the same recognizer.

- [ ] **Step 5: Verify failure and measurement contracts.** Use fake CUDA synchronization/peak functions to assert ordering without requiring real GPU work. Ensure token tensors remain integer, labels/prompts remain traceable, nonfinite logits cannot reach JSON export, and a CUDA allocation error never triggers a CPU call. Run `uv run --locked pytest -m 'not model_smoke' -q`. Inspect that no test downloads weights.

## Task 5: Notebook Experiments, Visualization, and Optional Local Export

**Files:** Create `notebooks/activity_recognition.ipynb`; extend `notebooks/README.md`.

**Interfaces:** Consumes `NUM_FRAMES`, `SampledVideo`, `device_info`, `get_recognizer`, `sample_video`, `prepare_candidates`, and the recognizer's `.classify()` method. Produces an executable notebook with these in-notebook helpers:

```python
def show_sampled_frames(sampled: SampledVideo, *, max_frames: int = 8): ...
def show_result(result: dict): ...
def run_experiments(
    video_paths: list[str], experiments: list[dict], *, repeats: int = 1
) -> tuple[list[dict], pd.DataFrame, pd.DataFrame]: ...
```

These are notebook-local helper interfaces, not additional production abstractions. `run_experiments` returns successful JSON-compatible records, a flattened successful-run DataFrame, and a separate failure DataFrame.

- [ ] **Step 1: Author a valid unexecuted notebook in the spec's nine-section order.** Include Python kernel metadata. Import the local module before other Hugging Face/Transformers imports so offline/telemetry settings apply. Use editable empty defaults:

```python
VIDEO_PATHS: list[str] = []
REFERENCE_LABELS: dict[str, str] = {}  # video_id -> canonical activity key
ACTIVITIES = [
    "Dancing", "Singing", "Playing sports", "Playing games", "Running",
    "Walking", "Sitting and listening", "Drawing or painting", "Other activities",
]
DEVICE = "auto"
REPEATS = 3
EXPORT_RESULTS = False
OUTPUT_DIR = Path("results")
```

Tag that cell `input-configuration` in its metadata, and place it before any model-dependent work. Display diagnostics unconditionally. If the video list is empty, model-load, preview, and experiment cells print an instruction to set `VIDEO_PATHS` and skip work. Show the download command in Markdown; do not execute it automatically. When configured, load one recognizer and display its `load_time_seconds` separately.

- [ ] **Step 2: Add frame and result visualization.** `show_sampled_frames` uses up to eight evenly spaced positions in the 32-frame sample and titles each tile with source frame index and approximate timestamp. `show_result` sorts `result["scores"]`, labels bars with original candidate labels, uses `barh`, and labels the axis `Relative candidate score (not calibrated confidence)`. Display predicted activity, all three timings, actual device/dtype, and both memory fields; CPU memory is displayed as not applicable. Use no file-saving calls.

- [ ] **Step 3: Add concrete prompt and candidate experiments.** Define descriptive text for every initial category and supply at least these experiment dictionaries:

```python
EXPERIMENTS = [
    {"name": "short_labels", "activities": ACTIVITIES,
     "prompt_template": "{activity}", "descriptions": None},
    {"name": "descriptive", "activities": ACTIVITIES,
     "prompt_template": "A video of people {activity}.",
     "descriptions": DESCRIPTIONS},
    {"name": "similar_motion_candidates",
     "activities": ["Dancing", "Running", "Walking", "Playing sports"],
     "prompt_template": "A video of people {activity}.", "descriptions": None},
]
```

Define `DESCRIPTIONS` before `EXPERIMENTS` in a cell tagged `experiment-configuration`:

```python
DESCRIPTIONS = {
    "Dancing": "A group of teenagers dancing to music.",
    "Singing": "People singing together in a group.",
    "Playing sports": "People actively playing a sport together.",
    "Playing games": "People playing a board game or a group game.",
    "Running": "People running across an area.",
    "Walking": "People walking through an area.",
    "Sitting and listening": "People sitting and listening to someone speaking.",
    "Drawing or painting": "People drawing pictures or painting artwork.",
    "Other activities": "People doing an activity other than the listed activities.",
}
```

Keep all experiments at 32 frames. Explain ordinary `Other activities`, changes in softmax normalization, center-crop edge loss, approximate timing for variable-frame-rate sources, and the inability to infer independent multi-label probabilities from this classifier.

- [ ] **Step 4: Implement warmed batch comparisons and failure rows.** For each video/experiment pair, run one labeled untimed warm-up before measured repetitions. Classify sequentially with the existing recognizer. Catch expected input/runtime exceptions per pair, record `video_id`, experiment name, exception type/message, and continue; do not hide arbitrary programming errors with a blanket bare exception. Add experiment name, prompt strategy, candidate keys, and repeat index to each successful record. Flatten scores using `pd.json_normalize(records, sep=".")`, keep a separate error DataFrame, and summarize median/range latency and peak memory by experiment. If `REFERENCE_LABELS` contains a clip, compute exact top-label match against its canonical key and report the number of manually labeled clips represented; do not invent accuracy for unlabeled clips.

- [ ] **Step 5: Add guarded exports.** Tag this cell `result-export`. The export cell is the only ordinary notebook code that creates output directories or result files:

```python
if EXPORT_RESULTS and records:
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "activity_results.json").write_text(
        json.dumps(records, indent=2, allow_nan=False), encoding="utf-8"
    )
    results_df.to_csv(output_dir / "activity_results.csv", index=False)
    if not errors_df.empty:
        errors_df.to_csv(output_dir / "activity_errors.csv", index=False)
```

Document that previews/results can persist inside saved notebook outputs. Include an output-clearing command in the README:

```bash
uv run --locked jupyter nbconvert --ClearOutputPreprocessor.enabled=True --inplace activity_recognition.ipynb
```

- [ ] **Step 6: Validate and execute the data-independent notebook.** Run this read-only-file validation and in-memory execution; it must not create a saved executed notebook or require a model download:

```bash
uv run --locked python -c 'import nbformat; from nbclient import NotebookClient; nb = nbformat.read("activity_recognition.ipynb", as_version=4); nbformat.validate(nb); assert all(c.get("outputs", []) == [] and c.get("execution_count") is None for c in nb.cells if c.cell_type == "code"); NotebookClient(nb, timeout=120, kernel_name="python3").execute(); print("Empty-input notebook execution passed")'
```

Expected: diagnostics and configuration messages, no missing-file/cache failures, no model download, and no output files. Validate that the saved notebook still has empty outputs because execution occurred only in memory.

## Task 6: User-Facing Setup and Interpretation Instructions

**Files:** Complete `notebooks/README.md`.

**Interfaces:** Consumes all implemented commands/APIs. Produces instructions a user can follow from the existing repository without guessing interpreter, working directory, cache behavior, or export paths.

- [ ] **Step 1: Document the exact reproducible workflow.** State that all commands below are run from `notebooks/`, then provide:

```bash
uv sync --locked
uv run --locked python download_model.py
uv run --locked jupyter lab activity_recognition.ipynb
```

Explain that initial dependency/model acquisition requires internet, while already-installed dependencies and cached-model inference do not. Show the convenience call and explicit CPU call with a synthetic path:

```python
from activity_recognition import classify_activity

result = classify_activity("videos/local_clip.mp4", ["Dancing", "Walking"])
cpu_result = classify_activity(
    "videos/local_clip.mp4", ["Dancing", "Walking"], device="cpu"
)
```

- [ ] **Step 2: Explain diagnostics, measurements, and errors.** Include driver-versus-runtime CUDA distinction, the actual tested PyTorch/runtime versions once known, one-clip-at-a-time FP16 GPU/FP32 CPU policy, warm-up, and the exact timing/memory definitions from the spec. Describe missing-cache, unsupported-codec, invalid-prompt, CUDA-unavailable, and out-of-memory messages with the corresponding user action. Do not claim model inference fits or passes until Task 7 provides evidence.

- [ ] **Step 3: Document data handling and experiments.** Cover local video paths, fixed 32-frame coverage, portrait center-crop limitations, candidate-dependent softmax, multi-activity interpretation, reference-label entry, explicit exports under `results/`, and clearing notebook outputs. State that accuracy must be measured on manually labeled clips. Describe both ignore files and why ignored planning documents do not appear in normal Git status.

- [ ] **Step 4: Verify instructions against implemented names and commands.** Check that the README uses `XCLIPRecognizer`, `classify_activity`, the correct filenames, and `uv` consistently. Run `uv run --locked python -c 'from activity_recognition import classify_activity, get_recognizer, device_info; print(device_info())'`, `uv run --locked pytest -m 'not model_smoke' -q`, and `git diff --check`. No new documentation-only test suite is needed.

## Task 7: Real-Checkpoint CUDA, CPU, Offline, and Notebook Acceptance

**Files:** Create `notebooks/tests/test_model_smoke.py` and `notebooks/tests/test_notebook_smoke.py`; update `notebooks/README.md` with observed verification results. Change application code only if a check finds a specific defect, adding a focused regression check when warranted.

**Interfaces:** Consumes the downloader, recognizer, synthetic-video fixture, and complete notebook. Produces evidence for the spec's success criteria; these tests evaluate functionality, not accuracy.

- [ ] **Step 1: Add opt-in model smoke checks before downloading.** Mark the file `model_smoke` and skip unless `RUN_XCLIP_SMOKE=1`. Ordinary `pytest` must not load weights. Parameterize explicit `cpu` and `cuda`; mark CUDA as skipped if absent, and never count that skip as verified GPU success. Use the synthetic-video fixture and actual `XCLIPRecognizer`. Deny network connections during initialization and inference by monkeypatching Python socket connection functions to raise `AssertionError`; keep Hugging Face offline settings and local-only loading enabled. Include:

```python
result = recognizer.classify(
    str(make_video(frames=60)), ["Dancing", "Walking"], video_id="synthetic_smoke"
)
assert result["device"].startswith(device)
assert result["num_frames"] == 32
assert result["model_revision"] == MODEL_REVISION
assert result["activity"] == max(result["scores"], key=result["scores"].get)
assert sum(result["scores"].values()) == pytest.approx(1.0)
assert result["total_time_seconds"] >= result["inference_time_seconds"] > 0
json.dumps(result, allow_nan=False)
if device == "cuda":
    assert result["peak_gpu_memory_allocated_mib"] > 0
    assert result["peak_gpu_memory_reserved_mib"] >= result["peak_gpu_memory_allocated_mib"]
else:
    assert result["peak_gpu_memory_allocated_mib"] is None
```

Release each recognizer after its test so the CPU and GPU checks do not leave duplicate live models. Record prediction consistency across repeats without asserting a specific action for a solid-color synthetic video.

- [ ] **Step 2: Perform the explicit acquisition.** Run `uv run --locked python download_model.py`. Expected: the pinned snapshot and safetensors weights in the ignored cache. Do not download or use sponsor videos for verification. Retry only if there is a concrete transient download failure, recording any actual blocker.

- [ ] **Step 3: Verify in a fresh offline process.** Run:

```bash
RUN_XCLIP_SMOKE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --offline pytest tests/test_model_smoke.py -q
```

Expected: real CPU and CUDA checks pass on this machine, no network calls are attempted, scores are finite, timings are positive, and memory fields follow the schema. If GPU memory or precision fails, investigate that specific failure, retain native 32 frames, and rerun affected checks after a supported precision or memory-lifetime correction. Do not substitute CPU success for CUDA acceptance.

- [ ] **Step 4: Run the configured notebook with synthetic data in memory.** In `test_notebook_smoke.py`, use the same `model_smoke` marker and `RUN_XCLIP_SMOKE` guard as the model tests. Parameterize the test with `export_results=False` and `export_results=True`. Use `tmp_path` and `make_video` for a 60-frame synthetic AVI; the export-enabled case also tests a missing-file second clip. Append overrides to the tagged configuration cells rather than editing the saved notebook or matching arbitrary source text:

```python
nb = nbformat.read("activity_recognition.ipynb", as_version=4)
video_paths = [str(make_video(frames=60))]
if export_results:
    video_paths.append(str(tmp_path / "missing.avi"))
export_dir = tmp_path / "results"
input_cell = next(c for c in nb.cells if "input-configuration" in c.metadata.get("tags", []))
input_cell.source += (
    f"\nVIDEO_PATHS = {video_paths!r}\n"
    "ACTIVITIES = ['Dancing', 'Walking']\nREPEATS = 1\n"
    f"EXPORT_RESULTS = {export_results!r}\n"
    f"OUTPUT_DIR = Path({str(export_dir)!r})\n"
)
experiment_cell = next(
    c for c in nb.cells if "experiment-configuration" in c.metadata.get("tags", [])
)
experiment_cell.source += (
    "\nEXPERIMENTS = [{'name': 'smoke', 'activities': ACTIVITIES, "
    "'prompt_template': '{activity}', 'descriptions': None}]\n"
)
nb.cells.append(nbformat.v4.new_code_cell(
    "assert len(records) == 1\n"
    "assert len(results_df) == 1\n"
    f"assert len(errors_df) == {int(export_results)}\n"
    "assert records[0]['num_frames'] == 32\n"
))
executed = NotebookClient(nb, timeout=600, kernel_name="python3").execute()
assert any(
    "image/png" in output.get("data", {})
    for cell in executed.cells if cell.cell_type == "code"
    for output in cell.get("outputs", [])
)
```

Expected: sampled-frame figure, score chart, predicted label, timing/memory summaries, and a successful DataFrame row. Notebook execution must use the uv environment's interpreter; if an existing user kernelspec shadows it, supply an in-memory kernelspec using that environment's `sys.executable` instead of installing a global kernel. Do not deny kernel communication sockets: the socket-denial check belongs only to the direct model tests. Never save this executed notebook.

- [ ] **Step 5: Verify optional exports and batch failures.** In the same parameterized test, the export-disabled case asserts that `export_dir` does not exist. In the export-enabled case, check results from the parent pytest process after in-memory notebook execution:

```python
exported = json.loads((export_dir / "activity_results.json").read_text())
assert len(exported) == 1
assert exported[0]["num_frames"] == 32
table = pd.read_csv(export_dir / "activity_results.csv")
assert len(table) == 1
assert table.iloc[0]["activity"] == exported[0]["activity"]
assert table.iloc[0]["inference_time_seconds"] == pytest.approx(
    exported[0]["inference_time_seconds"]
)
errors = pd.read_csv(export_dir / "activity_errors.csv")
assert len(errors) == 1
assert errors.iloc[0]["video_id"] == "missing"
```

The missing-file second clip must not prevent the first clip from succeeding. No raw failed row belongs in `activity_results.json`. pytest cleans temporary inputs and exports. Run `RUN_XCLIP_SMOKE=1 uv run --locked --offline pytest tests/test_notebook_smoke.py -q` after the direct model smoke checks pass.

- [ ] **Step 6: Run the final bounded check set and record evidence.** Run `uv lock --check`, the full non-model pytest suite, the unexecuted-notebook validation from Task 5, representative `git check-ignore` checks from Task 1, and `git diff --check`. Inspect `git status --short --untracked-files=all` for accidental videos, cached weights, or exported metadata. Confirm the delivered notebook remains unexecuted. Document actual tested GPU/runtime/precision, the real-model checks performed, and any blocked acceptance item in the README and final handoff.

## Spec Coverage and Review Checklist

These checks concern plan coverage, not completed implementation or passing runtime tests.

- [x] Spec sections 1–2: Task 1 covers the Python/CUDA environment; Tasks 2 and 4 retain native 32-frame inference.
- [x] Spec section 3: Tasks 1–7 cover the declared notebook, module, download entry point, lock, README, ignore additions, and focused tests.
- [x] Spec section 4: Task 3 covers acquisition isolation, offline local loading, device/precision selection, and separate initialization timing.
- [x] Spec section 5: Task 2 covers RGB, orientations, short videos, missing metadata, sequential fallback, local-only inputs, and cleanup.
- [x] Spec section 6: Task 4 covers prompt/candidate validation, token limits, stable keys, scores/logits, and inference without training.
- [x] Spec section 7: Task 4 specifies every metadata field and timing/memory boundary; Task 7 supplies actual GPU and serialization checks.
- [x] Spec section 8: Task 5 covers all notebook sections, prompt/category experiments, repeated warmed runs, DataFrames, failures, reference labels, and explicit exports.
- [x] Spec section 9: Tasks 1, 3, 5, and 7 cover ignored data, disabled tracking, in-memory frames, output clearing, and offline verification.
- [x] Spec sections 10–11: Focused red/green checks plus Task 7 cover acceptance; synthetic predictions are not represented as accuracy evidence.
- [x] Interface names, candidate-description mapping keys, metadata units, error handling, and device semantics agree across tasks.
- [x] The plan contains no unresolved placeholders, unrequested scope additions, automatic commits, or unauthorized subagent instructions.

## Execution Handoff

The written specification is approved. This plan is ready for task-by-task execution after the user selects the execution mode:

1. **Inline execution:** use `executing-plans` in this session, with review checkpoints between meaningful task batches.
2. **Delegated execution:** only on the user's explicit selection, use `subagent-driven-development` and dispatch bounded tasks with review between tasks.

Neither option authorizes Git commits. Keep all sponsor data local in either mode.
