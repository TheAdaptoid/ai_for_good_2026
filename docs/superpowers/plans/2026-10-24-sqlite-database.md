# Video Analysis SQLite Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` for delegated execution, or `executing-plans` for inline execution. Steps use checkbox (`- [ ]`) syntax for tracking. Parallel work is permitted only at the dependency boundaries below.

**Goal:** Create and populate a local SQLite database from validated face-detection CSV/TSV files and original video metadata, with atomic, repeatable imports and empty future-output tables.

**Architecture:** Extend the existing `backend/` uv project with a SQL schema, small standard-library modules, and two thin CLI scripts. Stream each CSV once within one explicit transaction, resolve original videos by exact filename, and insert or compare existing records without replacing conflicts. Freeze shared contracts first, develop three independent components in parallel, and join them for ingestion and CLI integration.

**Tech Stack:** Existing Python `>=3.13`, uv, standard-library `sqlite3`, `csv`, `subprocess`, `json`, `fractions`, `pathlib`, and `argparse`; local ffprobe; pytest as a development dependency. ffmpeg is used only by one optional real-video integration test.

## Global Constraints

- Approved design: `docs/superpowers/specs/2026-10-24-sqlite-database-design.md`.
- Source requirements: the user's SQLite Database Specification, sections 1–10, and the approved Approach A.
- “Use Python's built-in `sqlite3` module.”
- “Enable foreign key enforcement for every database connection.”
- “Use parameterized SQL queries.”
- “Read CSV files one row at a time to limit memory use.”
- “If validation fails, roll back the affected CSV import.”
- “Do not silently replace conflicting data.”
- “Do not invent missing metadata values.”
- “Do not populate this table during CSV ingestion.” applies to both Activity and Engagement.
- “Each score must be between 0 and 1.” applies to Engagement scores; do not constrain their sum.
- “Do not implement activity classification, engagement scoring, or frame extraction.”
- Preserve original IDs, timestamps, numeric bounding boxes, and detection scores. Never persist either ignored image-path field.
- Application files live in `backend/`; inputs and the default database live in repository-root `data/`.
- Resolve defaults independently of cwd; explicit relative CLI arguments resolve from the caller's cwd. Store video paths relative to the repository root.
- `--input` is required. From `backend/`, the input example is `--input ../data/csv/`; default DB and videos resolve to `../data/analysis.sqlite` and `../data/videos/`.
- Keep existing Python `>=3.13`; add no runtime Python dependencies.
- Root `.gitignore` already excludes `data/` and `docs/superpowers/*`. Keep those exclusions.
- Preserve the existing modification to `notebooks/activity_recognition.ipynb` and the user's untracked backend scaffold.
- Do not stage, commit, force-add, or update git configuration without an explicit user request. Use diff review checkpoints instead of automatic commits.
- Only documents are created during planning. Implementation, dependency installation, database creation, and actual-data import start after execution is selected.

---

## File Map

All paths below are repository-relative; Python commands use `backend/` as cwd unless stated otherwise.

| File | Owner task | Responsibility |
| --- | --- | --- |
| `backend/pyproject.toml`, `backend/uv.lock`, `backend/.gitignore` | 1 | pytest setup, lockfile, local Python cache exclusions |
| `backend/analysis_db/__init__.py` | 1 | Package marker; no import side effects |
| `backend/analysis_db/contracts.py` | 1 | Shared row, metadata, counter, result, and error types |
| `backend/analysis_db/paths.py` | 1 | Default locations and repository-relative path policy |
| `backend/tests/conftest.py`, `backend/tests/test_contracts_paths.py` | 1 | Shared typed-row fixture and foundation tests |
| `backend/db/schema.sql`, `backend/analysis_db/storage.py` | 2 | Schema, connections, conflict-aware writes, table counts |
| `backend/tests/test_storage.py` | 2 | SQL constraints, idempotent initialization, conflict behavior |
| `backend/analysis_db/csv_input.py`, `backend/tests/test_csv_input.py` | 3 | Input discovery, delimiter detection, typed streaming validation |
| `backend/analysis_db/video_metadata.py`, `backend/tests/test_video_metadata.py` | 4 | Video lookup and ffprobe parsing |
| `backend/analysis_db/ingestion.py`, `backend/tests/test_ingestion.py` | 5 | Transactions, caches, outcomes, file continuation |
| `backend/scripts/init_db.py`, `backend/scripts/ingest.py` | 6 | CLI adapters and human-readable summaries |
| `backend/tests/test_cli.py`, `backend/tests/test_real_video.py` | 6 | Subprocess CLI checks and real-probe integration |
| `backend/README.md` | 6 | Setup, commands, conflict policy, counts, verification |

Do not delete or repurpose the existing `backend/main.py`; the new entry points are the specified scripts.

## Dependency Graph and Parallel Execution Contract

```text
Task 1: shared contracts, paths, test setup
                 |
         +-------+--------+
         |       |        |
      Task 2   Task 3   Task 4      Run concurrently
      storage  CSV      metadata   Exclusive source/test ownership
         |       |        |
         +-------+--------+
                 |
          Task 5: ingestion
                 |
          Task 6: CLI, docs, acceptance
```

- Complete and review Task 1 before launching Tasks 2–4. Their interfaces below are frozen.
- Tasks 2–4 must not edit shared contracts, conftest, project config, lockfiles, or each other's files. Report a contract issue to the coordinator for one serialized amendment.
- Each worker writes only its listed files and runs its own focused tests in a temporary database or directory. No worker touches the user's actual database or input files.
- One coordinator owns dependency synchronization and the join. Run `uv sync` once before parallel tests; workers use the complete `uv run --no-sync pytest` commands in their tasks to avoid lockfile contention.
- Parallel implementation does not mean concurrent database ingestion. Directory imports remain sequential so per-file commit order and diagnostics are deterministic.
- After Tasks 2–4 pass independently, run the combined suite and check imports/signatures before Task 5.
- If delegated execution is selected, dispatch one worker for each of Tasks 2–4 in the same batch. Otherwise implement the same boundaries inline.

## Shared Contract Reference

Task 1 implements these types verbatim; later tasks consume them without renaming fields.

