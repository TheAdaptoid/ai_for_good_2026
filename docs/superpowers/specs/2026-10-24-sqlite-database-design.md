# Video Analysis SQLite Database Design

- Date: 2026-10-24
- Status: Design approved in conversation; implementation not started
- Application location: `backend/`
- Repository root: `/mnt/storage/Projects/ai_for_good_2026`
- Source: The user's SQLite Database Specification, sections 1–10

## 1. Objective and scope

Create a local SQLite database for video metadata, original person and frame
identifiers, and face detections imported from comma- or tab-separated files.
Create empty Activity and Engagement tables for future model outputs. Use Python's
built-in `sqlite3`, `csv`, and `subprocess` modules and local `ffprobe`.

Do not implement face detection, clustering, tracking, frame extraction, activity
or engagement inference, aggregation, analytics, or visualization. Do not read,
copy, or store frame images, face crops, or their source paths.

## 2. Approved repository integration

The user selected Approach A: one streaming pass and one explicit transaction per
input file. Conflicting data or invalid rows roll back the entire affected file.
Independent files can still be imported successfully.

```text
repository/
├── data/
│   ├── videos/                 # User-provided original videos
│   ├── csv/                    # User-provided CSV/TSV inputs
│   └── analysis.sqlite
├── backend/
│   ├── db/schema.sql
│   ├── scripts/init_db.py
│   ├── scripts/ingest.py
│   ├── analysis_db/            # Small reusable implementation modules
│   ├── tests/
│   ├── pyproject.toml
│   ├── uv.lock
│   └── README.md
└── docs/superpowers/
    ├── specs/2026-10-24-sqlite-database-design.md
    └── plans/2026-10-24-sqlite-database.md
```

Run documented commands from `backend/`:

```bash
uv run python scripts/init_db.py
uv run python scripts/ingest.py --input ../data/csv/
```

Resolve defaults from the scripts' repository location, independent of the working
directory: database `<repository>/data/analysis.sqlite`, video directory
`<repository>/data/videos`. Explicit relative CLI arguments use the caller's
working directory. Store resolved video paths relative to the repository root,
such as `data/videos/example.mp4`; never store absolute paths. The `--video-dir`
override must resolve inside the repository; reject paths outside it rather than
inventing a storage convention. Require `--input`.

The root `.gitignore` already excludes `data/` and `docs/superpowers/*`. Preserve
these rules. Preserve the existing notebook working-copy modification. Do not
stage or commit files without a separate explicit request.

## 3. Schema

Use the six table names and columns from the source specification: `Video`,
`Frame`, `Person`, `FaceDetection`, `Activity`, and `Engagement`.

- `Video`: automatically generated integer primary key; unique non-null filename
  and repository-relative path; non-null title; nullable creation date, duration,
  FPS, width, and height.
- `Frame`: original text primary key, non-null Video foreign key, nonnegative
  integer frame number and timestamp; unique `(video_id, frame_number)`.
- `Person`: original nonempty text primary key.
- `FaceDetection`: automatic integer primary key; non-null Person and Frame
  foreign keys; original numeric bounding box and detection score; unique
  `(frame_id, person_id)`; checks for ordered coordinates and a score in `[0, 1]`.
- `Activity`: automatic integer primary key; unique non-null detection foreign
  key; non-null start/end frame, label, and confidence;
  `CHECK(end_frame = start_frame + 31)`. Negative start frames remain possible:
  the future pipeline owns boundary handling for windows `[f - 16, f + 15]`.
- `Engagement`: automatic integer primary key; unique non-null detection foreign
  key; non-null positive/neutral/negative scores, each checked in `[0, 1]`.
  There is no constraint on their sum.

Use `CREATE TABLE/INDEX IF NOT EXISTS`. Add the three requested indexes on
`Frame.video_id`, `FaceDetection.person_id`, and `FaceDetection.frame_id`.
Enable foreign keys on every application connection. Frame deletion cascades to
its detections and Video deletion cascades to its frames as approved; other
relationships retain SQLite's restrictive default. No deletion CLI is added.

## 4. Responsibilities and interfaces

- `db/schema.sql`: complete schema and indexes; no data deletion or migration.
- `analysis_db/contracts.py`: row, metadata, counter, and error types shared by
  parallel implementation tasks.
- `analysis_db/paths.py`: repository discovery, default locations, and relative
  video-path policy.
- `analysis_db/storage.py`: connections, idempotent schema initialization,
  conflict-aware entity insertion, and table counts. Insert helpers never commit.
- `analysis_db/csv_input.py`: input discovery, delimiter detection, streaming
  parsing, required-header checks, and typed row validation.
