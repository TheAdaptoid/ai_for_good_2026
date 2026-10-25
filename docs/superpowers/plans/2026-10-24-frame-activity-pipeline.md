# Frame-linked Activity Pipeline Implementation Plan

> **For agentic workers:** Use `executing-plans` to implement this plan inline, task by task. Do not dispatch agents unless the user requests delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Activity to center-frame records and benchmark 100 randomly
sampled center frames with seed 42. Use FP32, batches of 2, indexed retrieval,
and bounded prefetch to estimate the remaining full-dataset runtime.

**Architecture:** Keep the existing retriever as a correctness reference. Add an
indexed sampler and batch methods to the classifier. A CPU producer prepares
batches for one GPU consumer. One Activity row stores one center frame's result.

**Tech Stack:** Existing Python 3.13 backend, sqlite3, NumPy, PyAV, PyTorch,
Transformers, and pytest. No new dependencies.

## Global constraints

- Spec: `docs/superpowers/specs/2026-10-24-frame-activity-pipeline-design.md`.
- Use all person IDs. Do not implement the superseded percentile filter.
- Sample 32 frames over 15 seconds centered on the selected detection's time.
- Preserve existing retrieval/classifier calls and their local-only behavior.
  Add optional precision and batch methods without breaking single-clip callers.
- Preserve all 50,514 existing Engagement rows during migration and inference.
- Keep frame/crop arrays and notebook displays in memory. Save no image outputs.
- Default to 100 distinct sampled centers, seed 42, GPU FP32, batch size 2,
  and queue capacity 2 prepared batches. Remove the old default 50-attempt cap.
- Stop after the benchmark and report a measured remaining-work estimate.
- No commits or pushes without a new user request.
- This is a draft implementation plan. Review the spec before implementation.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `backend/db/schema.sql` | New Activity structure for fresh databases |
| `backend/analysis_db/activity_schema.py` | Explicit legacy-to-new Activity migration |
| `backend/analysis_db/activity_results.py` | Hashes, row validation, lookup, and transactional upsert |
| `backend/activity_pipeline/{__init__,config,selection,runner}.py` | Configuration, frame jobs, and orchestration |
| `backend/video_retrieval/indexed.py` | PTS index and exact bounded-window decode |
| `backend/activity_classification/{classifier,contracts}.py` | Optional precision, CPU batch preparation, and ordered batch results |
| `backend/scripts/migrate_activity.py` | Migration CLI |
| `backend/scripts/classify_activity.py` | Selection and inference CLI |
| `backend/tests/test_activity_{migration,selection,pipeline}.py` | Transaction, selection, and orchestration checks |
| `backend/tests/test_video_indexed_sampling.py` | Indexed/reference sampling equivalence and seek fallback |
| `backend/tests/test_activity_classification.py` | Precision and batch behavior, plus single-clip compatibility |
| `backend/tests/{test_storage,test_identity_tables}.py` | Update legacy Activity fixtures and assertions |
| `backend/README.md` | Local-copy setup, commands, semantics, and timing limits |

## Task 1: Migrate Activity without losing other results

**Interfaces:**

```python
# analysis_db/activity_schema.py
def migrate_activity(connection: sqlite3.Connection) -> bool:
    """Return True if migrated, False if already current; do not own the connection."""
```

- [ ] Add migration tests before implementation. Construct an empty legacy
  Activity table with its old six columns and populate all five other tables,
  including an Engagement row. Check exact before/after snapshots for those five
  tables. Also test idempotence, nonempty legacy rejection, unknown-schema
  rejection, and rollback when validation fails.
- [ ] Run `uv run --locked pytest -q tests/test_activity_migration.py` from
  `backend/`. Confirm failures identify the missing migration behavior.
- [ ] Implement the exact Activity DDL in the spec in both `schema.sql` and the
  migration. Require an idle connection and inspect columns, foreign keys, and
  constraints to distinguish legacy/current/unknown schemas. Use `BEGIN IMMEDIATE`.
  Create `Activity_new`, drop the empty legacy Activity, then rename the new table.
  Check `foreign_key_check` and `integrity_check` before commit. Roll back failures.
  Verify the full schema before accepting an already-current no-op.
- [ ] Add `scripts/migrate_activity.py --db PATH` using the existing CLI style.
  Require an existing database. Print migrated/already-current status. Exit 1 on
  expected migration errors and 2 on invalid arguments. Do not migrate implicitly
  through initialization or inference.
- [ ] Replace `test_storage.py::test_activity_frame_interval` with meaningful
  new-schema tests: frame FK, unique frame, negative requested start allowed,
  positive interval, exactly 32 samples, and score range. Update the Activity seed
  in `test_identity_tables.py` with named columns and valid JSON. Confirm identity
  replacement still clears Activity before removing its parent frames.
