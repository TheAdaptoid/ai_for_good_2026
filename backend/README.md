# backend

Local SQLite ingestion pipeline for the THIS IS ME face-detection CSV. It builds a
six-table analysis database (schema in `db/schema.sql`) with no model, frame, or
image processing of any kind, and no network access. Runtime dependencies are the
standard library only (`uv` is used to manage the Python environment and pytest).

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
