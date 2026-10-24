# Local Video Activity Recognition Prototype

- Date: 2026-10-24
- Status: Design written for user review
- Project location: `notebooks/`

## 1. Objective and approved decisions

Build an experimental Jupyter notebook that classifies local 10–15-second video
clips against user-defined activity descriptions using
`microsoft/xclip-base-patch16-zero-shot`. Use the pretrained model without
fine-tuning. The prototype must support evaluating accuracy, prompt sensitivity,
latency, and GPU memory use on manually labeled examples.

The user approved the notebook-plus-module design and fixed 32-frame sampling.
The checkpoint has a native temporal length of 32 frames. Sample those frames
uniformly over the entire clip; do not use only the first 32 consecutive frames.
The earlier proposed 8/16-frame experiments are superseded. Do not interpolate
temporal embeddings, change temporal layer configuration, or repeat a smaller
sample merely to simulate a lower inference cost.

All sponsor video processing, visualization, and inference run locally. A
separate setup step may download model artifacts from Hugging Face. Normal
inference must work offline after that download.

## 2. Environment and repository integration

The repository already contains a minimal `uv` project in `notebooks/` with a
Python 3.13 interpreter selection and no dependencies. Extend that project.
Support Python 3.11–3.13, retain Python 3.13 as the selected development
interpreter, and verify dependency resolution with `uv`.

Observed hardware after the user's reboot:

| Property | Observed value |
| --- | --- |
| GPU | NVIDIA GeForce GTX 1650 |
| VRAM | 4,096 MiB |
| NVIDIA driver | 595.99.02 |
| Driver-supported CUDA version reported by `nvidia-smi` | 13.2 |

These observations confirm that `nvidia-smi` works; they do not yet verify
PyTorch CUDA execution. During implementation, install a CUDA-enabled PyTorch
build compatible with this GPU and driver, then verify `torch.version.cuda`,
`torch.cuda.is_available()`, and an actual GPU tensor operation. The PyTorch
CUDA runtime version need not equal the version displayed by `nvidia-smi`.

Manage every dependency and notebook command through `uv`. Declare the PyTorch
package source explicitly where needed so an ordinary project sync reproduces
the tested installation. Commit-ready deliverables include a generated
`uv.lock`. Use stable dependency versions with compatible constraints based on
the implementation checks.

Required libraries are PyTorch, Transformers, Hugging Face Hub, OpenCV, NumPy,
Matplotlib, Pandas, JupyterLab, and ipykernel. Include notebook validation and
focused test dependencies in development dependency groups as needed. Use the
headless OpenCV distribution because previews use Matplotlib, not GUI windows.

## 3. Deliverables and component boundaries

```text
.gitignore
docs/superpowers/specs/2026-10-24-activity-recognition-design.md
notebooks/
  .python-version
  pyproject.toml
  uv.lock
  README.md
  activity_recognition.ipynb
  activity_recognition.py
  tests/
```

### Notebook

The notebook is the experiment interface. It contains explanations, editable
configuration, device diagnostics, model initialization, single-video examples,
visualizations, prompt and candidate-set comparisons, batch experiments, and
explicit metadata export. It imports reusable functions from the Python module.
It must not duplicate the inference implementation across cells.

### Reusable module

The module owns local input validation, frame sampling, privacy-related runtime
configuration, model loading, prompt preparation, classification, measurements,
and result construction. Importing it must not download weights, load the
model, read a video, or start inference.

Use a small recognizer object to own the processor, model, device, and inference
configuration. Provide a public convenience function with the required call:

```python
classify_activity(video_path: str, activities: list[str]) -> dict
```

The convenience function reuses a lazily initialized recognizer rather than
loading weights for each clip. Optional keyword arguments may expose prompt
templates, explicit per-label descriptions, a caller-supplied video ID, and
device selection. The recognizer object supports explicit initialization and
reuse in the notebook and future pipeline integration.

### Supporting files

The README documents `uv` setup, CUDA verification, model download, offline
execution, notebook launch, local video configuration, exports, and known
interpretation limits. The root `.gitignore` excludes local datasets, sponsor
videos, caches, environments, checkpoints, notebook checkpoints, generated
results, and temporary files. Examples must use synthetic paths and content.

## 4. Model acquisition and local execution

Set telemetry and experiment-tracking disable flags before importing the
relevant ML libraries. Do not integrate external experiment trackers or remote
inference APIs. Do not enable remote model code.

Provide an explicit model-download command or setup cell. Download the model,
processor, tokenizer, and configuration artifacts needed for subsequent local
loading into an ignored project-local cache. Record the resolved model revision
in the run metadata when available.

Normal model loading uses `local_files_only=True` and offline Hugging Face
settings. A missing or incomplete cache produces an actionable error that
points to the separate download step. It must not silently attempt network
access. The first-time download is not part of inference latency.

Select CUDA automatically when available and otherwise select CPU. Allow an
explicit CPU override. Report the selected device, PyTorch version, PyTorch
CUDA runtime version, GPU name, total VRAM, and free VRAM when accessible.
Use evaluation mode and `torch.inference_mode()`.

