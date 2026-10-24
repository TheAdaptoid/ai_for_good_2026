# backend

Local SQLite ingestion and video retrieval for the THIS IS ME face-detection CSV.
Ingestion builds a six-table analysis database (schema in `db/schema.sql`). The
`video_retrieval` package reads original video frames, face crops, and 32-frame
clips into memory. Neither component runs models or performs inference.
Retrieval uses PyAV and NumPy; ingestion uses the standard library. Use `uv` to
manage dependencies, pytest, and the Jupyter/Matplotlib validation environment.

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

## Database

Six tables: `Video` (one row per probed video file), `Frame`, `Person`,
`FaceDetection` (bbox and detection score), plus `Activity` and `Engagement`,
which are **future outputs**: the pipeline performs no inference and these tables
stay empty.

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
