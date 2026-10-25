# Frame-linked activity pipeline

Date: 2026-10-24. Status: draft for user review.

## Goal and deadline

Build a small, resumable activity pipeline before work moves to the frontend.
The submission deadline is Sunday at 10 AM. The user reported Saturday at
9:41 PM when requesting this spec. Complete a seeded 100-frame benchmark before
attempting the full dataset. This document covers database migration, frame
selection, optimized inference, and a measured estimate of the remaining work.

## Current database, checked after PR #2

| Table | Rows |
| --- | ---: |
| Video | 12 |
| Frame | 34,452 |
| Person | 100 |
| FaceDetection | 50,514 |
| Activity | 0 |
| Engagement | 50,514 |

Integrity and foreign-key checks pass. Every detection has one engagement row.
Kept detections have unchanged IDs, frames, boxes, and detection scores compared
with the database before re-clustering. Each person ID has at least 87 detections.
Use all person IDs. Remove the percentile filter from the pipeline requirements.
Keep the occurrence notebook as an optional inspection tool.

There are 34,452 distinct frames with detections. A real-clip timing check on the
GTX 1650 found 3.55 seconds of model time in FP16 versus 0.85 seconds in FP32.
FP32 batch size 2 measured about 0.76 seconds of model time per clip. These short
checks exclude decoding. Use the 100-frame benchmark below for the full-pipeline
estimate. Full-dataset completion is not a prerequisite for frontend work.

## 1. Database change

Replace the detection-linked Activity table with this frame-linked table:

```sql
CREATE TABLE Activity (
    activity_id INTEGER PRIMARY KEY,
    frame_id TEXT NOT NULL UNIQUE REFERENCES Frame(frame_id) ON DELETE CASCADE,
    window_start_seconds REAL NOT NULL,
    window_end_seconds REAL NOT NULL,
    sample_count INTEGER NOT NULL CHECK (sample_count = 32),
    activity_label TEXT NOT NULL CHECK (length(trim(activity_label)) > 0),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    sampling_json TEXT NOT NULL CHECK (json_valid(sampling_json)),
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    config_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (window_end_seconds > window_start_seconds)
);
```

- `frame_id` identifies the center frame. Several detections can share its result.
- Window times are the requested boundaries. A start time may be negative.
- `result_json` contains the complete `ClassificationResult`, including ranked
  candidates, resolved prompts, logits, scores, model revision, device, and timings.
  It also stores the automatic decision label, uncertainty flag, and cutoff.
- `sampling_json` contains original source frame indices and timestamps, target
  timestamps, decoded reference time, unique-frame count, padding counts, and
  retrieval time. Each sample array has exactly 32 entries.
- `config_json` records the resolved inference settings described in section 3.
- `score` is the top candidate's relative softmax score, not a probability of
  correctness. Keep that score even when `activity_label` is "Uncertain result".
  Save the known activity label only when its top score is greater than 0.65.
  Scores at or below 0.65 automatically produce "Uncertain result".
- Store one current result per center frame. Replace it only after a new
  classification succeeds. Historical runs are outside this milestone.

Add an explicit, transactional migration. It accepts the exact legacy schema
only when Activity is empty. It also accepts the new schema as an idempotent
no-op. Reject unknown schemas or a nonempty legacy Activity table without writes.
Check foreign keys and integrity before commit. On failure, roll back all changes.
Preserve Video, Frame, Person, FaceDetection, and all existing Engagement rows.
Update `schema.sql` so fresh databases receive the same Activity structure.
Do not treat `initialize_database()` as a migration.

## 2. Select center frames

Read the database as the source of truth. Earlier handoff CSVs have stale person
IDs and include detections removed by re-clustering.

The eligible population is every distinct Frame that has a FaceDetection. Use
the smallest detection ID as its reference anchor. Sort the population by video
ID, source frame number, then frame ID. A frame occurs only once in this list,
regardless of how many people share it. No person filter or spacing rule applies.

For the benchmark, use `random.Random(42).sample(population, 100)` without
replacement. Sample before checking completed Activity rows. Then sort the chosen
jobs by video ID, frame number, and frame ID for efficient processing. This changes
execution order, not sample membership. Do not replace failed or completed sample
members with other frames. Reject a requested sample larger than the population.
An empty population returns an empty report without loading the model.

For the inspected database, the sample contains 6 frames from video 1, 61 from
video 2, 4 from video 3, 26 from video 4, 1 from video 5, and 2 from video 6.
This is an observed baseline, not a hard-coded selection. Record the selected
frame IDs and population fingerprint so the actual sample can be checked later.
The population fingerprint hashes canonical JSON of the ordered frame IDs,
video IDs, frame numbers, source times, and video file metadata used by input hashes.