```python
from dataclasses import dataclass, field
from pathlib import Path

TABLES = ("Video", "Frame", "Person", "FaceDetection", "Activity", "Engagement")


class DataError(ValueError):
    """Invalid source values, conflicting records, or unavailable video metadata."""


class CsvImportError(Exception):
    def __init__(self, source: Path, line_number: int | None, reason: str):
        self.source = source
        self.line_number = line_number
        self.reason = reason
        location = str(source)
        if line_number is not None:
            location += f":{line_number}"
        super().__init__(f"{location}: {reason}")


@dataclass(frozen=True)
class DetectionRow:
    line_number: int
    video_title: str
    video_filename: str
    frame_number: int
    frame_id: str
    person_id: str
    source_time_seconds: float
    x1: float
    y1: float
    x2: float
    y2: float
    det_score: float


@dataclass(frozen=True)
class VideoMetadata:
    created_at: str | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None


def zero_counts() -> dict[str, int]:
    return dict.fromkeys(TABLES, 0)


@dataclass
class FileResult:
    source: Path
    committed: bool = False
    rows_read: int = 0
    rejected_rows: int = 0
    inserted: dict[str, int] = field(default_factory=zero_counts)
    skipped: dict[str, int] = field(default_factory=zero_counts)
    error: CsvImportError | None = None
```

Counts describe committed entities, not attempted writes. Successful-file FaceDetection inserted plus skipped equals rows read. Count each other entity once per successful file, even if referenced by many rows. On a failed file, inserted/skipped counts are zero and `rejected_rows == rows_read`; unread rows are not claimed as rejected.

---

### Task 1: Freeze Shared Contracts, Paths, and Test Setup

**Dependencies:** None. **Parallel group:** Foundation; complete before Tasks 2–4.

**Files:** The Task 1 files in the file map. Do not change application behavior elsewhere.

**Interfaces:**
- Produces all shared types above.
- `paths.REPOSITORY_ROOT: Path` is `Path(__file__).resolve().parents[2]`.
- `paths.DEFAULT_DB: Path`, `paths.DEFAULT_VIDEO_DIR: Path`, `paths.SCHEMA_PATH: Path` are absolute module-derived paths.
- `paths.repository_relative(path: Path, *, root: Path = REPOSITORY_ROOT) -> str` resolves a path, requires it inside root, and returns a POSIX relative path; otherwise raises `DataError`.
- Shared pytest fixture `make_row(**changes) -> DetectionRow` returns an immutable valid row with replacements.

- [ ] **Step 1: Configure tests and write the foundation tests.**

Use `uv add --dev pytest` to generate `uv.lock`, retaining the existing project metadata and Python requirement. Add pytest `pythonpath = ["."]` and `testpaths = ["tests"]` under `[tool.pytest.ini_options]`. Create `backend/.gitignore` with `.venv/`, `__pycache__/`, `.pytest_cache/`, and `*.py[cod]`. Verify the parent directory exists before generating new files.

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

```gitignore
.venv/
__pycache__/
.pytest_cache/
*.py[cod]
```

In `tests/test_contracts_paths.py`:

```python
from pathlib import Path
import pytest
from analysis_db.contracts import CsvImportError, DataError, FileResult, VideoMetadata
from analysis_db.paths import DEFAULT_DB, DEFAULT_VIDEO_DIR, repository_relative


def test_defaults_ignore_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert DEFAULT_DB.is_absolute()
    assert DEFAULT_VIDEO_DIR.is_absolute()
    assert DEFAULT_DB.parts[-2:] == ("data", "analysis.sqlite")
    assert DEFAULT_VIDEO_DIR.parts[-2:] == ("data", "videos")


def test_repository_path_policy(tmp_path):
    inside = tmp_path / "data" / "videos" / "clip.mp4"
    assert repository_relative(inside, root=tmp_path) == "data/videos/clip.mp4"
    with pytest.raises(DataError, match="repository"):
        repository_relative(tmp_path.parent / "outside.mp4", root=tmp_path)


def test_result_counters_are_independent():
    one, two = FileResult(Path("one.csv")), FileResult(Path("two.csv"))
    one.inserted["Video"] = 1
    assert two.inserted["Video"] == 0
    assert VideoMetadata().fps is None
    assert "one.csv:3: invalid score" == str(CsvImportError(Path("one.csv"), 3, "invalid score"))
```

- [ ] **Step 2: Run the red test.**

Run `uv run pytest tests/test_contracts_paths.py -q`. Expected: import/collection failure because `analysis_db` has not been created.

- [ ] **Step 3: Implement the contract reference and path helpers.**

Create `analysis_db/__init__.py` and `contracts.py` using the exact contract code above. Implement `paths.py`:

```python
from pathlib import Path
from .contracts import DataError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPOSITORY_ROOT / "data" / "analysis.sqlite"
DEFAULT_VIDEO_DIR = REPOSITORY_ROOT / "data" / "videos"
SCHEMA_PATH = REPOSITORY_ROOT / "backend" / "db" / "schema.sql"


def repository_relative(path: Path, *, root: Path = REPOSITORY_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DataError(f"video path must be inside repository: {path}") from exc
```

Create `tests/conftest.py`:

```python
from dataclasses import replace
import pytest
from analysis_db.contracts import DetectionRow


@pytest.fixture
def make_row():
    base = DetectionRow(2, "Clip", "clip.mp4", 0, "frame-0", "person-1",
                        0.0, 1.0, 2.0, 10.0, 20.0, 0.9)
    return lambda **changes: replace(base, **changes)
```

- [ ] **Step 4: Verify and freeze the foundation.**

Run `uv run pytest tests/test_contracts_paths.py -q`, then `uv sync --locked` and `uv lock --check`. Expect all tests and dependency checks to pass. Review only Task 1 changes and publish the exact signatures to Tasks 2–4. No automatic commit.

### Task 2: Schema and Conflict-Aware Storage

**Dependencies:** Task 1. **Parallel group:** A, concurrent with Tasks 3 and 4.

**Files:** `db/schema.sql`, `analysis_db/storage.py`, `tests/test_storage.py`.

