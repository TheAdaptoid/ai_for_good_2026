# backend

Local SQLite ingestion, video retrieval, and activity classification for the
THIS IS ME face-detection CSV. Ingestion builds a six-table analysis database
(schema in `db/schema.sql`). The `video_retrieval` package reads original video
frames, face crops, 32-frame clips, and variable-rate temporal samples into
memory. The `activity_classification` package additionally runs zero-shot X-CLIP
inference locally on those RGB frames. The activity runner saves frame-linked
predictions after an explicit schema migration. Retrieval uses PyAV and NumPy; ingestion uses the standard
library; classification uses PyTorch and Transformers. Use `uv` to manage
dependencies, pytest, and the Jupyter/Matplotlib validation environment.

## System prerequisites

- **ffprobe** (from FFmpeg) is required for ingestion: every referenced video is
  probed for metadata. Install it system-wide so `ffprobe` is on `PATH`.
- **ffmpeg** is optional and only needed by `tests/test_real_video.py`, which
  synthesizes a small clip; that test skips automatically when either tool is absent.

## Setup and operation (run all commands from `backend/`)

```bash
uv sync --locked
uv run python scripts/init_db.py
uv run python scripts/ingest.py --input ../data/csv/
uv run python scripts/ingest.py --input "../data/csv/activity_frame_person_map - activity_frame_person_map.csv"
uv run python scripts/init_db.py --db ../data/custom.sqlite
uv run python scripts/ingest.py --input ../data/csv/ --db ../data/custom.sqlite --video-dir ../data/videos/
uv run pytest -q
```

## Video retrieval

Run from `backend/` after ingesting the database and placing originals under
`data/videos/`:

```python
from video_retrieval import DetectionInfo, VideoRetriever

retriever = VideoRetriever()  # Default: ../data/analysis.sqlite
# Or: VideoRetriever(db_path="../data/custom.sqlite")

info: DetectionInfo = retriever.get_detection_info(detection_id=1)
frame = retriever.get_frame(info.video_id, info.frame_number)
face = retriever.get_face(info.detection_id)
clip = retriever.get_clip(info.detection_id)

print(info.person_id, info.bbox)
print(frame.shape, face.shape, clip.shape)
```

Use a detection ID from your database. Metadata preserves string `person_id` and
`frame_id` values and includes the source timestamp. Every returned array is RGB
`uint8`. Face crops retain their original size: lower bbox coordinates round down,
upper coordinates round up, and all bounds are clamped to the decoded image.

`get_frame` takes a **zero-based original frame index**, including frames without
stored detections. `get_clip` returns `(32, height, width, 3)` for the inclusive
window `[frame_number - 16, frame_number + 15]`. Slot 16 is the detection frame.
Out-of-bounds slots repeat the actual first or last frame; a reference detection
itself beyond the video end raises an error.

The retriever reuses the configured database/repository paths. It opens short-lived
read-only SQLite connections and closes each decoder after use. Images stay in
memory; retrieval does not export files or change records. Keep only the arrays
you need: a 32-frame 1080p RGB clip occupies about 190 MiB.

PyAV decodes sequentially in presentation order from the beginning to preserve
exact indexing, including H.264 B-frames. It converts only requested frames to
RGB and opens a video once per clip. Late requests in long originals have linear
decoding latency; there is no persistent cache or approximate seeking.

Errors identify the missing record or invalid request:

| Exception | Meaning |
| --- | --- |
| `LookupError` | Video or detection ID is absent. |
| `FileNotFoundError` | The original video file is absent. |
| `ValueError` | Frame index is invalid/outside the video, or a crop is empty/nonfinite. |
| `RuntimeError` | The original cannot be opened or decoded. |
| `sqlite3.Error` | The database cannot be opened or queried. |

### Validation notebook

```bash
uv run jupyter lab notebooks/video_retrieval_validation.ipynb
```

The notebook shows database totals, a reproducibly selected detection, the source
frame and bbox, the unresized crop, and a 4×8 clip contact sheet. It checks true
decoded video boundaries, all 32 slots for available beginning/middle/end cases,
and original presentation timestamps against stored zero-based source times.
Inspect the images to confirm visible face alignment.

The default pool uses up to three shortest originals of at most 120 seconds to
keep sequential validation practical. Set `VALIDATION_VIDEO_IDS = (11,)` and
`MAX_VIDEOS = 1` for a shorter run on the supplied dataset, or choose IDs from your
database. `DB_PATH` accepts a custom database. Missing boundary cases are reported
explicitly. All-slot checks make many independent requests and can take minutes.

Keep the notebook's saved outputs cleared, including execution counts. Do not
save or export displayed identifying images. The repository notebook contains no
image outputs. Automated tests synthesize their own originals and temporary
databases; `uv run pytest -q` does not require the private dataset.

## Activity classification (X-CLIP)