The current schema does not retain the identity notebook's
`selected_downstream_frame` flag. This selection therefore uses stored detections,
not an assumed reconstruction of the old handoff selection.

## 3. Run and resume classification

Defaults:

```python
INTERVAL_SECONDS = 15.0
SAMPLE_COUNT = 32
BATCH_SIZE = 2
PRECISION = "fp32"
PREFETCH_BATCHES = 2
BENCHMARK_SIZE = 100
SEED = 42
MIN_ACTIVITY_SCORE = 0.65
UNCERTAIN_LABEL = "Uncertain result"
ACTIVITIES = (
    "Dancing", "Rapping", "Singing", "Acting", "Speaking", "Playing sports", "Playing games",
    "Running", "Walking", "Sitting and listening", "Drawing or painting",
)
```

Reuse the pinned X-CLIP checkpoint. Use the complete per-class descriptions in
`activity_pipeline/config.py` as prompts for all 11 known activities. Uncertainty
is an automatic output rule, not a scored model candidate. Keep settings in one
backend module. Load the model once with FP32
weights and FP32 inputs on CUDA. Do not load FP16 weights and then convert them
back to FP32. CPU remains FP32. Add an explicit precision option to the classifier;
preserve its existing default behavior for callers that omit that option.

### Faster retrieval with the same samples

Add an indexed temporal sampler for the runner. Decode each selected source video
once to build an in-memory index of presentation timestamps and original frame
indices. Do not convert these index-building frames to RGB. Validate timestamps
and establish the actual first/last frame and decoded reference times.

For each window, use that index to select the same 32 nearest-PTS source frames
as `get_temporal_clip`. Seek to a preceding keyframe and decode only through the
last required source frame. Map decoded timestamps back to original frame indices;
do not count frame indices from the seek position or infer them from FPS. If a
seek misses a required frame, retry sequential decoding for that window and
report the fallback. Do not silently substitute samples.

Keep `get_clip` and `get_temporal_clip` unchanged as the reference implementation.
The new sampler must match their applicable temporal output exactly: RGB pixels,
indices, timestamps, nearest-frame ties, requested bounds, and padding metadata.
Windows stay centered on stored source time. The label still describes the video
window, not an independent action measurement for each visible person.

### Preparation and GPU execution

Use one CPU producer and one GPU consumer. The producer retrieves and preprocesses
clips into model-ready CPU tensors. It groups up to two clips into a batch and
places prepared batches in a queue with capacity two. Release each full-resolution
RGB clip after preprocessing. Do not fill the queue with full-resolution videos.

The consumer transfers one batch to CUDA, runs inference once, and returns one
`ClassificationResult` per input clip in input order. Apply softmax across candidate
labels separately for each clip. Keep the final short batch; do not duplicate a
clip to fill it. Preserve the existing single-clip classifier API and result fields.
Record actual batch size in sampling metadata. Per-result batch timings are
amortized shares, not independently measured clip latencies. Report raw batch
timings separately. Peak GPU memory is the whole-batch peak.

Only the consumer uses CUDA or writes SQLite results. Save each successful result
in a short transaction. Use a cancellation signal and bounded queue operations so
producer failure, consumer failure, or Ctrl-C cannot leave a blocked worker behind.
Keep all model assets and inference local. Use inference mode and no silent CPU
retry. Configurable batch size and precision allow later timing comparisons.

Compute a SHA-256 `config_hash` from canonical JSON containing checkpoint ID and
revision, ordered labels and resolved prompts, automatic decision policy, interval,
sample count, indexed sampler version, configured batch size, resolved device,
and dtype. Sample size, seed, and queue
capacity do not change a clip's intended model input and stay outside this hash.
Compute `input_hash` from frame ID, video ID, source
frame number, stored source time, repository-relative video path, file size, and
mtime in nanoseconds. File metadata detects ordinary source replacements; it is
not a content checksum. Originals must remain unchanged during a run.

Skip an existing row only when both hashes match. On a mismatch, recompute it.
Changing person IDs alone does not change model inputs, but the existing identity
replacement operation clears Activity. Do not replace identities during inference.

CLI: `--db`, repeatable `--video-id`, `--sample-size` (default 100), `--seed`
(default 42), `--all`, optional `--limit`, `--batch-size` (default 2), `--precision`
(default fp32), `--prefetch-batches` (default 2), `--device`, `--dry-run`, and
optional `--report PATH`. `--all` disables random selection and is mutually
exclusive with an explicit `--sample-size`. `--limit` is an optional cap on
pending attempts in either mode; there is no additional default 50-frame cap.