**Interfaces:**
- Consumes `DetectionRow`, `VideoMetadata`, `DataError`, `TABLES`, `SCHEMA_PATH`.
- `connect_database(path: Path, *, must_exist: bool = False) -> sqlite3.Connection`: foreign keys ON; explicit transaction control (`isolation_level=None`); default tuple rows. `must_exist=True` opens SQLite URI `mode=rw` without creating a database.
- `initialize_database(path: Path) -> dict[str, int]`: create parent directory, apply schema idempotently, close connection, return table counts.
- `assert_schema(connection: sqlite3.Connection) -> None`: require all six tables; raise `DataError` instructing the caller to initialize if absent. Do not initialize during ingestion.
- `ensure_video(connection, row: DetectionRow, file_path: str, metadata: VideoMetadata) -> tuple[int, bool]` returns video ID and inserted flag.
- `ensure_person(connection, person_id: str) -> bool` returns inserted flag.
- `ensure_frame(connection, row: DetectionRow, video_id: int) -> bool` returns inserted flag.
- `ensure_detection(connection, row: DetectionRow) -> tuple[int, bool]` returns detection ID and inserted flag.
- `table_counts(connection) -> dict[str, int]`: keys exactly `TABLES` in that order.
- Insert helpers never commit, roll back, or probe videos. Conflicting rows raise `DataError` identifying the entity and field(s).

- [ ] **Step 1: Write storage tests covering transactions and constraints.**

Include these tests and direct parameterized constraint cases:

```python
import sqlite3
import pytest
from analysis_db.contracts import DataError, TABLES, VideoMetadata
from analysis_db.storage import (connect_database, initialize_database, ensure_video,
    ensure_person, ensure_frame, ensure_detection, table_counts)


def test_idempotent_init_and_conflicting_reimport(tmp_path, make_row):
    db = tmp_path / "analysis.sqlite"
    assert initialize_database(db) == dict.fromkeys(TABLES, 0)
    con = connect_database(db)
    try:
        assert con.execute("PRAGMA foreign_keys").fetchone() == (1,)
        con.execute("BEGIN")
        row = make_row()
        vid, inserted = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata(fps=24.0))
        assert inserted
        assert ensure_person(con, row.person_id)
        assert ensure_frame(con, row, vid)
        first_id, inserted = ensure_detection(con, row)
        assert inserted
        assert ensure_detection(con, row) == (first_id, False)
        with pytest.raises(DataError):
            ensure_detection(con, make_row(x2=99.0))
        con.commit()
    finally:
        con.close()
    assert initialize_database(db)["FaceDetection"] == 1


def test_foreign_key_enforced_without_csv_validator(tmp_path):
    db = tmp_path / "analysis.sqlite"
    initialize_database(db)
    con = connect_database(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO Frame VALUES (?, ?, ?, ?)", ("f", 999, 0, 0.0))
    finally:
        con.close()
```

Also test: required IDs cannot be NULL/blank; Frame alternate unique key rejects a second ID for one video/frame; mismatching title/path/metadata and frame timestamp/video association raise `DataError`; Person reuse; Detection duplicate values reuse the existing ID; invalid bounding boxes/scores fail SQL checks; Activity rejects a non-32-frame interval but permits `(-16, 15)`; Engagement rejects each out-of-range score but accepts `(0.8, 0.8, 0.8)`; required indexes exist; schema columns contain no image paths; connections with `must_exist=True` never create files.

- [ ] **Step 2: Run red tests.**

Run `uv run --no-sync pytest tests/test_storage.py -q`. Expect missing storage/schema failures.

- [ ] **Step 3: Create the complete SQL schema.**

```sql
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE IF NOT EXISTS Video (
    video_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL UNIQUE,
    created_at TEXT,
    duration_seconds REAL,
    fps REAL,
    width INTEGER,
    height INTEGER
);
CREATE TABLE IF NOT EXISTS Frame (
    frame_id TEXT NOT NULL PRIMARY KEY CHECK (length(trim(frame_id)) > 0),
    video_id INTEGER NOT NULL REFERENCES Video(video_id) ON DELETE CASCADE,
    frame_number INTEGER NOT NULL CHECK (typeof(frame_number) = 'integer' AND frame_number >= 0),
    source_time_seconds REAL NOT NULL CHECK (source_time_seconds >= 0),
    UNIQUE (video_id, frame_number)
);
CREATE TABLE IF NOT EXISTS Person (
    person_id TEXT NOT NULL PRIMARY KEY CHECK (length(trim(person_id)) > 0)
);
CREATE TABLE IF NOT EXISTS FaceDetection (
    detection_id INTEGER PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES Person(person_id),
    frame_id TEXT NOT NULL REFERENCES Frame(frame_id) ON DELETE CASCADE,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    x2 REAL NOT NULL,
    y2 REAL NOT NULL,
    det_score REAL NOT NULL CHECK (det_score BETWEEN 0 AND 1),
    CHECK (x1 < x2 AND y1 < y2),
    UNIQUE (frame_id, person_id)
);
CREATE TABLE IF NOT EXISTS Activity (
    activity_id INTEGER PRIMARY KEY,
    detection_id INTEGER NOT NULL UNIQUE REFERENCES FaceDetection(detection_id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    activity_label TEXT NOT NULL,
    confidence REAL NOT NULL,
    CHECK (end_frame = start_frame + 31)
);
CREATE TABLE IF NOT EXISTS Engagement (
    engagement_id INTEGER PRIMARY KEY,
    detection_id INTEGER NOT NULL UNIQUE REFERENCES FaceDetection(detection_id),
    positive_score REAL NOT NULL CHECK (positive_score BETWEEN 0 AND 1),
    neutral_score REAL NOT NULL CHECK (neutral_score BETWEEN 0 AND 1),
    negative_score REAL NOT NULL CHECK (negative_score BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS idx_frame_video_id ON Frame(video_id);
CREATE INDEX IF NOT EXISTS idx_detection_person_id ON FaceDetection(person_id);
CREATE INDEX IF NOT EXISTS idx_detection_frame_id ON FaceDetection(frame_id);
COMMIT;
```

- [ ] **Step 4: Implement connection lifecycle and insert-or-compare helpers.**

Use a URI generated from `path.resolve().as_uri() + "?mode=rw"` for existing-only connections. Set `PRAGMA foreign_keys = ON` immediately and check it returned 1. Close connections in `finally` blocks; the sqlite connection context manager alone does not close them. Apply schema only during initialization; roll back if executescript fails.

