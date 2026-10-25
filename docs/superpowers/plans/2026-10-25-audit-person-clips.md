# Audit Logging and Person-Based Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add audited corrections, immutable person-presence clips, live analytics,
and source-video segment retrieval to the SQLite backend.

**Architecture:** Add focused modules under analysis_db for schema extensions,
corrections, segmentation, and summaries. Extend VideoRetriever's existing
in-memory RGB retrieval contract. Finalize clips explicitly after detection imports.

**Tech Stack:** Python 3.13, SQLite, PyAV, NumPy, pytest; no new dependencies.

## Global Constraints

- Default threshold: 5 consecutive analyzed frames.
- Audit records are created only for user-initiated corrections.
- The correction and audit insertion must execute within a single database transaction.
- Store timestamps in UTC using ISO 8601.
- Clip boundaries are static after initial generation.
- Do not permanently generate or store separate video files for each clip.
- Preserve existing data and the six-table ingestion/counting interface.
- Work in .worktrees/audit-person-clips; do not commit unless requested.

## Task 1: Additive schema and transactional corrections

Files: create backend/db/audit_clips.sql, backend/analysis_db/corrections.py,
backend/tests/test_corrections.py; modify backend/analysis_db/storage.py.

Interfaces: initialize_database(path) installs the extension; correction functions
correct_activity(connection, activity_id, new_label, *, changed_by=None) -> bool
and correct_engagement(connection, engagement_id, positive_score, neutral_score,
negative_score, *, changed_by=None) -> bool return whether a change occurred.

- [x] Write fixtures with a video, frames, detections, Activity and Engagement.
  Assert `correct_activity(c, 1, 'writing')` changes the current label and records
  `('discussion', 'writing')`. Repeat corrections and assert history order.
- [x] Run `python -m pytest tests/test_corrections.py -q`; confirm missing module.
- [x] Create additive SQL with all four requested tables and finalization marker.
  Protect history with triggers, and use explicit BEGIN IMMEDIATE/commit/rollback
  in corrections. No-op returns False; missing record raises LookupError;
  invalid label/scores raises ValueError. Require an idle connection.
- [x] Verify no-op, append-only SQL, injected failing audit insert, migration
  rerun, unchanged existing rows, and engagement score history.

## Task 2: Persistence segmentation and immutable population

Files: create backend/analysis_db/clips.py, backend/scripts/populate_clips.py,
backend/tests/test_person_clips.py; extend backend/db/audit_clips.sql triggers.

Interfaces: generate_clips(connection, video_id, *, persistence_frames=5)
-> tuple[int, ...]; populate_clips(connection, *, persistence_frames=5)
-> dict[int, tuple[int, ...]].

- [x] Add person-set timelines with exact expected start/end/membership tuples.
  Include `[{A}]*5 + [{A,B}]*5`, expecting A over [0,5), then A/B to duration.
- [x] Run `python -m pytest tests/test_person_clips.py -q`; confirm import failure.
- [x] Implement per-person counters, backdated events, timestamp grouping,
  transactional insertion and finalization. Use left joins to include empty frames.
- [x] Add departure, short dropout, simultaneous swap, overlapping runs, late
  unconfirmed arrival, empty video, invalid metadata and repeated calls tests.
  Attempt SQL mutation of finalized clips and membership; require rejection.
- [x] Add CLI `--db`, `--video-id`, `--persistence-frames`, concise errors and
  populated counts; test invocation with temporary databases.

## Task 3: Live aggregation and import lifecycle

Files: create backend/analysis_db/clip_analytics.py,
backend/tests/test_clip_analytics.py; modify analysis_db/engagement_table.py,
analysis_db/identity_tables.py; extend relevant import tests.

Interfaces: get_clip_info(connection, clip_id) -> ClipInfo and
get_clip_summary(connection, clip_id, *, include_details=False) -> dict.
ClipInfo is a frozen dataclass with clip/video IDs, interval, and person IDs.

- [x] Test a clip [5,15) with activity windows [0,10) and [10,30): equal weights.
  Also use unequal overlap lengths to distinguish weighting from record counting.
- [x] Run `python -m pytest tests/test_clip_analytics.py -q`; confirm import failure.
- [x] Query same-video overlapping windows and available member detections;
  normalize current labels, compute means/counts, and return detailed rows on request.
- [x] Test missing engagement, person-specific/group weighted means, missing clip,
  no activities, boundary exclusion and updates after both correction methods.
- [x] Upsert retained Engagement IDs; delete only absent input IDs so audited
  removals fail atomically through foreign keys. Guard destructive identity
  replacement when history or finalized clips exist. Verify imports create no audits.

## Task 4: Source segment retrieval

Files: modify backend/video_retrieval/contracts.py, retrieval.py, __init__.py;
create backend/tests/test_person_clip_retrieval.py.

Interfaces: VideoSegment(frames, source_frame_indices,
source_timestamps_seconds, requested_start_seconds, requested_end_seconds);
VideoRetriever.get_segment(video_id, start_time_seconds, end_time_seconds),
get_person_clip(clip_id), get_person_clip_info(clip_id),
get_person_clip_summary(clip_id, *, include_details=False).

- [x] Encode tiny lossless synthetic videos and compare returned frames against
  an independent full decode filtered to the expected half-open PTS interval.
- [x] Run `python -m pytest tests/test_person_clip_retrieval.py -q`; confirm missing methods.
- [x] Extend existing PyAV retrieval with normalized Fraction timestamps and
  exact presentation indices; keep existing detection retrieval unchanged.
- [x] Verify first/last frames, nonzero PTS origins, variable intervals, missing
  source/clip/video, invalid bounds, and no extra files after retrieval.

## Task 5: Documentation and final verification

Files: modify backend/README.md, backend/scripts/init_db.py help text;
create backend/db/README.md documenting new schema and interfaces.

- [x] Document the initialization/finalization sequence, correction examples,
  overlap policy, null summaries, immutable lifecycle, and retrieval examples.
- [x] Run targeted new tests, then the complete backend suite using
  `/mnt/storage/Projects/ai_for_good_2026/backend/.venv/bin/python -m pytest -q`.
- [x] Review `git diff --check`, worktree status, and all source changes for
  requirement coverage and compatibility. Report test counts and worktree path.

## Self-review

Tasks 1–4 cover all requested tables and backend capabilities. Task 2's marker
handles repeated empty initialization. Task 3 preserves history across existing
destructive import paths. Task 4 preserves zero-based presentation indexing and
does not mux or export files. All interfaces above use current SQLite connection
and dataclass conventions. No authentication, identity correction, or models added.

## Completion evidence

- Full backend suite: **479 passed** (364-test baseline, 115 additional cases).
- Read-only review findings resolved and rechecked: prevent both INSERT/UPDATE
  OR REPLACE from replacing finalized Video rows; validate the entire decoded PTS
  stream; index Frame by video/time for live engagement summaries.
- Added boundary regressions for floating-point SQLite/decoded timestamp equality.
- `git diff --check` passes. Work remains uncommitted on
  `feat/audit-person-clips` in `.worktrees/audit-person-clips`.