Zero-shot activity ranking of in-memory RGB clips with the pinned checkpoint
`microsoft/xclip-base-patch16-zero-shot` at revision
`6746d6a5202bf24300cd9bf36f457f174483d41b`. All commands run from `backend/`,
and `backend/` has no sibling-project dependencies: its environment, cache,
downloader, notebook, and tests work standalone.

```bash
uv sync --locked
uv run --locked python -m activity_classification.download_model
uv run --locked jupyter lab notebooks/activity_classification.ipynb
```

`download_model` is the only acquisition step: the first run fetches
`model.safetensors` and config/tokenizer assets (~600 MB) into the backend cache
`backend/.cache/huggingface/hub`; afterwards everything, including the notebook,
runs from only those local files, never the network, a sibling project, or a
global cache.

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

- **Reference labels & quality summaries.** The notebook's `REFERENCE_LABELS` is
  a manual, editable mapping (detection -> exact candidate label). Accuracy is
  computed only over manually labeled detections whose four conditions all
  succeeded, with the denominator and exclusions disclosed; softmax scores are
  relative to the candidate list, so larger values do not establish quality. No
  dataset accuracy has been measured and none is claimed.
- **Temporal sampling.** Targets derive from presentation timestamps relative to
  the first decoded frame's PTS, centered on the detection's stored
  `source_time_seconds`. Each target picks the nearest frame (ties take the
  earlier frame); targets past the first/last frame repeat that frame as
  left/right padding. `unique_frame_count`, `*_padding_count`, and
  `source_frame_indices` expose repeats and bounds; the stored center is never
  rewritten. Windows decode sequentially to end-of-stream to establish true
  boundaries, so late windows in long originals cost linear decoding time, with
  no cache or approximate seeking.
- **Devices.** `device="auto"` selects CUDA (FP16) when available, otherwise CPU
  (FP32); pass `device="cpu"` explicitly. Results carry device/dtype and peak
  CUDA memory. CUDA `OutOfMemoryError` becomes an actionable `RuntimeError`
  with no automatic CPU retry.
- **Validation.** Inputs must be uint8 `(T, H, W, 3)` RGB; prompts may not be
  blank, duplicated, exceed the checkpoint's 77-token text limit, or omit
  required descriptions; logits/scores are checked for finiteness; frames are
  subsampled (nearest, stable) to the checkpoint's 32.
- **Direct model paths.** `model_path=<dir>` must contain exactly the pinned
  revision's assets (`config.json`, tokenizer, `model.safetensors`); it is not a
  way to relabel arbitrary checkpoints.
## Frame-linked activity benchmark

Use a local working copy of the database. Create it once with SQLite's backup
API; this includes existing engagement results and leaves the shared file alone:

```bash
uv run --locked python -c "from pathlib import Path; import sqlite3; p=Path('../data/analysis.local.sqlite'); assert not p.exists(), 'Reuse the existing local DB'; s=sqlite3.connect('file:../data/analysis.sqlite?mode=ro',uri=True); d=sqlite3.connect(p); s.backup(d); d.close(); s.close()"
uv run --locked python scripts/migrate_activity.py --db ../data/analysis.local.sqlite
uv run --locked python scripts/classify_activity.py --db ../data/analysis.local.sqlite --sample-size 100 --seed 42 --dry-run
uv run --locked python scripts/classify_activity.py --db ../data/analysis.local.sqlite --sample-size 100 --seed 42 --device cuda --precision fp32 --batch-size 2 --prefetch-batches 2 --report results/activity_benchmark_seed42.json
```

The migration replaces the **empty legacy Activity table**. It preserves all other
tables, including Engagement. It is idempotent and rejects unknown schemas or a
nonempty legacy Activity table. Schema initialization does not migrate old tables.
Both new CLI commands default to `data/analysis.local.sqlite` when `--db` is omitted.

The runner uses all person IDs and selects distinct frames with detections. It
samples 100 center frames without replacement using seed 42, then orders those
frames by video/time. Each input has 32 samples over a centered 15-second window.
The runner builds a timestamp-only index once per selected video, seeks to each
window, and reports any sequential-decode fallback. This preserves exact source
indices and padding, without decoding the whole original for each request.

### Activity labels and automatic uncertainty

`activity_pipeline/config.py` defines 11 known activities, including Acting and
Speaking, and a complete description for each. The runner uses these descriptions
directly as model prompts. It does not score an Unknown or Uncertain candidate.

Each saved result applies this rule automatically:

```python
activity_label = top.label if top.score > MIN_ACTIVITY_SCORE else UNCERTAIN_LABEL
```

The defaults are `MIN_ACTIVITY_SCORE = 0.65` and
`UNCERTAIN_LABEL = "Uncertain result"`. Exactly 0.65 also produces the uncertainty
label. No manual decision is required. `Activity.score` remains the highest known
class score. `result_json` retains all ranked predictions and adds a `decision`
object containing the stored label, uncertainty flag, and threshold.