Each helper first selects by the entity's primary/unique key and compares exact parsed values. For Video select by `filename = ? OR file_path = ?`; any alternate-key collision is a conflict. For Frame select by `frame_id = ? OR (video_id = ? AND frame_number = ?)`; both identifiers must agree. Detect field mismatches, not just row existence. Compare metadata fields including NULL; do not use float tolerance or silently update an existing record.

Detection insertion/lookup pattern:

```python
expected = (row.x1, row.y1, row.x2, row.y2, row.det_score)
existing = connection.execute(
    "SELECT detection_id, x1, y1, x2, y2, det_score FROM FaceDetection "
    "WHERE frame_id = ? AND person_id = ?",
    (row.frame_id, row.person_id),
).fetchone()
if existing is not None:
    if existing[1:] != expected:
        raise DataError(f"conflicting FaceDetection for {row.frame_id!r}, {row.person_id!r}")
    return existing[0], False
cursor = connection.execute(
    "INSERT INTO FaceDetection (person_id, frame_id, x1, y1, x2, y2, det_score) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)",
    (row.person_id, row.frame_id, *expected),
)
return cursor.lastrowid, True
```

Use fixed, internal table names from `TABLES` for count-query identifiers; parameterize all source values. No `INSERT OR IGNORE`, `INSERT OR REPLACE`, or implicit commits in insertion helpers.

- [ ] **Step 5: Verify the storage branch.**

Run `uv run --no-sync pytest tests/test_storage.py -q`. Confirm a caller can `BEGIN`, call all helpers, `ROLLBACK`, and observe zero rows. Review this task's files; report the public signatures and passing result to the coordinator.

### Task 3: Streaming CSV/TSV Input and Typed Validation

**Dependencies:** Task 1. **Parallel group:** A, concurrent with Tasks 2 and 4.

**Files:** `analysis_db/csv_input.py`, `tests/test_csv_input.py`.

**Interfaces:**
- Consumes `DetectionRow`, `DataError`, `CsvImportError`.
- `discover_inputs(path: Path) -> tuple[list[Path], list[Path]]`: sorted selected files and ignored directory entries. Directory selection is nonrecursive `.csv`/`.tsv` case-insensitively; explicit file input is permitted independent of extension. Missing input or no selected files raises `DataError`.
- `iter_rows(source: Path) -> Iterator[DetectionRow]`: opens/closes the file inside a generator, validates the header, then parses one record at a time. Raises `CsvImportError` containing the source and physical starting line of the invalid record.
- `validate_row(values: Mapping[str, str], *, source: Path, line_number: int) -> DetectionRow`: typed validation; all errors are source-located.
- Constant `REQUIRED_COLUMNS` is the eleven mapped columns; image-path columns are optional, ignored, and absent from `DetectionRow`.

- [ ] **Step 1: Write parser tests.**

In `tests/test_csv_input.py`, define a task-local fixture writer:

```python
import csv
import pytest
from analysis_db.contracts import CsvImportError
from analysis_db.csv_input import iter_rows

HEADERS = ["video_title", "video_filename", "frame_number", "frame_id", "person_id",
           "source_time_seconds", "face_bbox_x1", "face_bbox_y1", "face_bbox_x2",
           "face_bbox_y2", "det_score"]
VALID = ["Clip", "clip.mp4", "0", "frame-0", "person-1", "0", "1", "2", "10", "20", "0.9"]


@pytest.mark.parametrize("delimiter,suffix", [(",", ".csv"), ("\t", ".csv"), ("\t", ".tsv")])
def test_delimiters_and_preserved_values(tmp_path, delimiter, suffix):
    path = tmp_path / ("source" + suffix)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(HEADERS)
        writer.writerow(VALID)
    row, = iter_rows(path)
    assert row.frame_id == "frame-0"
    assert row.person_id == "person-1"
    assert row.x1 == 1.0 and row.det_score == 0.9 and row.line_number == 2


@pytest.mark.parametrize("column,value", [
    ("frame_id", " "), ("person_id", ""), ("frame_number", "-1"),
    ("frame_number", "1.5"), ("frame_number", "1.0"),
    ("source_time_seconds", "-0.1"), ("source_time_seconds", "nan"),
    ("face_bbox_x2", "1"), ("face_bbox_y2", "2"), ("face_bbox_x1", "inf"),
    ("det_score", "1.1"), ("det_score", "-0.1"), ("det_score", "NaN"),
])
def test_invalid_value_has_source_and_line(tmp_path, column, value):
    path = tmp_path / "bad.csv"
    values = dict(zip(HEADERS, VALID))
    values[column] = value
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, HEADERS)
        writer.writeheader()
        writer.writerow(values)
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert caught.value.line_number == 2
    assert column in caught.value.reason
```

Add tests for missing required headers; duplicate headers; extra/missing record cells; quoted filenames with commas; optional ignored fields; header-only success; zero-byte failure; malformed quoting; CRLF/BOM; original nonblank IDs containing spaces retained; nonnegative frame integer above SQLite's signed 64-bit range rejected with a frame-number reason; one valid row yielded before a later invalid row is reached; deterministic discovery and ignored files. Do not read entire input to test streaming.

- [ ] **Step 2: Run red tests.**

Run `uv run --no-sync pytest tests/test_csv_input.py -q`. Expect missing parser failures.

- [ ] **Step 3: Implement header detection, streaming, and validation.**

Read a bounded header sample (64 KiB maximum), then seek back to the start. Sniff only comma/tab; on ambiguous sniffing use tab for `.tsv`, comma otherwise. Use `csv.reader(..., strict=True)` so record length can be checked before building a mapping. Track the starting physical line with `reader.line_num + 1` before each `next(reader)`. Blank physical records may be skipped. Never use `list(reader)`, `.read()` without a limit, or retain image-path values after row parsing. Catch decoding, I/O, and `csv.Error` exceptions and attach source/line.

Validation core:

