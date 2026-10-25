# backend

Local SQLite ingestion, video retrieval, and activity classification for the
THIS IS ME face-detection CSV. Ingestion builds a six-table core analysis database
(schema in `db/schema.sql`), with audit history and person clips added by
`db/audit_clips.sql`. The `video_retrieval` package reads original video
frames, face crops, 32-frame clips, person-based segments, and variable-rate temporal samples into
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
## Application service (staff sign-in and API)

`api/` is a FastAPI layer over `analysis_db`. Every endpoint except sign-in and `/api/health`
needs a signed-in staff account. The service reads analysis records and writes accounts,
sessions, and review history in `../data/analysis.sqlite` by default. Back up this database
before initialization or replacement. Keep database changes containing local credentials
and participant/review records out of Git commits.

```bash
uv run python scripts/init_db.py --db ../data/analysis.sqlite
uv run python scripts/staff.py create <username>       # prompts for a password (min 8 chars)
uv run python scripts/serve.py                          # http://127.0.0.1:8000/api/docs
```

- `scripts/staff.py create|disable|enable|reset-password <username>` is the only way to
  manage accounts. Disabling or resetting a password ends that account's sessions.
- `scripts/serve.py` binds to `127.0.0.1:8000` by default. Use `--host` to expose it beyond this
  machine, `--db` (or `TPA_DB`) to choose another database, and `--video-dir` to change the only
  directory videos are streamed from (default `../data/videos`).
- Sessions are an HttpOnly, SameSite=Strict cookie that lasts 12 hours. Passwords are stored only
  as Argon2 hashes and session tokens only as SHA-256 digests.
- The reviewer recorded in review history is always the signed-in username. Request bodies
  that include `reviewer_id` are rejected.
- Endpoints (OpenAPI at `/api/openapi.json`): `auth/login|logout|me`; `videos`,
  `videos/{id}`, `videos/{id}/participants` (presence intervals from detections, with gaps of
  2 s or less merged), `videos/{id}/stream` (supports byte ranges); `participants`,
  `participants/{person_id}`; `annotations` (Spec 001 filters), `annotations/{id}`,
  `annotations/{id}/history`, `POST annotations`, `POST annotations/{id}/accept|reject|defer|edit`;
  `clips?order=time|priority`; `labels`; `exports/annotations|history?format=csv|json`.

Stored analysis is also exposed through authenticated, read-only endpoints:

- `person-clips?video_id=...&person_id=...&search=...&limit=...&offset=...` reads `Clip`/`ClipPerson`,
  ordered by video and time. Search matches video titles (case-insensitive substrings) or an exact
  clip ID, with or without `#`; it combines with review-status filters and pagination. Limit is
  1–1000. `person-clips/status-counts?search=...` returns matching totals for each status.
- `person-clips/{id}` returns the stored boundaries in seconds and actual participant IDs.
- `person-clips/{id}/summary` reuses the live current-label and visible-affect aggregation
  described under audited corrections below. It exposes neither filesystem paths nor media.
- `exports/database/{dataset}?format=csv|json`, where dataset is `clips`, `activity`,
  `engagement`, `activity-history`, `engagement-history`, or `clip-review-history`, reads the corresponding current
  analysis/audit records. CSV headers are retained for empty datasets; authentication tables
  are never exportable. Video summaries include `person_clip_count` separately from the
  existing review-suggestion `clip_count`.

These reads do not generate clips, run models, populate review tables, or alter analysis records.

Stored clips carry their own `review_status` (`UNREVIEWED`, `ACCEPTED`, `EDITED`, `DEFERRED`).
`POST person-clips/{id}/accept` and `/defer` change only that status. `POST person-clips/{id}/edit`
takes an active activity label and/or all three visible-affect scores, then marks the clip `EDITED`.
Activity edits create or update a `HUMAN` annotation spanning only analyzed frames whose timestamps
lie in the clip's half-open interval. Model `Activity` rows and neighboring clips remain unchanged.
Annotation edits append `ReviewEvent` history; the clip summary identifies this activity as human
reviewed, and normal annotation views/exports include it. A new label adds a reusable staff option
without renaming or deactivating previous labels. Labels become model candidates only when they
also have an explicit entry in `pipeline/activity_prompts.json`.
Visible-affect edits set member Engagement scores inside the clip through audited corrections.
Every action appends a `ClipReviewEvent` in the same transaction. `scripts/init_db.py` adds the
review-status column to older databases. Existing historical corrections are not rewritten.
Raw signals have no staff review status and no computed review priority. Existing staff
annotation/review APIs retain their behavior and separate ID namespace.

