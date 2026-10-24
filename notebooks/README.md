# Local activity recognition with X-CLIP

`activity_recognition.ipynb` is an experimental, local zero-shot workflow for
ranking activity descriptions against video clips. It uses pretrained X-CLIP
without training. It is not a production activity-recognition system.

## Setup and launch

Run all commands below from `notebooks/` with [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync --locked
uv run --locked python download_model.py
uv run --locked jupyter lab activity_recognition.ipynb
```

Initial dependency installation and the explicit model-download command need
network access. The notebook does not run the download command. Once dependencies
and model assets are cached, you can launch offline:

```bash
uv run --locked --offline jupyter lab activity_recognition.ipynb
```

The project supports Python 3.11–3.13; `.python-version` selects 3.13. Manage
dependencies through uv and retain `uv.lock`. PyTorch comes from the explicit
`pytorch-cu128` index. The same environment supports CPU inference.

The observed environment on 2026-10-24 was Python **3.13.14**, PyTorch
**2.8.0+cu128**, Transformers **4.57.6**, CUDA runtime **12.8**, and an
**NVIDIA GeForce GTX 1650** with
driver **595.99.02**. The CUDA 13.2 shown by `nvidia-smi` describes driver support,
not the CUDA runtime used by PyTorch. Inspect the current runtime with:

```bash
uv run --locked python -c "from activity_recognition import device_info; print(device_info())"
```

## Model cache and local data

`download_model.py` downloads `microsoft/xclip-base-patch16-zero-shot`, pinned to
revision `6746d6a5202bf24300cd9bf36f457f174483d41b`. Configuration, tokenizer
assets, and `model.safetensors` go into `.cache/huggingface/hub/` under
`notebooks/`, without a duplicate `pytorch_model.bin`.

Import `activity_recognition` before Hugging Face dependencies. The module sets
offline flags before loading those dependencies and uses `local_files_only=True`
for initialization. Import alone does not load weights or read videos. Inference
uses local files only; images and videos are never uploaded. Telemetry and external
experiment tracking are disabled, including during model acquisition.

## Configure and run the notebook

Edit the tagged input-configuration cell. Restart the kernel and run all cells.
The default `VIDEO_PATHS: list[str] = []` runs diagnostics without weights or videos.

| Setting | Default and use |
| --- | --- |
| `VIDEO_PATHS` | `[]`; local video paths. Use distinct filename stems as video IDs. |
| `ACTIVITIES` | Nine editable activity labels, listed below. |
| `DEVICE` | `"auto"` selects CUDA when available, otherwise CPU; `"cpu"` forces CPU. |
| `REPEATS` | `3` measured calls per video/experiment pair, after one excluded warmup. |
| `REFERENCE_LABELS` | `{}`; map video IDs to canonical keys, e.g. `{"clip_01": "playing_sports"}`. |
| `EXPORT_RESULTS` | `False`; enable explicitly to write results. |
| `OUTPUT_DIR` | `Path("results")`; local export directory. |

Default labels: Dancing, Singing, Playing sports, Playing games, Running, Walking,
Sitting and listening, Drawing or painting, and Other activities. Edit
`EXPERIMENTS` and `DESCRIPTIONS` to compare short labels, full descriptions, or
candidate sets. Description mappings must cover every original label exactly.

Portrait and landscape videos are supported, subject to OpenCV codec support.
Each classification samples **32 frames uniformly across the full clip** and
converts OpenCV BGR frames to RGB. Very short clips repeat frames. The checkpoint
resizes and center-crops, so activities near the edges can be lost. Frame/FPS
timestamps and duration are approximate for variable-frame-rate video.
`sample_video(..., num_frames=...)` supports custom preview sampling counts;
classification always uses the checkpoint's native 32 frames, not 8 or 16.

## Python API

`classify_activity(video_path: str, activities: list[str]) -> dict` returns a
JSON-compatible result. These example paths are placeholders for a local clip:

```python
from activity_recognition import classify_activity

result = classify_activity("videos/local_clip.mp4", ["Dancing", "Walking"])
cpu_result = classify_activity(
    "videos/local_clip.mp4", ["Dancing", "Walking"], device="cpu"
)
```

Optional keyword arguments are `device`, `prompt_template`, `descriptions`, and
`video_id`. The default template is `"A video of people {activity}."` with
lowercased labels. `descriptions` maps original labels to full prompts and
replaces the template. Prompts longer than 77 tokens raise an error rather than
being truncated.

For repeated calls, use `get_recognizer(device="auto").classify(...)` from
`activity_recognition`. It caches one `XCLIPRecognizer` for reuse with the same
device. `XCLIPRecognizer(device="cpu")` explicitly constructs a CPU recognizer.
Load once and process one clip at a time using read-only inference: CUDA uses
FP16 and CPU uses FP32. Initialization time is separate in `load_time_seconds`.

## Interpret results and measurements

**Scores are candidate-relative, uncalibrated softmax values, not confidence.**
Adding or removing candidates changes their normalization. Raw logits are also
returned. “Other activities” is an ordinary candidate, not an unknown-activity
detector. Mixed activities produce ranked alternatives, not independent multilabel
detections or person identities. Measure accuracy on manually labeled clips;
repeated runs of one clip are not independent labeled examples.

Useful result fields include:

| Fields | Meaning |
| --- | --- |
| `activity`, `scores`, `logits` | Winning canonical key and per-candidate values. |
| `labels`, `prompts`, `model_revision` | Original labels, exact prompts, and pinned model revision. |
| `video_id`, `clip_start`, `clip_end` | Clip ID and full-clip interval from zero to estimated duration. |
| `num_frames`, `sampled_frame_indices`, `unique_sampled_frames` | Sampling count, source indices, and number of distinct frames. |
| `device`, `dtype` | Actual execution device and precision. |

The notebook shows individual results, rankings, reference comparisons, and
median/min/max latency across measured repeats. Timing boundaries are:

- `preprocessing_time_seconds`: input validation, frame sampling, text preparation,
  and CPU processor work.
- `inference_time_seconds`: device transfer, forward pass, score normalization,
  CPU copies, and CUDA synchronization.
- `total_time_seconds`: the full classification call, excluding one-time model
  initialization/download, plots, and exports.

Each video/experiment pair gets one excluded warmup before measured repeats.
CUDA peak counters reset per classification call.
`peak_gpu_memory_allocated_mib` measures peak tensor allocation;
`peak_gpu_memory_reserved_mib` measures peak allocator reservation. Both include
the resident model: neither measures incremental usage or total system VRAM.
CPU memory fields are `None` (JSON `null`).

## Exports and saved outputs

No frame or result files are written automatically. With `EXPORT_RESULTS = True`
and successful records, each explicit export overwrites `activity_results.json`,
flattened `activity_results.csv`, and separate `activity_errors.csv` under
`OUTPUT_DIR` with current-run data. The errors CSV is header-only when no failures
occurred. Never store extracted frame files.

Jupyter can retain preview frames and derived data in saved notebook outputs.
Clear outputs before committing or sharing:

```bash
uv run --locked jupyter nbconvert --ClearOutputPreprocessor.enabled=True --inplace activity_recognition.ipynb
```

The root `.gitignore` covers local datasets, sponsor videos, and generated results.
`notebooks/.gitignore` covers the environment, model assets, caches, and notebook
HTML exports. Planning files under `docs/superpowers/*` are intentionally ignored
and do not appear in normal Git status.

## Troubleshooting

| Problem | Action |
| --- | --- |
| Missing or incomplete model cache | Run `uv run --locked python download_model.py` with network access, then retry. |
| Video cannot open or decode | Check the local path and whether the installed OpenCV backend supports its codec/container. |
| Invalid labels or prompts | Use nonempty, distinct labels with distinct ASCII keys; supply complete description mappings and shorten prompts over 77 tokens. |
| CUDA unavailable | `"auto"` uses CPU. An explicit `"cuda"` request fails; check the driver or select `"cpu"`. |
| CUDA out of memory | Free GPU memory or explicitly retry with `device="cpu"`. There is no automatic CPU retry. |

## Verification status

Evidence recorded on 2026-10-24:

| Check | Status |
| --- | --- |
| CUDA tensor matrix operation | Passed on the environment above. |
| Fast acceptance suite | 123 passed; the normal run skips all 5 opt-in smoke cases. |
| Pinned-checkpoint CPU/CUDA offline smokes | 2 passed in 27.62 s, with Python network connections blocked and zero connection attempts. |
| In-memory notebook acceptance | 3 passed in 39.24 s: empty defaults without weights, configured CUDA with exports disabled, and configured CUDA with JSON/CSV exports plus a separate missing-file error. |
| Lockfile consistency | `uv lock --check` passed. |

The model smokes used the cached, pinned checkpoint and its **native 32 frames**.
CPU processed a synthetic blank-red **2-second MJPG/AVI** (60 source frames,
Dancing/Walking). CUDA processed an actual, temporarily encoded **12-second
MP4/mp4v** (360 source frames, 96×64 moving rectangle) with **all nine initial
categories**. Both checked finite JSON, normalized scores, correct full-clip
duration, actual device/precision, and consistent scores/ranking across two calls.
The second call measured:

| Device and synthetic input | Inference | Total classification | Peak allocated / reserved |
| --- | --- | --- | --- |
| CUDA FP16, 12 s MP4, 9 candidates | 3.545 s | 3.642 s | 580.708 / 680 MiB |
| CPU FP32, 4 PyTorch threads, 2 s AVI, 2 candidates | 7.904 s | 7.979 s | Not applicable |

These synthetic clips confirm functionality and this environment's MP4 codec
support, not activity accuracy or performance on real teenage-activity videos.
The two device measurements use different clips and candidate sets; they do not
establish CPU/GPU score equivalence. Other codecs and variable-frame-rate clips
remain subject to OpenCV support and approximate frame/FPS timestamps.

Notebook acceptance launched real kernels with the uv interpreter, checked inline
PNG plots and JSON/CSV score/timing agreement, and kept missing-file failures out
of successful records. Inputs and exports were temporary and removed. Execution
did not alter the saved notebook bytes: all saved code-cell outputs remain empty
and execution counts remain `null`.

Non-model tests do not download or load checkpoint weights:

```bash
uv run --locked pytest -m 'not model_smoke' -q
uv run --locked pytest -q
```

The opt-in checks require the already-cached model. The model tests explicitly
request CPU and CUDA; an unavailable-CUDA skip does not satisfy GPU acceptance.
Notebook checks use CUDA when available, otherwise CPU. Recorded commands:

```bash
RUN_XCLIP_SMOKE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --locked --offline pytest tests/test_model_smoke.py -q -s
RUN_XCLIP_SMOKE=1 uv run --locked --offline pytest tests/test_notebook_smoke.py -q
uv lock --check
```