```python
import math
import re


def finite_number(values, column):
    try:
        number = float(values[column])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{column} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{column} must be finite")
    return number


# Inside validate_row, catch ValueError as exc and raise
# CsvImportError(source, line_number, str(exc)) from exc.
raw_number = values["frame_number"]
if not re.fullmatch(r"[0-9]+", raw_number) or not 0 <= int(raw_number) <= 2**63 - 1:
    raise ValueError("frame_number must be a nonnegative SQLite integer")
frame_number = int(raw_number)
for name in ("frame_id", "person_id", "video_filename"):
    if not values[name].strip():
        raise ValueError(f"{name} must be nonempty")
timestamp = finite_number(values, "source_time_seconds")
if timestamp < 0:
    raise ValueError("source_time_seconds must be nonnegative")
x1, y1, x2, y2 = (finite_number(values, name) for name in (
    "face_bbox_x1", "face_bbox_y1", "face_bbox_x2", "face_bbox_y2"))
if not x1 < x2:
    raise ValueError("face_bbox_x1 must be less than face_bbox_x2")
if not y1 < y2:
    raise ValueError("face_bbox_y1 must be less than face_bbox_y2")
score = finite_number(values, "det_score")
if not 0 <= score <= 1:
    raise ValueError("det_score must be between 0 and 1")
```

Construct `DetectionRow` with the mapped source fields, preserving all nonempty strings exactly and not rounding floats. A title can be an empty string because the specification requires NOT NULL, not nonempty. Validate basename filenames in Task 4 rather than resolving them here. Permit additional unused source columns.

- [ ] **Step 4: Verify the CSV branch.**

Run `uv run --no-sync pytest tests/test_csv_input.py -q`. Review that no whole-file materialization, video probing, database access, or image-path persistence has entered this module. Report the public signatures and passing result.

### Task 4: Exact Video Lookup and ffprobe Metadata

**Dependencies:** Task 1. **Parallel group:** A, concurrent with Tasks 2 and 3.

**Files:** `analysis_db/video_metadata.py`, `tests/test_video_metadata.py`.

**Interfaces:**
- Consumes `VideoMetadata`, `DataError`.
- `resolve_video(filename: str, video_dir: Path) -> Path`: exact basename lookup, resolved existing file; reject `/`, `\\`, `.` and `..` names; no recursive or fuzzy lookup.
- `parse_probe(payload: Mapping[str, object]) -> VideoMetadata`: pure JSON-object parsing.
- `probe_video(path: Path) -> VideoMetadata`: ffprobe subprocess and parse; cache belongs to Task 5, not this module.
- Every expected probe/lookup failure raises `DataError`; ingestion adds source/line context.

- [ ] **Step 1: Write deterministic metadata and subprocess tests.**

```python
import json
import subprocess
import pytest
from analysis_db.contracts import DataError, VideoMetadata
from analysis_db.video_metadata import parse_probe, probe_video, resolve_video


def test_metadata_uses_video_stream_and_rational_fps():
    payload = {"streams": [
        {"codec_type": "audio", "duration": "999"},
        {"codec_type": "video", "duration": "2.5", "avg_frame_rate": "30000/1001",
         "width": 1920, "height": 1080, "tags": {"creation_time": "2025-01-01T12:00:00Z"}},
    ], "format": {"duration": "3.0"}}
    result = parse_probe(payload)
    assert result.duration_seconds == 2.5
    assert result.fps == pytest.approx(30000 / 1001)
    assert (result.width, result.height) == (1920, 1080)
    assert result.created_at == "2025-01-01T12:00:00Z"


def test_absent_metadata_stays_absent():
    assert parse_probe({"streams": [{"codec_type": "video"}]}) == VideoMetadata()


def test_probe_argument_list_preserves_filename(tmp_path, monkeypatch):
    path = tmp_path / "clip with spaces.mp4"
    path.touch()
    seen = {}
    def fake_run(args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        return subprocess.CompletedProcess(args, 0, json.dumps({"streams": [{"codec_type": "video"}]}), "")
    monkeypatch.setattr("analysis_db.video_metadata.subprocess.run", fake_run)
    assert probe_video(path) == VideoMetadata()
    assert seen["args"][-1] == str(path)
    assert seen["args"][0] == "ffprobe"
    assert seen["kwargs"].get("shell", False) is False
    assert seen["kwargs"]["timeout"] == 60
```

Add tests for missing file; different case; traversal; audio-only payload; attached cover image before the real stream; `0/0` average FPS falling back to `r_frame_rate`; format duration/creation fallback; missing values, `N/A`, NaN, Infinity, zero/negative FPS and invalid dimensions becoming NULL; ffprobe missing executable, timeout, nonzero status, non-object JSON, and invalid JSON becoming `DataError`. Do not patch ffprobe into Task 2 or Task 3 tests.

- [ ] **Step 2: Run red tests.**

Run `uv run --no-sync pytest tests/test_video_metadata.py -q`. Expect missing module failures.

- [ ] **Step 3: Implement lookup and pure parsing.**

Use `Fraction(str(value))` for rational FPS, convert to float, and accept only positive finite results. For duration accept finite nonnegative values. For width/height accept positive integer values, rejecting booleans and fractional values. Select the first `codec_type == "video"` stream without `disposition.attached_pic == 1`. Absent `streams` or no usable video stream is a `DataError`. A stream with no optional metadata is still usable.

```python
def resolve_video(filename, video_dir):
    if not filename.strip() or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise DataError(f"video_filename must be a basename: {filename!r}")
    path = (video_dir / filename).resolve()
    if not path.is_file():
        raise DataError(f"video file does not exist: {filename!r} in {video_dir}")
    return path
```

Parse creation time only from nonempty stream/format `tags.creation_time`, preserving the source text. Do not synthesize a timestamp or use file modification time. Treat malformed optional fields as unavailable, but malformed overall payloads as probe errors.

- [ ] **Step 4: Implement the subprocess adapter.**

```python
completed = subprocess.run(
    ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
    check=True, capture_output=True, text=True, timeout=60,
)
```

Catch `OSError`, `subprocess.TimeoutExpired`, `subprocess.CalledProcessError`, JSON decoding errors, and invalid JSON shape. Include the video filename and useful stderr in `DataError`. No network requests, shell command strings, or frame decoding.

- [ ] **Step 5: Verify the metadata branch and perform the parallel join.**

Worker command: `uv run --no-sync pytest tests/test_video_metadata.py -q`.

