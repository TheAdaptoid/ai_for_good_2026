# Video Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrieve exact RGB video frames, unresized face crops, and padded 32-frame clips from existing SQLite records, with tests and a validation notebook.

**Architecture:** Use the existing SQLite schema/path constants and a read-only extension to the connection helper. PyAV sequentially decodes presentation-order frames in one operation per request; only requested RGB arrays remain in memory. Parallel workers own separate core, test, and notebook files.

**Tech Stack:** Python >=3.13, SQLite, PyAV, NumPy, pytest, JupyterLab, Matplotlib, uv.

## Global Constraints

- Frame numbers are zero-based original-video indices.
- Image arrays are RGB uint8; clips have shape `(32, height, width, 3)`.
- Clip window is `[f - 16, f + 15]`, inclusive, with edge repetition.
- No database record changes, extracted-image writes, resizing, persistent caches, models, multiprocessing, or GPUs.
- Preserve string person/frame IDs and existing ingestion behavior.
- Default paths come from `analysis_db.paths`; explicit relative database paths use the working directory.
- Standard tests use synthetic videos and a temporary database only.
- Do not commit; the user has not requested commits. Preserve existing unrelated notebook edits.

## Shared interfaces and ownership

```python
@dataclass(frozen=True)
class DetectionInfo:
    detection_id: int
    person_id: str
    video_id: int
    frame_id: str
    frame_number: int
    source_time_seconds: float
    bbox: tuple[float, float, float, float]

class VideoRetriever:
    def __init__(self, db_path: str | Path | None = None): ...
    db_path: Path
    def get_frame(self, video_id: int, frame_number: int) -> np.ndarray: ...
    def get_face(self, detection_id: int) -> np.ndarray: ...
    def get_clip(self, detection_id: int) -> np.ndarray: ...
    def get_detection_info(self, detection_id: int) -> DetectionInfo: ...

def connect_database(path: Path, *, must_exist: bool = False,
                     read_only: bool = False) -> sqlite3.Connection: ...
```

`video_retrieval.__init__` exports both public classes. Errors: LookupError for
missing record, FileNotFoundError for absent video, ValueError for invalid frame
or crop, RuntimeError for decoding failure. `db_path` exposes the resolved path
for read-only notebook discovery queries.

## Execution graph

Coordinator prepares dependency installation and read-only helper. Immediately
dispatch three workers concurrently: tests (red first), retrieval (wait for red
confirmation before implementation), and notebook. Integration starts after all
three finish. Workers must not run uv dependency mutations or edit shared files.

### Task 1: Environment and read-only access — coordinator

**Files:** modify `backend/analysis_db/storage.py`, `backend/pyproject.toml`,
`backend/uv.lock`; extend `backend/tests/test_storage.py`.

**Interfaces:** consumes existing helper; produces `read_only=True` option.

- [ ] Add a regression test that initializes a temporary database, opens with
  `read_only=True`, verifies a SELECT works, and verifies
  `connection.execute("INSERT INTO Person VALUES ('blocked')")` raises
  `sqlite3.OperationalError` matching `readonly`. Close with try/finally.
- [ ] Run `uv run pytest tests/test_storage.py -q`; verify the new test fails
  because the keyword is unsupported.
- [ ] Set `mode = "ro" if read_only else "rw"`; use the URI branch when
  `must_exist or read_only`. Keep PRAGMA enforcement and current defaults.
- [ ] Run `uv add av numpy` and `uv add --group dev jupyterlab matplotlib`.
- [ ] Run `uv run pytest tests/test_storage.py -q`; require success.

### Task 2: Synthetic acceptance tests — worker A

**Files:** create `backend/tests/test_video_retrieval.py` only.

**Interfaces:** consumes shared public API, `initialize_database`, PyAV encoder.

- [ ] Write fixture creating a 48-frame 64x48 lossless FFV1 video with distinctive
  red/green/blue regions and frame-dependent colors. Save only synthetic original
  video into pytest tmp_path. Initialize existing schema and insert Video,
  Person, Frame, FaceDetection records for beginning, middle, and ending indices.
  Absolute temp video paths work with repository-root path joining; additionally
  test a repository-relative path by monkeypatching the retrieval root constant.
- [ ] Add tests checking RGB dtype/shape and expected images (allclose with
  tolerance for lossy variants), index 0/middle/last, negative/beyond-EOF frame,
  missing video ID, missing video file, and invalid detection for all methods.
- [ ] Add exact crop comparisons against retrieved source frame for integer,
  fractional, and clamped bounds; wholly offscreen valid-schema boxes must raise.
- [ ] Add clips centered at 0, 5, 24, 47; compare each returned slot to the known
  source index `min(max(f - 16 + slot, 0), 47)`. Include 1-frame and 7-frame videos.
  Test a detection whose reference is beyond EOF.
- [ ] Run `uv run pytest tests/test_video_retrieval.py -q` before the package exists;
  confirm an import failure and report red confirmation to the coordinator.