The cutoff uses candidate-relative softmax scores, not calibrated certainty.
Changing labels, descriptions, or the decision policy changes the configuration
hash and schedules old results for recomputation when inference resumes. Code
updates alone do not recalculate previously stored predictions.

FP32 and batch size 2 are the runner defaults, based on GTX 1650 measurements.
The older single-clip classifier retains its device-based default when precision
is omitted; pass `precision="fp32"` to override it. One CPU worker prepares batches
in a queue of capacity two; only the consumer uses CUDA and writes results. No
frames or crops are saved. Batch result timings are amortized shares; the report
contains raw batch durations and whole-pipeline wall time.

Repeat the command to resume **the same selected sample**. It skips matching
config/input hashes and does not replace completed sample members with new frames.
Use another report filename to preserve the original timing report. `--all`
selects the full population; `--limit N` optionally caps pending attempts in either
mode. Batch size, precision, queue depth, seed, and sample size are configurable.
The runner stops after its selected work; it does not start a full run automatically.
An all-cached resume does not load model weights or decode videos. Ctrl-C saves
completed rows and writes a partial report when `--report` is set.

The JSON report separates model/index/warm-up setup from processing wall time.
Its remaining-time estimate uses wall time per newly completed frame, including
retrieval, preparation, GPU work, and writes. Phase totals overlap and must not be
added. Partial or all-skipped runs are labeled; skipped work is not timed inference.
Unrepresented videos and future index-build costs limit the estimate.

### Measured benchmark: October 24, 2026

The GTX 1650 run completed 100 seeded center frames in 50 FP32 batches, with zero
failures and zero seek fallbacks. Setup took 1,801.18 seconds (30.0 minutes).
Processing took 302.79 seconds (5.05 minutes), or 3.028 seconds per center frame.
The remaining 34,352 centers were estimated at 28.89 hours, excluding future setup.

Retrieval totaled 256.84 seconds, preparation 41.51 seconds, inference 77.95
seconds, and writes 28.09 seconds. These phases overlap. Peak allocated GPU memory
was 1,381.8 MiB. Retrieval is the current bottleneck. The sample covered videos
1-6; videos 7-12 were not sampled. These figures estimate runtime, not accuracy.
The repeat run skipped all 100 without model loading or decoding.
This timing run used the earlier nine generic prompts. The current 11 expanded
prompts and automatic uncertainty policy were added after that benchmark.

Activity stores the automatic decision label and highest known-class score,
full ranked results, actual sampling metadata,
configuration, and resume hashes. A successful changed configuration replaces the
frame's current result. Scores are candidate-relative, not calibrated probabilities.
Detections share the activity of their center frame, not every activity window
that happens to overlap them. Missing Activity means unprocessed, not negative.

```sql
SELECT d.person_id, d.detection_id, f.video_id, f.source_time_seconds,
       a.activity_label, a.score,
       e.positive_score, e.neutral_score, e.negative_score
FROM FaceDetection d JOIN Frame f ON f.frame_id = d.frame_id
LEFT JOIN Activity a ON a.frame_id = f.frame_id
LEFT JOIN Engagement e ON e.detection_id = d.detection_id
WHERE d.person_id = ?
ORDER BY f.video_id, f.frame_number, d.detection_id;
```

Engagement contains single-frame facial-expression scores, not established
measurements of engagement, mood, or satisfaction.

### Publish repeated 500-instance checkpoints

`scripts/run_activity_checkpoints.py` runs from an isolated worktree. Its input
and output is the tracked `data/analysis.sqlite` in that worktree. Seed it from
the migrated local database before starting. The main checkout must be on `main`.

```bash
uv run --locked python scripts/run_activity_checkpoints.py --main-root "$MAIN_CHECKOUT" --chunk-size 500 --device cuda
```

Each chunk processes up to 500 pending centers with FP32, GPU batch size 2, and
the current prompts/uncertainty rule. The process retains the loaded model and
timestamp indexes between chunks. It verifies integrity, foreign keys, and exact
preservation of the five non-Activity tables before committing only the SQLite
file. It integrates concurrent main/remote commits in the inference worktree,
fast-forwards local main, and pushes main after each checkpoint. Unrelated staged
work in the main checkout is preserved.

Reports and progress logs belong under ignored `backend/results/checkpoints/`.
The final shorter chunk is also published. Ctrl-C or SIGTERM stops processing and
saves a partial report; completed rows remain in the worktree even if the partial
chunk has not been published. A validation/Git error stops the loop without a
force-push. GitHub checkpoints must stay below its 100 MiB per-file limit. Inference
code changes merged during the run require a restart before the next chunk.

## Database