After Tasks 2 and 3 also finish, coordinator command: `uv run --no-sync pytest tests/test_contracts_paths.py tests/test_storage.py tests/test_csv_input.py tests/test_video_metadata.py -q`. Confirm all interfaces still match before starting Task 5. Review each task's diff without touching unrelated user files.

### Task 5: Atomic Streaming Ingestion and Committed Counts

**Dependencies:** Tasks 2–4, successful combined test run. **Parallel group:** Integration; sequential.

**Files:** `analysis_db/ingestion.py`, `tests/test_ingestion.py`.

**Interfaces:**
- Consumes all frozen storage, CSV, metadata, and path interfaces.
- `ingest_file(connection: sqlite3.Connection, source: Path, video_dir: Path, *, repository_root: Path, metadata_cache: dict[Path, VideoMetadata]) -> FileResult` handles one complete transaction and returns success or source-located failure.
- `ingest_files(connection: sqlite3.Connection, sources: Iterable[Path], video_dir: Path, *, repository_root: Path = REPOSITORY_ROOT) -> list[FileResult]` runs schema validation, creates one per-invocation metadata cache, and processes files sequentially without stopping on a file failure.
- Metadata-cache keys are resolved video paths; cache values have no database IDs. Entity caches are reset per file and discarded on rollback.

- [ ] **Step 1: Write an end-to-end transaction test with task-local CSV helper.**

In `tests/test_ingestion.py`, define the task-local CSV helper below. Do not depend on another test module.

```python
import csv


def write_rows(path, rows):
    headers = ["video_title", "video_filename", "frame_number", "frame_id", "person_id",
               "source_time_seconds", "face_bbox_x1", "face_bbox_y1", "face_bbox_x2",
               "face_bbox_y2", "det_score"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "video_title": row.video_title, "video_filename": row.video_filename,
                "frame_number": row.frame_number, "frame_id": row.frame_id,
                "person_id": row.person_id, "source_time_seconds": row.source_time_seconds,
                "face_bbox_x1": row.x1, "face_bbox_y1": row.y1,
                "face_bbox_x2": row.x2, "face_bbox_y2": row.y2, "det_score": row.det_score,
            })
```

```python
from unittest.mock import Mock
from analysis_db.contracts import TABLES, VideoMetadata
from analysis_db.ingestion import ingest_files
from analysis_db.storage import connect_database, initialize_database, table_counts


def test_import_then_reimport_and_late_conflict(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "data" / "videos"
    videos.mkdir(parents=True)
    (videos / "clip.mp4").touch()
    good, bad = tmp_path / "good.csv", tmp_path / "bad.csv"
    write_rows(good, [make_row(), make_row(frame_number=1, frame_id="frame-1", source_time_seconds=0.04)])
    write_rows(bad, [make_row(person_id="new-person"), make_row(x2=999.0)])
    probe = Mock(return_value=VideoMetadata(duration_seconds=1.0, fps=24.0, width=64, height=64))
    monkeypatch.setattr("analysis_db.ingestion.probe_video", probe)
    db = tmp_path / "analysis.sqlite"
    initialize_database(db)
    con = connect_database(db, must_exist=True)
    try:
        first, repeat, rejected = ingest_files(con, [good, good, bad], videos, repository_root=tmp_path)
        assert first.committed and first.inserted["FaceDetection"] == 2
        assert repeat.committed and repeat.inserted["FaceDetection"] == 0
        assert repeat.skipped["FaceDetection"] == 2
        assert not rejected.committed and rejected.error.line_number == 3
        assert rejected.inserted == dict.fromkeys(TABLES, 0)
        assert rejected.rejected_rows == 2
        assert table_counts(con) == {"Video": 1, "Frame": 2, "Person": 1,
                                     "FaceDetection": 2, "Activity": 0, "Engagement": 0}
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert probe.call_count == 1
    finally:
        con.close()
```

Add meaningful cases: identical duplicate row; conflicting duplicate within an initially empty DB; two persons in one frame; same person across videos; frame-ID mismatch/alternate unique key collision; existing Video title/metadata conflict; a new video's writes rolled back after a later missing video; invalid numeric late row; failure followed by a successful file referencing the same video (no stale ID cache); ignored image paths absent from persistence; header-only file; all Activity/Engagement rows untouched; incomplete CSV leaves a fresh DB empty; every successful Video stores a relative path resolving to a real file.

- [ ] **Step 2: Run red tests.**

Run `uv run --no-sync pytest tests/test_ingestion.py -q`. Expect missing ingestion-module failures.

- [ ] **Step 3: Implement the per-file transaction.**

Initialize the per-file caches and nested row writer before the transaction loop:

```python
seen_videos: dict[str, tuple[str, str, VideoMetadata, int]] = {}
seen_persons: set[str] = set()
seen_frames: dict[str, tuple[int, int, float]] = {}
seen_detections: dict[tuple[str, str], tuple[float, float, float, float, float]] = {}


def count_entity(table, inserted):
    (result.inserted if inserted else result.skipped)[table] += 1


def store_row(row):
    if row.video_filename not in seen_videos:
        path = resolve_video(row.video_filename, video_dir)
        stored_path = repository_relative(path, root=repository_root)
        if path not in metadata_cache:
            metadata_cache[path] = probe_video(path)
        metadata = metadata_cache[path]
        video_id, inserted = ensure_video(connection, row, stored_path, metadata)
        count_entity("Video", inserted)
        seen_videos[row.video_filename] = (row.video_title, stored_path, metadata, video_id)
    else:
        title, stored_path, metadata, video_id = seen_videos[row.video_filename]
        if row.video_title != title:
            raise DataError(f"conflicting Video.title for {row.video_filename!r}")

    if row.person_id not in seen_persons:
        count_entity("Person", ensure_person(connection, row.person_id))
        seen_persons.add(row.person_id)

    frame_signature = (video_id, row.frame_number, row.source_time_seconds)
    if row.frame_id in seen_frames:
        if seen_frames[row.frame_id] != frame_signature:
            raise DataError(f"conflicting Frame for {row.frame_id!r}")
    else:
        count_entity("Frame", ensure_frame(connection, row, video_id))
        seen_frames[row.frame_id] = frame_signature

    key = (row.frame_id, row.person_id)
    signature = (row.x1, row.y1, row.x2, row.y2, row.det_score)
    if key in seen_detections:
        if seen_detections[key] != signature:
            raise DataError(f"conflicting FaceDetection for {key!r}")
        count_entity("FaceDetection", False)
    else:
        detection_id, inserted = ensure_detection(connection, row)
        count_entity("FaceDetection", inserted)
        seen_detections[key] = signature
```