- [ ] Add tests for immutable typed metadata, read-only/noncreating DB behavior,
  decoder cleanup and single-open clip behavior, and H.264/B-frame ordering using
  an available PyAV encoder (skip only that codec-specific case if unavailable).
- [ ] Once implementation is available rerun the focused file, report failures
  with exact traceback and expected behavior. Edit only tests.

### Task 3: Retrieval implementation — worker B

**Files:** create `backend/video_retrieval/__init__.py`, `contracts.py`, `retrieval.py`.

**Interfaces:** consumes helper/constants and produces the shared public API.

- [ ] Confirm test worker has observed red before writing implementation.
- [ ] Implement frozen DetectionInfo exactly as shared above and exports.
- [ ] Resolve the supplied/default database path, open a read-only connection to
  validate availability, close it. Each query uses `contextlib.closing` around
  `connect_database(self.db_path, read_only=True)`.
- [ ] Implement parameterized detection JOIN and Video lookup. Construct typed
  metadata, raise LookupError with requested ID if no row, and check local file
  existence before opening PyAV. Resolve stored paths against REPOSITORY_ROOT.
- [ ] Implement bounded sequential decoding inside `with av.open(path) as video`.
  Enumerate `video.decode(video=0)`; convert selected images with
  `frame.to_ndarray(format="rgb24")`. Stop after the window end. At EOF distinguish
  an invalid reference from a valid window requiring right-edge padding. Never
  infer EOF from `stream.frames` or metadata duration. Allocate the output once
  shape is known and fill repeated edge slots without retaining the whole video.
- [ ] Implement get_frame and get_clip on the bounded decoder; a clip opens only
  once. Missing or negative indices raise clear errors; contextualize av failures.
- [ ] Implement floor/ceil/clamped slicing in get_face, checking finite bbox
  values and rejecting empty results; preserve original pixels and size.
- [ ] Run `uv run pytest tests/test_video_retrieval.py -q`, fix implementation
  failures, and report exact passing output. Do not edit the test worker's file.

### Task 4: Validation notebook — worker C

**Files:** create `backend/notebooks/video_retrieval_validation.ipynb` only.

**Interfaces:** consumes public API, path constants, read-only helper/table_counts.

- [ ] Create a valid nbformat 4 notebook with backend import-path setup supporting
  launch from repository root, backend, or backend/notebooks. Initialize retriever;
  use read-only SQL and table_counts for the four requested totals.
- [ ] Sort candidate detection IDs before seeded selection (`random.Random(42)`).
  Check original paths exist, report empty data clearly, show metadata and title.
- [ ] Retrieve source via get_frame, draw matplotlib Rectangle and person label;
  retrieve get_face, show dimensions, and compare to the expected frame slice.
- [ ] Retrieve get_clip, assert dtype/shape, label 4x8 axes with clamped source
  indices, and highlight slot 16 with the bbox/person label. Obtain true frame
  count in diagnostic code by enumerating PyAV decoding without retaining images;
  this metadata diagnostic does not duplicate retrieval.
- [ ] Add beginning/middle/end detection selection based on actual decoded video
  bounds; compare clip slots with get_frame for chronology/padding. Report when
  dataset lacks true boundary detections. Delete large arrays/close figures
  between boundary cases to keep memory bounded.
- [ ] Add zero-index/timestamp validation using original stream timestamps and
  stored fps/source timestamp with tolerances. Include a visual human check for
  detected face alignment; do not imply automated identity verification.
- [ ] Validate notebook JSON with nbformat; all code cells have `outputs: []`
  and `execution_count: null`. Never save an executed notebook or images.

### Task 5: Integration and documentation — coordinator

**Files:** modify `backend/README.md`; review every added/modified backend file.

**Interfaces:** consumes all completed workstreams.

- [ ] Document uv setup, imports, API examples, exceptions, exact sequential
  indexing/performance trade-off, notebook launch, and in-memory image handling.
  Update old README claims that the entire backend has no frame processing or
  runtime dependencies, while keeping ingestion-specific behavior accurate.
- [ ] Run `uv run pytest -q` and `uv sync --locked`; require all existing and new
  tests to pass. Review output and fix causes before repeating relevant tests.
- [ ] Use nbformat to validate structure; execute notebook with outputs only in
  memory. If production execution is costly, verify full notebook execution on
  synthetic DB/video fixtures and a real-data smoke check on a short original.
  Never write outputs back to the repository notebook.
- [ ] Validate actual source video frame 0 and selected subsequent frame indices
  against independent sequential decoding and stored timestamps; inspect decoded
  source dimensions and clip shape. Do not export images or alter production DB.
- [ ] Review `git diff --check`, `git diff --stat`, and `git status --short`;
  verify the pre-existing root notebook edit is untouched and outputs are clear.
- [ ] Report delivered paths, test counts, real-data checks, and sequential
  decoding latency trade-off. No commit or branch operation.