- [ ] Run `uv run --locked pytest -q tests/test_activity_migration.py tests/test_storage.py tests/test_identity_tables.py tests/test_engagement_table.py`.
  Verify equivalent constraints on fresh and migrated databases.

## Task 2: Define settings and select the seeded benchmark

**Interfaces:**

```python
# activity_pipeline/config.py
INTERVAL_SECONDS = 15.0
SAMPLE_COUNT = 32
BATCH_SIZE = 2
PRECISION = "fp32"
PREFETCH_BATCHES = 2
BENCHMARK_SIZE = 100
SEED = 42
ACTIVITIES = (
    "Dancing", "Rapping", "Singing", "Playing sports", "Playing games",
    "Running", "Walking", "Sitting and listening", "Drawing or painting",
)

@dataclass(frozen=True)
class FrameJob:
    frame_id: str
    video_id: int
    frame_number: int
    source_time_seconds: float
    anchor_detection_id: int

# activity_pipeline/selection.py
def select_frame_jobs(connection, *, video_ids: tuple[int, ...] = ()) -> list[FrameJob]:
    """Return the complete eligible population in deterministic video/frame order."""

def sample_frame_jobs(population: list[FrameJob], *, sample_size: int | None = 100,
                      seed: int = 42) -> list[FrameJob]:
    """Sample without replacement, then sort selected jobs for video/time processing.

    None selects the full population. An empty population returns an empty list.
    """
```

- [ ] Write selection tests with two people sharing one frame, a person with one
  detection, a Frame without detections, and two videos. Expect one job for the
  shared frame, inclusion of the low-count person, exclusion of the empty frame,
  the smallest anchor detection ID, deterministic ordering, and video filtering.
- [ ] Run `uv run --locked pytest -q tests/test_activity_selection.py` and confirm
  the missing selection fails. Implement the interfaces above and rerun.
- [ ] Test sample size, distinct frame IDs, repeatability, changed seed, and
  video/time execution order. Use a six-frame fixture in one video: seed 42 and
  sample size 3 must select frames 0, 4, and 5. Reject nonpositive or oversized
  samples; allow an empty population without model loading. Test `None` as all.
  Implement membership with `random.Random(seed).sample(population, sample_size)`.
- [ ] Use this query shape, with parameterized video filters when requested:

  ```sql
  SELECT f.frame_id, f.video_id, f.frame_number, f.source_time_seconds,
         MIN(d.detection_id) AS anchor_detection_id
  FROM Frame AS f JOIN FaceDetection AS d ON d.frame_id = f.frame_id
  GROUP BY f.frame_id, f.video_id, f.frame_number, f.source_time_seconds
  ORDER BY f.video_id, f.frame_number, f.frame_id;
  ```

  Do not load old handoff CSVs, apply a percentile, or thin nearby centers.
  Choose the random sample before resume filtering. Record the population
  fingerprint and sampled IDs. A rerun must not replace completed sample members.

## Task 3: Add exact indexed retrieval and FP32 batch inference

**Interfaces:**

```python
# video_retrieval/indexed.py
class IndexedTemporalSampler:
    def __init__(self, path: Path):
        """Build one timestamp-only index; close the index-building decoder."""

    def sample(self, *, reference_frame_number: int, center_seconds: float,
               interval_seconds: float = 15.0,
               sample_count: int = 32) -> TemporalClip:
        """Return the same sample as the reference temporal implementation."""

# Add to XCLIPClassifier; keep all existing constructor arguments.
# precision=None retains the existing device-based default for older callers.
def __init__(self, *, device="auto", model_path=None, cache_dir=None,
             precision: str | None = None): ...

def prepare_batch(self, clips: Sequence[RGBFrames], activities: list[str], *,
                  prompt_template=DEFAULT_PROMPT_TEMPLATE,
                  descriptions=None) -> PreparedBatch: ...

def classify_prepared_batch(self, batch: PreparedBatch) -> tuple[ClassificationResult, ...]: ...

def classify_batch(self, clips: Sequence[RGBFrames], activities: list[str], *,
                   prompt_template=DEFAULT_PROMPT_TEMPLATE,
                   descriptions=None) -> tuple[ClassificationResult, ...]: ...
```

`PreparedBatch` holds CPU input tensors, resolved candidates, each clip's input
frame count and selected indices, and measured preparation duration. Define it
in `activity_classification/contracts.py` without eagerly importing torch. No
GPU tensor enters the producer queue. Keep result fields and package exports
unchanged. Import the prepared-batch type from contracts when needed.