Use this transaction loop inside `ingest_file`, with the shared imports and nested helpers above. Expected parser failures include their own source/line; errors from storage or video probing are attributed to the current row.

```python
result = FileResult(source)
current_line = None
if connection.in_transaction:
    raise DataError("ingestion requires an idle database connection")
started = False
try:
    connection.execute("BEGIN")
    started = True
    for row in iter_rows(source):
        result.rows_read += 1
        current_line = row.line_number
        store_row(row)
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise DataError("foreign key validation failed")
    connection.commit()
    result.committed = True
except (CsvImportError, DataError, sqlite3.Error, OSError) as exc:
    if started:
        connection.rollback()
    if isinstance(exc, CsvImportError):
        # iter_rows validates before yielding: its invalid data row was not
        # counted by the loop. Header errors have line 1 and add no data row.
        if exc.line_number is not None and exc.line_number > 1:
            result.rows_read += 1
        result.error = exc
    else:
        result.error = CsvImportError(source, current_line, str(exc))
    result.rejected_rows = result.rows_read
    result.inserted = zero_counts()
    result.skipped = zero_counts()
finally:
    if started and connection.in_transaction:
        connection.rollback()
return result
```

Keep `BEGIN` failures source-located too: if the initial `BEGIN` raises a database error, return a failed `FileResult` without claiming any rows and do not roll back a transaction owned by some other caller. Require idle connections at the public boundary; reject an already-active caller transaction with `DataError` before starting imports.

For a first reference, `resolve_video`, `repository_relative`, and cached `probe_video` supply Video values; call the storage helper and increment inserted or skipped once for that entity. On later references compare the title/path/metadata signature and reuse the video ID. For Frames compare `(video_id, frame_number, source_time_seconds)`; alternate-frame-number uniqueness remains enforced by the database helper. For detection pairs compare all five numeric fields; an identical repeat increments FaceDetection skipped for that row, and a different tuple raises `DataError`. Never let a cache suppress conflict checks. Person reuse within the file does not increment entity counts a second time.

Files are parsed lazily, with insertions happening inside the transaction as rows arrive; do not accumulate rows and insert them only after EOF. Memory grows with distinct signatures, not ignored text/image columns. Do not pre-scan a file in a second pass.

- [ ] **Step 4: Implement directory-level orchestration.**

```python
def ingest_files(connection, sources, video_dir, *, repository_root=REPOSITORY_ROOT):
    if connection.in_transaction:
        raise DataError("ingestion requires an idle database connection")
    assert_schema(connection)
    repository_relative(video_dir, root=repository_root)
    cache = {}
    return [ingest_file(connection, source, video_dir,
                        repository_root=repository_root, metadata_cache=cache)
            for source in sources]
```

Do not retain entity IDs across files. Resolve and validate the configured video directory's repository-relative policy even if a header-only input references no videos. No writes to Activity or Engagement.

- [ ] **Step 5: Verify atomicity and the integration suite.**

Run `uv run --no-sync pytest tests/test_ingestion.py -q`, then `uv run --no-sync pytest -q`. Inspect the late-conflict test: counts must show no new person/detection after rollback, and the original committed detection ID/value must remain intact. Review this task's changes before CLI work.

### Task 6: CLI, Documentation, and Acceptance Verification

**Dependencies:** Task 5. **Parallel group:** Final integration; sequential in this plan to keep CLI and documentation synchronized.

**Files:** `scripts/init_db.py`, `scripts/ingest.py`, `tests/test_cli.py`, `tests/test_real_video.py`, `README.md`.

**Interfaces:**
- Both scripts expose `main(argv: list[str] | None = None) -> int` and end with `raise SystemExit(main())`.
- Init CLI: optional `--db` only; default from `paths.DEFAULT_DB`.
- Ingestion CLI: required `--input`, optional `--db` and `--video-dir`; return 0 for all-success, 1 for rejected files/runtime failure, 2 for argparse usage errors.
- Final counts cover all six table names even if some input files failed.

- [ ] **Step 1: Write real subprocess CLI tests.**