- `analysis_db/video_metadata.py`: exact video-filename lookup and local
  `ffprobe` JSON parsing.
- `analysis_db/ingestion.py`: one transaction per input file, metadata cache,
  per-file outcomes, rollback, and directory-level continuation.
- `scripts/init_db.py` and `scripts/ingest.py`: thin CLI adapters and reporting.
- `tests/`: focused contract, transaction, conflict, CLI, and metadata tests.

## 5. Streaming ingestion and conflicts

Discover `.csv` and `.tsv` inputs in deterministic filename order, without
recursion. Explicit file input can use either delimiter regardless of extension.
Use UTF-8 with optional BOM. Detect comma/tab from a bounded header sample;
prefer tab for `.tsv` only as a fallback. Validate the eleven mapped source
columns; the two ignored image-path columns are optional and never retained.
Header-only files are valid empty imports. Empty files, duplicate headers, an
empty input directory, and nonexistent inputs are errors. Report excluded
directory files as skipped, not rejected data rows.

Stream each row, validate it, resolve its video, and ensure Video, Person, Frame,
and FaceDetection records within the same explicit transaction. Hold lightweight
seen-record maps rather than complete CSV rows, and reuse database constraints
and lookups to identify conflicts. Keep video probe results cached per invocation,
including across files. Probe every referenced video once per invocation, even
when the Video row already exists, so metadata comparison is meaningful.

Compare existing records field-by-field. Identical entities and identical repeat
detections are reused; different title, path, metadata, frame association,
timestamp, bounding box, or score is a validation conflict. A different `frame_id`
for an occupied `(video_id, frame_number)` is also a conflict. Never use replace
or ignore operations that conceal conflicts. A failure rolls back all writes for
that file, including entities inserted before the bad row. Caches of persisted
entity IDs must not leak across rollback. A failed import cannot remove or modify
records committed by earlier files.

Validate nonempty IDs, nonnegative integer frame numbers, finite nonnegative
timestamps, finite bounding box values with `x1 < x2` and `y1 < y2`, and finite
detection scores in `[0, 1]`. Preserve nonempty identifiers, titles, filenames,
coordinates, and timestamps rather than stripping or rounding them. Do not add
an undocumented identifier regex, bounding-box clipping, or video-bound checks.
Match exact basename filenames; reject embedded path components. All references
must exist before the transaction commits; check foreign-key integrity.

## 6. Metadata

Use `ffprobe -v error -print_format json -show_format -show_streams <file>` via an
argument list, never a shell. Select the first non-attached-picture video stream.
Read duration from the selected stream, falling back to format duration; read FPS
from `avg_frame_rate`, falling back to `r_frame_rate`; read dimensions from that
stream; read creation time from stream tags, falling back to format tags.

Treat absent values, `N/A`, invalid fractions such as `0/0`, and non-finite values
as missing metadata. Keep them SQL NULL. Do not substitute filesystem dates,
current timestamps, guessed FPS, or frame-count-derived values. Missing ffprobe,
probe failure, invalid JSON, and absence of a usable video stream fail the row
with file/line context. Use a bounded subprocess timeout.

## 7. Results and verification

After each file, report rows read and committed detection rows inserted/skipped
or rejected. If a file rolls back, its committed entity insertion counts are zero
and all rows read in that failed attempt count as rejected; say explicitly that
processing stopped at the first error so unread rows are not counted. Also report
per-table inserted/skipped entity counts for successful files. Always print final
counts for all six tables after processing a valid database. Return nonzero if
any file was rejected. Do not populate Activity or Engagement during ingestion.

Use temporary databases and small CSV fixtures for tests. Test ffprobe parsing
with stubbed subprocess results; use one generated, temporary ffmpeg MP4 for a
real-probe integration test when ffmpeg is available. No OpenCV dependency is
needed. Test exact repeated imports, inconsistent duplicates, foreign keys,
late-row rollback, preservation of existing data, mixed-success directories,
both delimiters, missing metadata, non-finite values, and the documented CLI.

On 2026-10-24 the user's CSV contains 32,723 rows referencing 12 videos; only two
referenced videos are currently available. Full-file ingestion must therefore
fail atomically until all required originals arrive. Use synthetic fixtures and
an explicitly temporary filtered CSV for present-video checks, without altering
the supplied CSV. Future user data additions do not block implementation.

## 8. Parallel execution

First freeze shared contracts, paths, and test configuration. Then implement
schema/storage, CSV validation, and metadata extraction concurrently, with
exclusive source/test ownership. Integrate only after all three interfaces pass
their contract tests. Finish with CLI/reporting/documentation and end-to-end
verification. Do not run concurrent SQLite writers or concurrent dependency-lock
updates as part of task parallelization.