Process one clip at a time. CUDA inference uses an appropriate supported
precision to fit the 4 GiB device, initially FP16; CPU inference uses FP32.
Record the actual precision. Integer token tensors retain their integer dtype.
If GPU inference runs out of memory, release per-call resources and report an
actionable error with the explicit CPU option. Do not silently report a CPU
retry as a successful GPU measurement.

## 5. Local video loading and preprocessing

The sampler accepts a local regular file path. Reject URLs and paths that do
not identify a readable local file before passing input to OpenCV. Support MP4
and other formats available through the installed OpenCV codecs; file extension
alone does not establish codec support.

For the approved inference path, extract exactly 32 RGB frames in chronological
order using uniform frame indices from the first through the last frame. Clips
with fewer than 32 source frames use deterministic repeated indices and report
the number of unique sampled frames. The reusable sampling helper may accept a
frame-count parameter, but classification validates that its input count equals
the checkpoint's native 32 frames.

Use container frame-count and FPS metadata when valid. If frame-count metadata
is unavailable or seeking cannot retrieve the requested frames, use a bounded-
memory sequential decoding fallback to establish and sample the actual frame
range. Do not retain every decoded frame. If usable FPS or timing information
is unavailable, report a clear error rather than invent clip timestamps.
Release the capture on both successful and failed reads.

Retain portrait or landscape orientation through sampling and honor rotation
metadata when the OpenCV backend supports it. Convert BGR frames to RGB, then
use the checkpoint's processor for resizing, center cropping, and normalization.
Do not stretch portrait frames into squares manually. Explain that the model's
center crop can remove activity near the image edges.

Return sampled indices and available source metadata with the in-memory frames.
Frame-index sampling is approximately uniform in time for constant-frame-rate
video. Record the sampling method and explain the limitation for variable-frame-
rate sources. Display a configurable subset of sampled frames on request.
Never write extracted frames to disk by default.

## 6. Labels, prompts, and inference

Initial editable labels:

- Dancing
- Singing
- Playing sports
- Playing games
- Running
- Walking
- Sitting and listening
- Drawing or painting
- Other activities

Validate that candidates are nonempty, unique strings. Create stable readable
keys such as `playing_games`; reject normalized-key collisions. Preserve the
original labels separately from these keys and the actual text prompts.

Use a natural-language default template such as `A video of people {activity}.`
with sensible casing. Support raw-label experiments with an identity template
and descriptive experiments with a per-label prompt mapping, including
`A group of teenagers dancing to music.`. Keep the same category keys when only
prompt wording changes. Validate prompt token lengths against the checkpoint's
text limit and provide a clear error rather than silently truncating them.

Process all candidate descriptions and the sampled video with the checkpoint's
processor. Run a single-video forward pass, obtain `logits_per_video`, and apply
softmax across the candidate set to calculate relative scores. Return the
highest-ranked candidate and all candidate scores, preserving the associated
raw logits for analysis.

The scores are candidate-relative, uncalibrated similarities. Adding or removing
candidates changes the normalization. A high score does not establish that the
activity is actually present, and `Other activities` is an ordinary text
candidate, not a learned unknown-class detector.

For clips containing multiple activities, show the ranked candidates and
discuss competing or overlapping descriptions. Do not present softmax scores
as independent multi-label probabilities. Temporal segmentation and per-person
activity assignment are outside this prototype.

## 7. Measurements and structured results

Use a monotonic high-resolution clock. Synchronize CUDA at timing boundaries
so asynchronous work is included. Report:

- Preprocessing time: validation, video loading/sampling, text preparation, and
  CPU processor work.
- Inference time: device transfer, model forward pass, score normalization, and
  copying scores back to CPU, with CUDA synchronization at completion.
- Total time: the complete classification call through result construction,
  excluding one-time model initialization, downloads, plots, and file export.
- Peak allocated and reserved GPU memory during the measured call, in MiB.
  Allocated memory includes the resident model; it is not incremental memory
  use or total system VRAM consumption. CPU runs report these fields as null.

Model initialization is measured separately. The notebook provides a labeled
untimed warm-up before repeated latency comparisons. Reset CUDA peak statistics
before each measured call. Do not retain GPU tensors in returned metadata.

The result is directly serializable using `json.dumps(..., allow_nan=False)`.
Its fields are:

| Field | Meaning |
| --- | --- |
| `video_id` | Caller-provided ID, otherwise local file stem |
| `clip_start` | `0.0`, relative to the supplied clip |
| `clip_end` | Estimated full clip duration in seconds from available source metadata |
| `model` | Full Hugging Face model identifier |
| `model_revision` | Resolved cached revision, or null if unavailable |
| `activity` | Highest-ranked candidate key |
| `scores` | Candidate key to relative softmax score |
| `logits` | Candidate key to raw model similarity logit |
| `labels` | Candidate key to original label |
| `prompts` | Candidate key to actual inference description |
| `score_type` | `candidate_relative_softmax` |
| `num_frames` | `32` |
| `unique_sampled_frames` | Number of distinct source frame indices used |
| `sampled_frame_indices` | Chronologically ordered source indices |
| `sampling_method` | Uniform frame-index sampling |
| `device` | Actual execution device |
| `dtype` | Actual model precision |
| `preprocessing_time_seconds` | Measured preprocessing latency |
| `inference_time_seconds` | Measured inference latency as defined above |
| `total_time_seconds` | Measured classification latency |
| `peak_gpu_memory_allocated_mib` | Peak PyTorch allocated GPU memory, or null |
| `peak_gpu_memory_reserved_mib` | Peak PyTorch reserved GPU memory, or null |