- [ ] Add indexed-sampler tests before implementation. Compare complete returned
  arrays and metadata with `get_temporal_clip` on synthetic CFR and VFR videos,
  nonzero starting PTS, ties, left/right padding, and late references. Add an H.264
  B-frame case when ffmpeg is available. Reject invalid PTS and references beyond
  EOF. Test a seek that starts too late: sequential retry must recover exact frames
  and increment a visible fallback counter.
- [ ] Run `uv run --locked pytest -q tests/test_video_indexed_sampling.py` while
  implementing the index. Store original indices and rational presentation times
  relative to the first frame. Build the index once per selected video without
  RGB conversion. Resolve targets with the reference's exact nearest/tie rule.
  Seek using the stream time base and preceding keyframe, map decoded PTS to
  indexed source frames, and stop after the final required frame. Open/close each
  window decoder within the retrieval worker. Keep original APIs unchanged.
- [ ] Add precision/batch tests to `test_activity_classification.py`. Cover explicit
  FP32 model loading on CUDA, retained legacy defaults, invalid precision, every
  output row, batch order, per-row softmax, distinct clips, and singleton batches.
  Verify CPU preparation does not call CUDA. Add numerical batch/single checks
  with a tiny deterministic real X-CLIP configuration; use tolerances, not bitwise
  equality. Do not download weights in automated tests.
- [ ] Run `uv run --locked pytest -q tests/test_activity_classification.py` while
  adding the methods. Resolve dtype before `from_pretrained`; FP32 loads original
  FP32 weights directly. Reject explicit FP16 on CPU. `classify_batch` prepares and executes;
  existing `classify` returns the sole result of a one-clip batch. Preserve input,
  token, finite-output, error-cleanup, and local-only checks.
- [ ] Return results in input order. Pass one candidate token batch shared by the
  video batch, not duplicated candidates. Normalize scores along the label axis.
  Per-result preparation/inference/total timings are batch totals divided by its
  actual size. Record raw batch timings and actual size for the runner; whole-batch
  peak GPU memory may appear on each result. Do not call those shares clip latency.
- [ ] Run `uv run --locked pytest -q tests/test_video_indexed_sampling.py tests/test_video_temporal_sampling.py tests/test_video_retrieval.py tests/test_activity_classification.py tests/test_activity_runtime.py`.

## Task 4: Persist results, overlap preparation, and report throughput

**Interfaces:**

```python
# analysis_db/activity_results.py
def canonical_json(value) -> str: ...
def config_fingerprint(settings: dict) -> str: ...
def input_fingerprint(job: FrameJob, *, video_path: Path, repository_root: Path) -> str: ...
def result_matches(connection, frame_id: str, config_hash: str, input_hash: str) -> bool: ...
def save_activity(connection, job: FrameJob, sampling: dict,
                  result: ClassificationResult, *, config_json: str,
                  config_hash: str, input_hash: str,
                  retrieval_time_seconds: float) -> None: ...

# activity_pipeline/runner.py
@dataclass(frozen=True)
class RunSummary:
    population: int
    selected: int
    skipped: int
    attempted: int
    written: int
    failed: int
    report: dict

def run_activity(db_path: Path, *, video_ids: tuple[int, ...] = (),
                 sample_size: int | None = BENCHMARK_SIZE, seed: int = SEED,
                 limit: int | None = None, device: str = "auto",
                 precision: str = PRECISION, batch_size: int = BATCH_SIZE,
                 prefetch_batches: int = PREFETCH_BATCHES,
                 dry_run: bool = False) -> RunSummary: ...
```

The ellipses above denote signatures, not implementation steps. Hash settings
and inputs exactly as specified in the spec. Canonical JSON uses sorted keys,
compact separators, UTF-8, and `allow_nan=False`. Hash the encoded JSON with
SHA-256. Use `prepare_candidates` from the existing classifier to resolve prompts.
Store their original configured order, not score order, in the configuration.

- [ ] Add persistence tests: JSON round-trip, matching top label/score, finite
  values, exact 32-entry sampling arrays, frame uniqueness, hash stability under
  dictionary key reordering, and hash changes for changed prompts/source metadata.
  Test successful replacement and preservation of the old row after a failed save.
  Implement validation and an explicit transaction around an
   `ON CONFLICT(frame_id) DO UPDATE` statement. Reset `created_at` on replacement. Never commit
  a partial prediction or a failed classification.