Tests should build a temporary database and data directory inside a pytest temporary directory created under the repository (not the user's `data/`), because `--video-dir` must remain inside the repository. Clean it via `TemporaryDirectory(dir=REPOSITORY_ROOT)` and never store fixture media in git. Use `sys.executable` for child Python calls; no nested uv processes.

```python
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_init_cli_from_unrelated_cwd(tmp_path):
    db = tmp_path / "nested" / "test.sqlite"
    command = [sys.executable, str(BACKEND / "scripts" / "init_db.py"), "--db", str(db)]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert db.is_file()
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert "Video" in second.stdout and "Engagement" in second.stdout
```

Also test argparse missing `--input`; ingestion against a missing/uninitialized DB without creating or initializing it; error output containing filename/line/reason; a rejected file followed by successful header-only input; directory ignored-file report; sorted processing; nonzero exit after mixed results; exactly six final table counts; no raw traceback for expected errors. For subprocess ingestion without ffprobe, use invalid input or header-only files; verify successful detection ingestion using the real-video case below rather than mocking across a process boundary.

- [ ] **Step 2: Run red CLI tests.**

Run `uv run --no-sync pytest tests/test_cli.py -q`. Expect missing-script failures.

- [ ] **Step 3: Implement thin CLI adapters and reporting.**

Each script bootstraps the backend package from its own location before importing it:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

Use argparse `type=Path`. Init calls `initialize_database` and reports all counts. Ingest discovers files, opens existing DB with `connect_database(args.db, must_exist=True)`, calls `ingest_files`, reports outcomes, prints final `table_counts`, and closes in a `finally` block. Catch expected `DataError`, `OSError`, `sqlite3.Error`, and top-level input failures; print concise reasons to stderr without hiding programming exceptions.

Use an unambiguous summary shape:

```text
source.csv: committed; rows=12 inserted=10 skipped=2 rejected=0
  Video: inserted=1 skipped=0
  Frame: inserted=6 skipped=0
  Person: inserted=3 skipped=0
  FaceDetection: inserted=10 skipped=2
bad.csv: rolled back; rows_read=3 rejected=3; stopped at first error
bad.csv:4: conflicting FaceDetection for 'frame-0', 'person-1'
Table counts:
  Video: 1
  Frame: 6
  Person: 3
  FaceDetection: 10
  Activity: 0
  Engagement: 0
```

The first line's inserted/skipped numbers are detection-row outcomes, not a sum over entities. Failed-file per-table committed counts are zero. Do not claim the entire remaining file was scanned or count unread rows as rejected.

- [ ] **Step 4: Add one actual video/probe/CLI integration test.**

In `tests/test_real_video.py`, skip only this test if `shutil.which("ffmpeg")` or `shutil.which("ffprobe")` is absent. Use a `TemporaryDirectory(dir=REPOSITORY_ROOT)`; create `data/videos/clip.mp4`, fixture CSV, and temporary DB inside it. Generate media with:

```python
subprocess.run([
    "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x48:r=24",
    "-t", "1", "-an", "-c:v", "mpeg4", str(video_path),
], check=True, capture_output=True, timeout=30)
```

Initialize using the script; ingest a CSV containing two frames and two people; repeat ingestion. Inspect the resulting DB through the application's FK-enabled connection: one Video, two Frames, two Persons, expected Detection count, stable generated detection IDs after repeat, zero Activity/Engagement, FPS approximately 24, width 64, height 48, duration approximately one second, and a stored relative path that resolves from the repository root to the fixture file. No extracted images should exist. Keep pure parser/transaction tests running even if this external-tool test skips.

- [ ] **Step 5: Write the backend README.**

Include these exact setup/operation commands (cwd `backend/`):

```bash
uv sync --locked
uv run python scripts/init_db.py
uv run python scripts/ingest.py --input ../data/csv/
uv run python scripts/ingest.py --input "../data/csv/activity_frame_person_map - activity_frame_person_map.csv"
uv run python scripts/init_db.py --db ../data/custom.sqlite
uv run python scripts/ingest.py --input ../data/csv/ --db ../data/custom.sqlite --video-dir ../data/videos/
uv run pytest -q
```

Document ffprobe as a system prerequisite, ffmpeg as an optional test prerequisite, six-table purpose, empty future outputs, exact filename matching, repository-relative stored paths, comma/tab support, file-level rollback, original identifiers, identical-repeat skip behavior, conflicting-repeat rejection, ignored image fields, exit codes, all-table counts, and no model/frame processing. State that defaults are module-derived while explicit relative arguments use cwd. Explain that init is idempotent creation, not schema migration.

The supplied CSV currently references 12 originals; only two are present as of planning. Explain that additional originals can be added without code changes, but one missing video invalidates the whole CSV. Do not alter or split the user's original CSV as part of normal ingestion.

- [ ] **Step 6: Verify acceptance with fixtures, then optional available user data.**

Run `uv run pytest -q`, `uv lock --check`, and both CLI `--help` commands. Confirm whether the real ffmpeg test actually ran or skipped and report that accurately. Run `git diff --check` for tracked edits and review all newly created files separately because untracked backend files do not appear in a normal diff.

For a local-data check, use a temporary DB and temporary filtered CSV containing only rows whose exact filenames currently exist in `data/videos/`; derive that file by streaming the supplied CSV with `csv.DictReader/DictWriter`. Keep the original unchanged. Initialize, ingest twice, compare counts and IDs, and ensure metadata matches ffprobe. Do not populate the default database during this check. If all 12 referenced originals have arrived by execution time, a temporary full-import check can replace the filtered check.

Record the tests/commands and observed result. If missing files remain, explicitly distinguish verified fixture/available-video ingestion from the unavailable full dataset; do not claim full-file acceptance. End with a concise changed-file and verification summary, without committing.

---

## Acceptance Coverage and Review Checklist

| Spec requirement / acceptance criterion | Owning task / evidence |
| --- | --- |
| Six exact tables; idempotent initialization | Task 2 schema/init tests; Task 6 CLI |
| CSV file or directory; comma/tab; streaming | Task 3 parser/discovery tests; Task 5 pipeline |
| Exact original-file match and repository-relative paths | Tasks 1, 4, 5; Task 6 real-video test |
| Available video metadata, NULL for absent values | Task 4 parsing/probe tests; Task 6 real-video test |
| Original person/frame identifiers | Task 3 typed rows; Task 5 SQL assertions |
| Valid FK relationships on every app connection | Task 2 connection/constraint tests; Task 5 integrity check |
| Original bounding boxes and scores | Tasks 3 and 5, including numeric equality checks |
| No duplicates or silent conflict replacement | Tasks 2 and 5 repeated/conflicting imports |
| Per-file transaction rollback and continuation | Task 5 late-failure and mixed-file tests |
| Empty Activity and Engagement after ingestion | Tasks 5 and 6 |
| 32-frame inclusive Activity window; future boundary handling | Task 2 CHECK permits negative start; no inference code |
| Engagement score bounds without sum constraint | Task 2 direct SQL tests |
| No image data, extracted paths, crops, models, or dashboards | Schema inspection; Task 3 row contract; final source review |
| Parameterized SQL and requested indexes | Task 2 code/DDL review and index tests |
| Initialization separate from ingestion | Task 2 API; Task 6 missing-schema CLI test |
| Inserted/skipped/rejected summaries; all six final counts | Tasks 5 and 6 |
| Local operation; uv; no extra runtime dependencies | Tasks 1 and 6; pyproject/lock review |

Before execution handoff, inspect this document for undefined interfaces, inconsistent names, missing requirement ownership, and shared-file collisions. The only parallel window is Tasks 2–4; each owns disjoint files and depends only on Task 1.

## Execution Handoff

1. **Subagent-driven:** Use the prescribed implementation/review workflow, with Tasks 2–4 dispatched concurrently after Task 1. Keep integration and dependency-file edits under one coordinator.
2. **Inline:** Use `executing-plans`, follow the same dependency order, and pause at foundation, parallel-component join, and final verification checkpoints.

Neither option starts until the user selects execution. The plan and approved design remain local ignored documentation under the existing repository policy.
