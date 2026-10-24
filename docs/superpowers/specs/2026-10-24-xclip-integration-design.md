# Local X-CLIP integration and temporal-context experiment

## Goal and approval

Provide a reusable backend classifier and a notebook that selects an existing
face detection, retrieves original video frames in memory, and ranks configurable
activity descriptions using local X-CLIP inference.

The backend classifier approach was approved on 2026-10-24. The requested
experiment adds four conditions: 32 consecutive frames and 32 uniformly sampled
frames over 5, 10, and 15 seconds around the same detection. The user clarified
that code must be ported from the existing notebook implementation: backend must
be self-contained except for the SQLite database and original video files.

## Existing components

- `backend/video_retrieval/VideoRetriever` returns RGB uint8 arrays. Its existing
  `get_clip(detection_id)` returns 32 consecutive frames with the detection at
  slot 16 and repeated edge frames at video boundaries.
- `analysis_db.storage.connect_database` supports read-only SQLite connections.
- `notebooks/activity_recognition.py` already loads and runs a pinned local
  X-CLIP checkpoint, but its classification entry point accepts a video path.
- The checkpoint is `microsoft/xclip-base-patch16-zero-shot`, revision
  `6746d6a5202bf24300cd9bf36f457f174483d41b`. Its configuration specifies 32
  frames, 224-pixel image inputs, and a 77-token text context.
- Its processor specifies resizing, center cropping, and normalization with
  means `[0.485, 0.456, 0.406]` and standard deviations `[0.229, 0.224, 0.225]`.
  Use the checkpoint processor rather than duplicating these transformations.
- The existing notebook environment pins PyTorch 2.8.0 and Transformers 4.57.6.
  The runtime works around that Transformers version's video-routing issue by
  calling the tokenizer and image processor components directly.

## Architecture

### Self-contained backend classifier

Create `backend/activity_classification/` with typed result objects and a
frame-input classifier. Keep model loading explicit and separate from inference;
load once and reuse across notebook conditions.

Port the existing candidate preparation, checkpoint loading, preprocessing,
device handling, and forward-pass logic into this package. Do not import the
top-level `notebooks/activity_recognition.py` module, its downloader, or any other
code outside `backend/`. Normal imports from installed third-party dependencies
and backend-local modules are appropriate. The classifier core has no SQLite or
video-decoder dependency. It accepts an RGB uint8 frame array or sequence and
configurable activity labels, prompt template, or descriptions.

Read the required frame count from `model.config.vision_config.num_frames`.
Uniformly select the required number of frames across the supplied input when
counts differ; repeat indices for shorter inputs. Return selected input indices
so adaptation is inspectable. The approved experiment uses 32 input frames and
the pinned 32-frame checkpoint, so no adaptation changes these four conditions.

Return descending predictions containing the original label, exact prompt, raw
logit, and candidate-relative softmax score. Also return checkpoint revision,
actual device and dtype, preprocessing time, synchronized inference time, and
total classification time. Model loading and video retrieval are timed separately.

Use evaluation mode and `torch.inference_mode()`. Automatic device selection uses
CUDA when available and CPU otherwise. Preserve FP16 on CUDA and FP32 on CPU,
explicit CPU selection, finite-output checks, useful missing-cache messages, and
clear CUDA-memory failures with an explicit CPU retry option.

Use only local model assets at inference time. Store the default model cache
under `backend/.cache/huggingface/`, with paths derived from the backend package
location rather than the working directory or a sibling directory. Allow an
explicit local model/cache path. Provide an explicit model acquisition command
within `backend/`, ported from the existing downloader. It downloads public model
assets only and is separate from inference. Do not use the top-level notebook
cache as a default or fallback; setting up the backend must work without it.

### Backend independence and setup

Keep the existing top-level `notebooks/activity_recognition.py` implementation
and its environment unchanged. Its source is a porting reference, not a runtime
dependency. The new detection workflow uses PyAV through backend retrieval and
does not need the notebook implementation's OpenCV whole-video sampler.

Declare all new runtime and development dependencies in `backend/pyproject.toml`
and update `backend/uv.lock`. Port the working ML version pins and CUDA wheel
index configuration into the backend configuration. Do not add an editable
dependency on a sibling project, search parent directories for application code,
or require the top-level notebook virtual environment. Any notebook import-path
setup is limited to locating the containing backend directory.

Put setup instructions, model acquisition, inference, the evaluation notebook,
and new tests under `backend/`. Document commands that run from `backend/` using
its own uv environment. Only the database and original videos are external
application assets. Continue to reuse the existing backend database and retrieval
utilities for those assets. New model-cache ignore rules belong in
`backend/.gitignore`, so handling backend-generated assets does not depend on
the parent project's ignore rules.

### Temporal retrieval extension