Stored clip responses expose `mean_positive_score` and `impact_score`, calculated on each read.
The user-approved impact formula is `ln(1 + clip seconds / 3) × 1.5^N × mean positive score` (D031), with N counting distinct
ClipPerson members and the mean using available same-video member observations in the clip's
half-open interval. Missing observations produce null scores; measured zero remains valid.
The frontend selects the top ten scored clips per video. Summaries use the same formula and
current corrected scores. No score column or schema migration is introduced. Video summaries
also expose `human_annotation_count`: human-sourced staff annotations plus distinct Activity
and Engagement records with correction audits. Repeated edits count each record once;
acceptance or deferral alone does not count as a human modification.

Review clips and AI annotations stay empty until the clip and annotation pipeline (a later
feature) runs. Every list then returns an empty array.

On macOS, `uv sync` installs the CPU/MPS build of the pinned `torch==2.8.0`. Linux and Windows
keep the CUDA 12.8 build.

## Importing pipeline output (Spec 004)

The service shows review clips and AI annotations only after a pipeline's output file has been
imported. Nothing in this repository generates that output yet. Clip segmentation, activity
inference, and affect aggregation are a later feature.

```bash
uv run python scripts/import_pipeline_output.py --input <run>.json   # --db defaults to the working DB
```

- Format `tpa-review-import/1`: see `specs/004-clip-annotation-pipeline/contracts/import-format.md`.
  Videos are referenced by filename and labels by name and category. Positions are frames.
- The whole file is validated first and stored in one transaction, or not at all. Imported
  annotations are `source = AI`, `review_status = UNREVIEWED`. Re-imports upsert by key.
  Reviewed annotations, and clips holding them, are never changed. Nothing is ever deleted.
- Each successful import is recorded as an `ImportRun` (pipeline, version, models, file hash,
  counts). It is visible on the dashboard and at `GET /api/imports`.
- Future generation stages implement the Protocols in `pipeline/stages.py`. They read signals
  with `pipeline.signals.load_video_signals` and turn proposals into a file with
  `pipeline.builder.build_import_file`, which derives deterministic keys.

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