- [ ] Add runner tests with synthetic videos and temporary databases. Substitute
  only the expensive classifier boundary with a deterministic callable returning
  real `ClassificationResult` objects. Keep real selection, indexed retrieval,
  hashes, CPU preprocessing, and SQL.
  Test one model input for a shared frame, boundary padding, matching-result skip,
  changed-configuration recomputation, empty input, and failed-result retry. Test
  that completed/failed members of a seeded sample are not replaced with new IDs.
- [ ] Test limit behavior with at least four center frames and `limit=2`: the first
  run writes the first two; the next run skips those and writes the next two within
  the same selected sample. Test that a clip failure counts as an attempt and
  produces a nonzero CLI exit.
  Model load, database failure, and CUDA OOM must stop the run without losing prior
  commits. Simulate these failures at the appropriate boundaries.
- [ ] Run `uv run --locked pytest -q tests/test_activity_pipeline.py` while
  implementing the persistence and runner behavior. Normal inference requires
  the migrated schema. Resolve original paths through existing repository path
  rules. Read/sample selection first; return without loading a model if empty.
  Dry-run never constructs the classifier/sampler or writes a database record.
- [ ] Add the inference CLI with `--db`, repeatable `--video-id`, `--device`,
  `--precision`, `--batch-size`, `--prefetch-batches`, `--seed`, `--dry-run`,
  `--report PATH`, optional `--limit N`, and mutually exclusive `--sample-size N`
  / `--all`. Default to sample size 100, seed 42, precision fp32, batch size 2,
  queue capacity 2, and no pending-attempt limit. `--all` sets sample size to None;
  `--limit` remains a separate optional cap in either mode. Reject nonpositive
  sample sizes, limits, batch sizes, or queue capacities. Dry-run reports sample
  membership/counts, per-video coverage, settings, and population fingerprint
  without model loading. Normal runs report counts/times and estimates. Exit 0 for successful work,
  1 for failures, 2 for invalid usage, and 130 after a clean Ctrl-C stop.
- [ ] Keep one FP32 classifier for the run. Resolve hashes, skip matching sample
  members, then apply the optional attempt cap. Build timestamp indexes once for
  videos with pending jobs. Measure index construction separately from processing.
  If no pending jobs remain, return before indexing or warm-up. Otherwise warm
  the configured batch shape with synthetic 32-frame clips, not benchmark frames.
  Record warm-up time separately and discard its outputs.
- [ ] Use one CPU producer thread with `queue.Queue(maxsize=prefetch_batches)`.
  It retrieves up to two clips, extracts only numeric sampling metadata, calls
  `prepare_batch`, and releases raw RGB arrays before enqueueing. Do not use
  `dataclasses.asdict(clip)`, which copies its RGB array. Queue entries contain
  jobs, metadata, and a PreparedBatch, not TemporalClip objects with live images.
  The consumer alone performs CUDA work and commits each successful row. Measure
  raw batch times at the producer/consumer boundaries. Record actual batch size
  in each result's sampling metadata. Preserve a final singleton batch.
- [ ] Test queue overlap and capacity with controlled producer/consumer events,
  not timing-sensitive sleeps. Test producer failure, consumer OOM, and cancellation
  while a producer is waiting on a full queue. Use a stop event, timed queue puts,
  and `finally` cleanup; join the producer and close every decoder. No SQLite
  connection may cross threads. Clip failures count as attempts; continue with
  the other selected jobs. Propagate fatal GPU/configuration/DB errors.
- [ ] Keep complete metadata in JSON and simple label/score columns for the API.
  Pass `list(ACTIVITIES)` to candidate preparation and classification: the existing
  classifier rejects tuples. Detect classification OOM through its chained
  `torch.OutOfMemoryError`, which the classifier wraps in a `RuntimeError`.
  Include configured batch size, precision, and indexed sampler version in the
  config hash. Exclude seed, sample size, and queue depth so later `--all` work can
  reuse benchmark results. Use file-stat caching per source video for input hashes.
- [ ] Add report tests for exact counters, phase durations, setup exclusion,
  overlapping phases, resumed/failed sample labels, and zero completed work.
  Capture population and selected IDs, raw timings, per-video counts/retrieval times, batch
  sizes, GPU peak, and seek fallback counts. Compute the primary processing rate
  from wall time divided by newly written frames, never by summing phase times.
  Count remaining eligible frames with no current config/input match. Report
  `remaining_count * seconds_per_frame`, setup costs, and videos not represented
  in the sample. An estimate from fewer than 100 new successes is explicitly partial.
  Save JSON only when `--report` is supplied; benchmark output goes to ignored
  `results/`. Do not divide by zero or extrapolate from a run that only skips rows.

## Task 5: Benchmark 100 seeded frames, estimate the remainder, and hand off