Six tables: `Video` (one row per probed video file), `Frame`, `Person`,
`FaceDetection` (bbox and detection score), `Activity` (one result per center
frame), and `Engagement` (facial-expression scores per detection). The supplied
database has engagement results. The activity runner writes only Activity.

`scripts/init_db.py` creates the schema idempotently from `db/schema.sql`
(`CREATE TABLE IF NOT EXISTS`). It is **not** a schema migration: an existing
database is never altered, so delete and re-create the file if the schema changes.
Foreign keys are enforced on every connection.

Files are stored with **repository-relative paths** (e.g.
`data/videos/<name>.mp4`); videos are matched by **exact original filename**
(basename, case-sensitive) only under `--video-dir`. `--input`, `--db`, and
`--video-dir` are passed as-is to these operations, so defaults are module-derived
(from the repository layout) while explicit relative arguments resolve against the
current working directory.

## Ingestion behavior

- `--input` accepts a single CSV/TSV file **or a directory**; directory entries are
  processed in sorted order, `.csv`/`.tsv` files only, and anything else is
  reported as ignored. Comma and tab delimiters are both supported.
- The row stream is validated and inserted transactionally with **file-level
  rollback**: if any row of a file fails (including an ffprobe failure), nothing
  from that file is committed and processing continues with the next file. The
  input stops at the first bad row, so unread rows are not counted as rejected.
- Original **person, frame, and video identifiers** are preserved verbatim;
  `detection_id` is a database-local generated integer.
- Re-importing an identical row is a **skip**; a conflicting duplicate (same
  identity, different values) rejects the whole file. Conflicts within one file
  behave the same way.
- CSV columns beyond the required detection columns are ignored; image fields such
  as `full_frame_path`/`face_crop_path` are not read, and **no images, crops,
  models, or extraction ever happen**.

## Replacing identity results

`scripts/replace_identity.py` loads an identity run's schema-shaped tables
(`VIDEO.csv`, `FRAME.csv`, `PERSON.csv`, `FACE_DETECTION.csv`, as written by the
identity pipeline's `Database/` folder) in one transaction:

```bash
uv run python scripts/replace_identity.py --tables <run>/Database --db ../data/analysis.local.sqlite
```

- `Video` is kept. `VIDEO.csv` is only used to map its `video_id` values to the
  existing rows by exact `filename`; an unknown filename aborts before any write.
- `Activity`, `Engagement`, `FaceDetection`, `Frame`, and `Person` are cleared, then
  the new rows are inserted with **their `detection_id` values preserved**, because
  downstream activity/engagement handoffs join on them.
- Foreign keys, `PRAGMA integrity_check`, and row counts are verified before commit;
  any failure rolls back and leaves the database unchanged (exit code `1`).

## Loading face-expression (engagement) results

`scripts/load_engagement.py` replaces `Engagement` with the per-detection CSV written by
`notebooks/face_expression_observation_pipeline.ipynb`
(`face_expression_observations_from_videos.csv`; keep it in the gitignored `data/csv/`):

```bash
uv run python scripts/load_engagement.py --input ../data/csv/face_expression_observations_from_videos.csv --db ../data/analysis.local.sqlite
```

- Uses `detection_id`, `positive_score`, `neutral_score`, `negative_score`; other columns stay in the CSV.
- Rows with all three scores empty (observations the notebook logged as errors) are skipped and counted.
- Every `detection_id` must exist in `FaceDetection`; duplicates or scores outside 0–1 abort before any write.
  After a re-clustering run that drops detections (IDs and boxes of the kept ones unchanged), pass
  `--skip-missing-detections` to reuse the existing scores for the kept detections; skipped rows are counted.
- One transaction with foreign-key, integrity, and row-count checks; any failure leaves the database unchanged.
- Scores are derived visual-expression classifications, not measurements of internal emotional state.

## Exit codes and output

- `0` — every input file committed.
- `1` — at least one file was rejected, or a runtime/input failure occurred
  (missing or un-initialized database, no input files, ffprobe unavailable).
- `2` — command-line usage error (e.g. missing `--input`).

Per file, the summary is `name: committed; rows=<read> inserted=<detection rows>
skipped=<detection rows> rejected=<detection rows>` with per-table detail for
committed files, or `name: rolled back; ...` plus the error reason on stderr. After
processing, all six table counts are printed regardless of whether any file failed.
Errors are concise one-line messages; no tracebacks for expected failures.

## About the supplied dataset

The supplied CSV references 12 distinct originals. At planning time only two were
in `data/videos/`; at the time of writing 11 of 12 are present (only
`THIS IS ME-camp2 montage-FINAL.mp4` is not). Additional originals can be dropped
into `data/videos/` with no code changes, but **one missing video invalidates the
whole CSV file** that references it, and ingesting such a file commits nothing.
As part of normal ingestion, do not alter or split the original CSV.