Five review tables sit alongside them (see [Review model](#review-model)).
Review-table initialization also adds missing starter labels with `INSERT OR IGNORE`, preserving existing rows.

`scripts/init_db.py` creates the core schema from `db/schema.sql` and installs
the additive audit/clip extension from `db/audit_clips.sql`. Run it on an existing
database to add those tables, indexes, and triggers without rebuilding or removing
data. Each SQL script is transactional and idempotent. It does not convert legacy
Activity columns; use `scripts/migrate_activity.py` for that earlier migration.
Foreign keys are enforced on every connection. Existing ingestion results and
`table_counts()` continue to report the six core tables.

### Audited corrections and person clips

After all frame/detection imports and identity replacement are complete, finalize
person clips once. Activity and engagement predictions can be loaded before or
after finalization:

```bash
uv run python scripts/init_db.py --db ../data/analysis.local.sqlite
uv run python scripts/populate_clips.py --db ../data/analysis.local.sqlite
# Optional: finalize just one video, with a different persistence threshold.
uv run python scripts/populate_clips.py --db ../data/analysis.local.sqlite --video-id 3 --persistence-frames 5
```

The default threshold is five consecutive **stored analyzed frames** per person.
Confirmed arrivals/departures are backdated to the start of their qualifying run.
Short detection gaps do not split clips. Empty Frame records count as absences;
unstored source frames do not count as observations. Only nonempty confirmed
person sets produce clips. The first confirmed appearance starts at its first
qualifying frame; remaining confirmed presence extends to the video duration.
Trailing changes with too few observations are ignored.

Finalization is atomic per video and resumable across videos. It records videos
that produce zero clips too. Repeating the command returns the same clips,
including when the requested threshold changes. Boundaries, parent videos, and
memberships are immutable. Finish detection population before finalization;
later detection imports do not regenerate clips. Videos require finite positive
durations and increasing in-range frame timestamps.

Use explicit correction functions for user edits:

```python
from contextlib import closing
from pathlib import Path
from analysis_db.storage import connect_database
from analysis_db.corrections import correct_activity, correct_engagement

with closing(connect_database(Path("../data/analysis.local.sqlite"), must_exist=True)) as c:
    changed = correct_activity(c, activity_id=1, new_label="discussion")
    changed = correct_engagement(c, engagement_id=1,
                                positive_score=0.62, neutral_score=0.30,
                                negative_score=0.08, changed_by=None)
```

These methods require an idle connection with foreign keys enabled. Each returns
`True` on a correction or `False` on an exact no-op. Missing records raise
`LookupError`; invalid values raise `ValueError`. Scores must be finite and in
0–1, matching the existing schema; their sum need not equal one. Each correction
updates the current record and appends its old/new values in the same transaction.
Timestamps use UTC ISO 8601. `changed_by` is optional; no authentication is added.
Automated prediction writes create no audits. Activity prediction JSON and model
scores remain provenance; `Activity.activity_label` is the current corrected label.

Retrieve live summaries and original video portions using the existing retriever:

```python
from video_retrieval import VideoRetriever

r = VideoRetriever("../data/analysis.local.sqlite")
info = r.get_person_clip_info(clip_id=12)  # Frozen ClipInfo dataclass
summary = r.get_person_clip_summary(clip_id=12, include_details=True)
segment = r.get_person_clip(clip_id=12)  # VideoSegment, RGB uint8 frames
segment = r.get_segment(info.video_id, info.start_time_seconds, info.end_time_seconds)
```

`summary` includes the video ID/path, boundaries, people, activity dominant label
and distribution, engagement means, and per-person engagement summaries.
Activity weights are the duration of each prediction window's overlap with the
clip, normalized across all overlapping windows. Windows are independent evidence,
so their weights are not deduplicated timeline coverage. Dominant-label ties use
alphabetical order. Details include current Activity rows and `overlap_seconds`.
No activities yields a null dominant label and an empty distribution.

Engagement averages available observations for clip members in the same video's
half-open interval `[start, end)`. Missing observations are excluded. Each group
or person summary has `positive`, `neutral`, `negative`, and `observation_count`;
no observations yields null means and count zero. Group means are weighted by
observation count, not equally by person. Corrections appear on the next query
without changing clips. Database-only interfaces are available from
`analysis_db.clip_analytics` and `analysis_db.clips`.

Segment retrieval returns all frames with normalized presentation timestamps in
`[start, end)`, source frame indices, and requested boundaries. Comparisons use the
same floating-point precision as SQLite timestamps. Empty frame intervals raise
`ValueError`; there is no edge padding. Retrieval reuses source paths and PyAV,
opens the source once per segment, and writes no video files. Results follow the
existing RGB-array contract, with no audio or encoded playback container. Full
resolution segments can use substantial memory; retain only arrays you need.
The full presentation-timestamp stream is validated on each request, while only
in-range frames are converted to RGB; decoding cost scales with source duration.
The existing `get_clip(detection_id)` still returns its original 32-frame window.

See [`db/README.md`](db/README.md) for extension structures and lifecycle details.

The signal loader reads both legacy per-detection and new frame-linked Activity layouts.
Frame-linked results are shared only by detections at their center frame; their time windows
are converted to frame positions using the video's FPS. Loading never migrates or writes data.

Files are stored with **repository-relative paths** (e.g.
`data/videos/<name>.mp4`); videos are matched by **exact original filename**
(basename, case-sensitive) only under `--video-dir`. `--input`, `--db`, and
`--video-dir` are passed as-is to these operations, so defaults are module-derived
(from the repository layout) while explicit relative arguments resolve against the
current working directory.

## Review model

Annotations are the single **current state** every view and export reads; the review
history is a separate, **append-only** audit log.

- `Label`: staff-managed vocabulary, category `activity` or `observation`. 18 starter
  labels; labels are deactivated (`labels.set_label_active`), never deleted.
- `Annotation`: one label on a video frame span, optionally for one participant
  (no participant = group/scene level). Several labels on one moment are several rows.
  `confidence` is the model's certainty only; `source` (`AI`/`HUMAN`, who produced the
  current value) and `review_status` (`UNREVIEWED`/`ACCEPTED`/`EDITED`/`REJECTED`/
  `DEFERRED`, what review has happened) are independent.
- `ReviewEvent`: one row per human action (`review.create_annotation`, `accept`, `edit`,
  `reject`, `defer`), written in the same transaction as the annotation change, with
  previous and resulting values and an opaque non-empty `reviewer_id`. Triggers reject
  UPDATE and DELETE.
- `ReviewClip` / `ReviewClipParticipant`: review clips with the participants on screen and
  an optional review-priority score (unbounded, never a confidence or percentage).
  Clip cutting and scoring belong to a later pipeline.
- `annotations.import_machine_output` upserts pipeline output by `import_key`. It only
  updates `AI`/`UNREVIEWED` annotations and clips holding no reviewed annotation, and it
  never deletes.
- Rejected annotations are hidden from default queries and exports.

Export current annotations or the review history (CSV or JSON):

```bash
uv run python scripts/export_annotations.py --format csv --output ../data/annotations.csv
uv run python scripts/export_annotations.py --format json --history --output ../data/history.json
```

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
- Refused once the database holds any annotation or review clip: re-clustering would
  silently reassign the anonymous IDs that reviewed work refers to.

- Replacement is rejected after audit history or finalized clips exist, including
  finalization that produced zero clips. This preserves history and static identity
  membership. Perform identity replacement before user corrections and finalization.

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
- Retained detections keep their existing `engagement_id` through upserts. Imports
  do not append audit records. Attempting to remove an audited Engagement record
  rejects and rolls back the whole import, preserving its history.
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