- [ ] Inspect current notebook diffs. Clear saved outputs/execution counts from
  `backend/notebooks/activity_classification.ipynb` without overwriting current
  source edits. Keep the occurrence notebook available for inspection, but do not
  import it or its percentile setting into the runner.
- [ ] Run `uv lock --check`, then `uv run --locked pytest -q`, from `backend/`.
  Investigate actual failures. Do not weaken notebook-cleanliness checks or hide
  failures behind a claimed green suite.
- [ ] Create the local working database once with SQLite's backup API. Do not
  overwrite an existing local database, which may already contain useful results:

  ```bash
  uv run --locked python -c "from pathlib import Path; import sqlite3; p=Path('../data/analysis.local.sqlite'); assert not p.exists(), 'Local DB already exists; reuse it'; s=sqlite3.connect('file:../data/analysis.sqlite?mode=ro',uri=True); d=sqlite3.connect(p); s.backup(d); d.close(); s.close()"
  uv run --locked python scripts/migrate_activity.py --db ../data/analysis.local.sqlite
  uv run --locked python scripts/classify_activity.py --db ../data/analysis.local.sqlite --sample-size 100 --seed 42 --device cuda --precision fp32 --batch-size 2 --prefetch-batches 2 --dry-run
  uv run --locked python scripts/classify_activity.py --db ../data/analysis.local.sqlite --sample-size 100 --seed 42 --device cuda --precision fp32 --batch-size 2 --prefetch-batches 2 --report results/activity_benchmark_seed42.json
  uv run --locked python scripts/classify_activity.py --db ../data/analysis.local.sqlite --sample-size 100 --seed 42 --device cuda --precision fp32 --batch-size 2 --prefetch-batches 2 --report results/activity_resume_seed42.json
  ```

  For the inspected database, dry-run must select 100 unique frames from 34,452.
  Expected per-video sample counts are {1: 6, 2: 61, 3: 4, 4: 26, 5: 1, 6: 2}.
  The first real run must write 100 rows in 50 real-data inference batches with no failures.
  The second must select the same 100, skip them all, and do no new inference or
  decoding. Do not overwrite the first timing report with the resume report.
  If the database changes, regenerate expected sample counts from dry-run rather
  than embedding these dataset-specific numbers in automated tests. If existing
  local results cause skips, disclose that the run is partial rather than silently
  clearing those results to obtain 100 new timings.
- [ ] Compare the five non-Activity tables in the local copy before/after migration
  and both runs. Require identical rows, zero foreign-key violations, integrity
  `ok`, valid stored JSON, and one Activity row per processed center frame. Confirm
  the tracked source database is unchanged. Rerun migration to check its no-op.
- [ ] Inspect a real contact sheet and predictions in memory. Use an additional
  video-11 retrieval-only boundary clip to check the request against a shorter
  original. Do not add it to or replace any of the 100 benchmark members.
  Confirm padding metadata rather than treating repeated samples as distinct
  observations. Keep saved notebooks output-free. Record retrieval/inference
  timings, completed row counts, and failures in the handoff. No accuracy claim.
- [ ] Print processing wall time, seconds per newly completed center, setup costs,
  phase totals, peak GPU memory, and seek fallback count. On a fresh local copy,
  100 matching completions leave 34,352 pending eligible frames. Compute remaining
  hours from measured wall throughput; do not reuse the old FP16 timing estimate.
  Include per-video coverage and note that videos 7-12 are absent from the current
  random sample. Do not present phase totals as additive when stages overlap.
  Stop after the benchmark and report. Do not launch the full dataset automatically.
- [ ] Update `backend/README.md`: migration requirement, all-person selection,
  centered sampling, seeded selection, precision, batching, indexed retrieval,
  bounded prefetch, resume behavior, current-result replacement, local database
  path, score meaning, and benchmark/estimate commands. Explain one-time index
  costs and reported seek fallbacks. Replace
  outdated statements that Activity and Engagement are always empty or that no
  backend component writes predictions. Document the query below for the API:

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

  Null Activity values mean unprocessed frames, not a negative prediction. The
  query deliberately shares one window result among detections in its center
  frame; it does not assign that label to every frame inside the time interval.
- [ ] Run `git diff --check`. Present the measured small-run results and the local
  database path. This is the backend handoff point. Do not delay frontend work
  while waiting for all 34,452 centers to finish.

## Deferred work

Further full-corpus tuning, multiple historical results per frame, API routes,
UI, and manual accuracy evaluation are separate tasks. Precision, batch size 2,
indexed retrieval, and prefetch are part of this milestone. Keep the 15-second,
32-sample window unchanged. Outside the explicit seeded benchmark, do not thin
center frames without user agreement.