Use native Python values, not NumPy scalars, tensors, paths, NaN, or infinity.
Do not include frames, embeddings, or absolute source paths in results. Exact
timeline offsets in an original longer video are a future caller concern;
the prototype classifies the entire supplied clip.

## 8. Notebook workflow and experiments

Organize the notebook into sequential sections:

1. Purpose, local-data handling, and score interpretation.
2. Runtime configuration, device diagnostics, and separate download instructions.
3. Local cached model initialization and model-load timing.
4. Editable clip paths, categories, and prompt definitions.
5. Uniformly sampled frame preview, single-clip classification, predicted label,
   horizontal candidate-score chart, timing summary, and GPU memory summary.
6. Raw-label versus descriptive-prompt comparisons with stable candidate keys.
7. Candidate-set experiments, including similar actions and mixed-activity clips.
8. Multi-video results and repeated warmed latency measurements in Pandas.
9. Explicit optional JSON and CSV export to an ignored local results directory.

Frame count stays fixed at 32 in every classification experiment. Annotate runs
with experiment name, candidate set, prompt strategy, and repeat index in the
experiment table. Use separate score columns or a long-form score table to make
plots and comparisons straightforward.

Allow manually supplied reference labels and show a straightforward match
summary when those labels exist. Do not make accuracy claims without labeled
examples. Batch failures produce identified error rows while successful clips
continue; single-clip calls raise clear exceptions. Separate failed rows from
valid inference results in exports.

The notebook runs setup and explanatory cells without sponsor data. Cells that
need clips give a clear configuration message when the editable video list is
empty, rather than referring to an unavailable example file.

## 9. Data handling

All video inputs remain local. No clips, frames, scores, labels, or other derived
data are sent to a remote service. Model acquisition is the only intended
network operation and runs separately from video classification.

Keep previews and results in memory unless the user explicitly exports them.
Explain that Jupyter can persist displayed frames and metadata inside a saved
notebook. Deliver the notebook with empty outputs and no execution counts, and
document clearing outputs before committing it. Ignore notebook checkpoints
and generated HTML or other notebook exports that may contain sponsor data.

No automatic frame extraction files, video copies, result exports, or external
tracking logs are created during ordinary inference. Focused tests use synthetic
videos only; temporary test files are cleaned up.

## 10. Errors and verification

Provide clear errors for missing or remote inputs, unreadable videos, unsupported
codecs, missing timing metadata, decode failures, empty or duplicate candidates,
normalized-key collisions, invalid prompts, missing cached model artifacts,
unsupported frame counts, and CUDA allocation failures. Preserve the original
cause when wrapping library errors.

Verification has three layers:

1. **Local synthetic checks:** verify uniform sampling and RGB conversion,
   portrait and landscape handling, short-clip repeated indices, invalid input
   rejection, and finite JSON-compatible output construction. Verify relevant
   inference plumbing without downloading weights where practical.
2. **Notebook and environment checks:** resolve/sync with `uv`, validate notebook
   structure, run data-independent cells, verify imports, and confirm the
   delivered notebook contains no saved frames or results. Confirm ignore rules
   cover representative video, cache, and output paths.
3. **Real-model checks:** download the checkpoint explicitly, verify an actual
   CUDA tensor operation, and run 32-frame classification on a synthetic clip
   with CUDA. Verify finite scores, top-ranked selection, measured latency, and
   GPU memory fields. In a fresh process with offline settings, reload the
   cached model and repeat inference. Also check explicit CPU inference.

A synthetic clip verifies functionality, not activity-recognition accuracy.
Later manual experiments use sponsor clips locally and compare results with
reference labels. Record any blocked checks accurately; a working driver alone
does not satisfy the GPU-inference acceptance criterion.

## 11. Acceptance criteria and scope

The implemented prototype is ready for experiments when:

- A local video is sampled into 32 RGB frames across its full duration.
- The pretrained X-CLIP checkpoint ranks editable activity candidates.
- The notebook displays sampled frames, predictions, scores, timing, and memory.
- Multiple clips and experiment configurations can be compared in DataFrames.
- Structured results can be explicitly exported as valid local JSON metadata.
- CUDA-enabled PyTorch and real model inference are verified on the GTX 1650.
- An explicit CPU path works, and cached model inference works offline.
- Generated data and model artifacts are excluded from version control.

This is an experimental classifier, not a production application. Face detection,
identity recognition, engagement scoring, individual participation attribution,
databases, web interfaces, training, and timeline generation are outside scope.

## 12. Next step

Review this written specification with the user. After approval, create the
implementation plan before changing application code or dependencies.