Add a separate `VideoRetriever` method for temporal sampling, accepting a
detection ID, positive finite interval duration, and positive integer sample count
(default 32). Preserve `get_clip()` exactly.

Sample equally spaced target timestamps including both endpoints, centered on
the detection's source timestamp. Decode the original video sequentially in
presentation order and select the nearest available frame to each target;
ties select the earlier frame. Use presentation timestamps relative to the
video's first decoded frame so variable-frame-rate sources are handled in time,
not by assuming a constant frame rate. Report a clear error for missing or
non-monotonic timestamps rather than silently claiming precise temporal sampling.

Clamp targets beyond video boundaries to the actual first or last decoded frame.
Preserve the requested centered window rather than shifting it inward. Validate
that the reference frame exists, so padding cannot conceal invalid detection
metadata. Convert only selected frames and necessary nearest-neighbor candidates
to RGB; never materialize a dense 15-second RGB clip.

Return frames with actual zero-based source frame indices, source timestamps,
requested interval bounds, and enough metadata to show unique-frame counts and
boundary padding. These are in-memory results, not Activity table records.

## Evaluation notebook

Create `backend/notebooks/activity_classification.ipynb` with these sections:

1. Imports and editable configuration: database path, detection IDs, candidate
   labels, optional descriptions, device, and optional reference labels.
2. Read-only database inspection and deterministic selection of one valid
   detection by default. Permit a short explicit list for the experiment and
   favor short videos to keep sequential decoding practical.
3. Detection metadata and representative original frames.
4. Explicit local model loading with checkpoint, frame-count, device, and load-time
   diagnostics.
5. Initial consecutive-clip inference and ranked-label display.
6. Four-condition experiment using identical detections, candidates, prompts,
   checkpoint, and precision:
   - `consecutive_32`: existing `get_clip()` output;
   - `uniform_5s`: 32 samples across a centered five-second interval;
   - `uniform_10s`: 32 samples across a centered ten-second interval;
   - `uniform_15s`: 32 samples across a centered fifteen-second interval.
7. Compact contact sheets and a comparison table with top predictions, reference
   label if present, reference-label rank and score, top-1 correctness, top-3
   inclusion, retrieval/preprocessing/inference times, actual source span,
   unique-frame count, and boundary-padding indicators.
8. A short editable observations cell for useful temporal context, scene changes,
   unrelated people, and apparent errors.

Process one condition at a time and release its full-resolution clip after
classification and preview creation. Keep only compact results and previews in
memory. Use a warmup before timed experiment inference and exclude it from
reported inference measurements.

Reference labels are an optional editable mapping from detection ID to one of
the candidate labels, assigned by human inspection. When references are absent,
show rankings and support visual comparison without claiming measured accuracy.
When references are present, summarize top-1 and top-3 agreement per condition
over the same labeled detections and show the number of evaluated detections.
Missing or invalid references must not silently become incorrect predictions.

Higher softmax scores alone do not establish better classification quality.
Longer windows may include scene cuts or activities different from the detection
moment; record these as experiment observations. Predictions describe full-frame
content and are not attributed reliably to the detected person.

## Errors and data handling

Validate empty clips, image shape and dtype, invalid labels, duplicate candidates,
invalid duration/count, and prompts exceeding model context. Preserve retrieval
errors for missing detections, missing videos, and invalid reference frames.
For multi-detection notebook experiments, collect condition-specific failures
without treating failed predictions as successful quality measurements. Summary
comparisons must disclose failures and use a common successful evaluation set.

Keep all sponsor data, frames, crops, predictions, and model inference local.
The notebook makes no SQLite writes or automatic result exports. Save its source
with outputs cleared and execution counts unset. Preserve existing user changes
in both existing notebooks. Do not commit files unless explicitly requested.

## Verification

- Synthetic classifier tests cover input adaptation, validation, actual processor
  routing, candidate ordering, score normalization, and CPU/CUDA selection without
  downloading weights.
- Synthetic encoded-video tests cover temporal sampling, exact source indices,
  nearest-frame selection, presentation-time offsets, variable frame rate,
  repeated boundaries, short sources, invalid timestamps, and invalid references.
- Existing retrieval tests verify unchanged consecutive-clip behavior.
- A backend-independence check verifies that the classifier can import and run
  without the top-level notebook module, environment, downloader, or cache.
- A local cached-checkpoint smoke test exercises a real model and a small real
  detection selection through all four conditions. Verify CPU support separately
  with a small synthetic clip when practical.
- Execute the new notebook locally, inspect generated comparisons, then clear
  its outputs and execution counts. Record actual verification outcomes without
  inferring dataset-level accuracy from smoke tests.

## Scope

This delivers the approved local proof of concept and the requested small temporal
experiment. Batch inference, Activity writes/schema decisions, person tracking,
person-centered cropping, and engagement-model integration remain later work.