Choose sample membership before resume filtering. Skip matching sample members
and retry only pending members of that same sample. A full rerun after 100
successful writes skips all 100. A later `--all` run can reuse those results.
Dry-run reports population, selected membership/counts, per-video counts, and
settings. It does not load the model, decode videos, migrate, or write records.

Print selected, skipped, attempted, written, and failed counts. Report failures
with frame/video IDs. Continue after an individual clip failure; leave its row
absent or its previous result unchanged. Abort on database/configuration/model
load errors or CUDA OOM. An interruption preserves completed transactions. A run
with failures exits nonzero. An empty selection does not load the model.

### Benchmark timing and remaining-work estimate

1. Record selection, model load, timestamp-index build, and synthetic warm-up times
   as setup costs. Warm the configured batch shape before timing real inference.
2. Time the processing stage from starting the producer through the final result
   commit. Include retrieval, preprocessing, queue waits, GPU work, and DB writes.
3. Record completed/failed/skipped counts, actual batch sizes, per-video coverage,
   retrieval/prepare/GPU/write phase durations, peak GPU memory, and seek fallbacks.
   Phase totals can overlap. Do not add them to estimate end-to-end runtime.
4. Compute `seconds_per_frame = processing_wall_seconds / written` for newly
   completed frames. Count remaining eligible frames whose config/input hashes do
   not match a completed Activity row. Estimate `remaining * seconds_per_frame`.
5. Report setup costs separately. Explain that a fresh process must rebuild its
   indexes and reload the model. Index setup for unsampled videos is not measured.
   Report per-video counts and retrieval times; the overall estimate is a
   ballpark from this workload, not a completion guarantee.

The primary benchmark requires 100 newly successful frames and no failures. Label
interrupted/resumed/failed runs as partial timing samples. If no new frames finish,
report no measured rate rather than divide by zero or use skip time as inference
time. Do not silently remove cached Activity rows to force a fresh benchmark.

Print a concise summary. With `--report`, also save numeric/text JSON containing
settings, population fingerprint, selected IDs, raw timings/counts, coverage, and
the estimate. The benchmark command saves this report under ignored `results/`.
Stop after the sample and report the estimate. Do not start `--all` automatically.

## 4. Small-run acceptance checks

- Migration is atomic and idempotent. Other tables, especially Engagement, retain
  their data. New and migrated databases have equivalent Activity constraints.
- Two detections in one frame produce one input clip and one Activity row.
- Boundary windows contain 32 samples and disclose repeats and padding.
- Indexed retrieval matches the existing temporal sampler, including VFR,
  nonzero starting PTS, tie selection, boundaries, and actual source frame indices.
- FP32 batches return every input's result in order, including a final singleton.
  Batch/single results agree within tested floating-point tolerances.
- Resume keeps the same seeded sample and recomputes changed prompts, precision,
  sampling settings, or source inputs. Failed replacements preserve the old result.
- CPU preparation and GPU inference overlap without unbounded memory or worker
  leaks. Exceptions and Ctrl-C leave completed transactions intact.
- A synthetic runner check uses temporary videos/databases and a deterministic
  classifier substitute. It verifies selection, persistence, failure, and resume.
- A real GPU run processes 100 unique randomly sampled center frames, seed 42,
  using FP32, batch size 2, indexed retrieval, and a queue of two prepared batches.
  Inspect selected contact sheets and predictions in memory. Require 100 writes,
   50 real-data inference batches, and a timing report. Rerun the same sample to verify 100
  skips and no new inference. Do not claim accuracy without reference labels.
- Existing backend checks pass. Notebook-cleanliness failures must be fixed by
  clearing outputs/counts while preserving current source edits, not by disabling
  the checks.

## Data handling and handoff

Only numeric/text results and sampling metadata are saved. Do not save images,
crops, contact sheets, or notebook outputs. Keep models and inference local.
Perform the real migration and benchmark on `data/analysis.local.sqlite`, created
with SQLite's backup API. Keep the tracked shared database unchanged during the
implementation check. The later API can query the same local working database.

Frontend query path: Person -> FaceDetection -> Frame -> Activity. Engagement
remains linked to FaceDetection. Show these as video-window activity and
single-frame facial-expression scores. The Engagement table does not establish
emotion, satisfaction, or engagement. Do not change its stored values here.
