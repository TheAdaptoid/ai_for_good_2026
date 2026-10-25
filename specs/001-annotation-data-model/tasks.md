---
description: "Task list for Spec 001: Review and Annotation Data Model"
---

# Tasks: Review and Annotation Data Model

**Input**: Design documents from `specs/001-annotation-data-model/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/python-api.md,
contracts/export-format.md, quickstart.md

**Tests**: Required. Constitution Principle X and the user's request both call for them. Each test
task sits next to the implementation it validates. Write the test first and confirm it fails.

**Organization**: Grouped by user story in priority order (P1: US1, US2, US4; P2: US3, US5, US7,
US8; P3: US6).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: User story from spec.md
- All paths are relative to the repository root. Run commands from `backend/`.

## Scope guard (applies to every task)

- No new third-party dependencies. Use only the stdlib (`sqlite3`, `csv`, `json`, `dataclasses`,
  `enum`).
- `schema.sql` changes are additive only (`CREATE … IF NOT EXISTS`, `INSERT OR IGNORE`).
  `Video`, `Frame`, `Person`, `FaceDetection`, `Activity`, and `Engagement` stay unchanged.
- Do not build FastAPI routes, React UI, authentication, clip generation, ML inference, affect
  segmentation, or model evaluation.
- Existing ingestion behavior and `TABLES` (the six original tables) stay unchanged.

---

## Phase 1: Setup

**Purpose**: Confirm a green baseline before changing anything.

- [X] T001 Run `uv sync --locked && uv run pytest -q` in `backend/` and record the passing
  baseline (expect all existing tests in `backend/tests/` to pass, or skip for missing
  ffmpeg/weights)

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: Schema, database safeguards, seeds, shared types, and test fixtures that every
story uses.

**⚠️ No user story work can begin until this phase is complete.**

### Schema and safeguards

- [X] T002 Append the `Label` table to `backend/db/schema.sql` (before its final `COMMIT;`).
  Columns: `label_id INTEGER PRIMARY KEY`, `name TEXT NOT NULL CHECK(length(trim(name))>0)`,
  `category TEXT NOT NULL CHECK(category IN ('activity','observation'))`, `description TEXT`,
  `is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))`. Add a unique index on
  `(category, name COLLATE NOCASE)` (`CREATE UNIQUE INDEX IF NOT EXISTS`) and a `label_no_delete`
  BEFORE DELETE trigger (`CREATE TRIGGER IF NOT EXISTS`) that raises
  `RAISE(ABORT, 'labels cannot be deleted; deactivate instead')`, per
  `specs/001-annotation-data-model/data-model.md`
- [X] T003 Append the 18 starter labels to `backend/db/schema.sql` as `INSERT OR IGNORE INTO Label`
  with fixed IDs. 1–9 are activity: Singing, Dancing, Acting, Spoken Performance, Instrumental
  Performance, Rehearsal, Group Performance, Solo Performance, Presenting Creative Work. 10–18 are
  observation: Sustained Participation, Projecting Voice, Collaboration, Leadership, Increased
  Participation, Decreased Participation, Visible Positive Affect, Visible Neutral Affect, Visible
  Negative Affect
- [X] T004 Append `ReviewClip` and `ReviewClipParticipant` to `backend/db/schema.sql`:
  - `ReviewClip` has `video_id` FK, start/end frame with `CHECK(0 <= start_frame AND start_frame <= end_frame)`,
    `priority_score REAL CHECK(priority_score IS NULL OR priority_score >= 0)`, `priority_method TEXT`,
    `CHECK(priority_score IS NULL OR priority_method IS NOT NULL)`, `import_key TEXT UNIQUE`, and
    `created_at TEXT NOT NULL`.
  - `ReviewClipParticipant` has `(clip_id` FK `ON DELETE CASCADE`, `person_id` FK → Person),
    with PK `(clip_id, person_id)`.
  - Indexes, all `CREATE INDEX IF NOT EXISTS`: `(video_id, start_frame)`, `(priority_score DESC)`,
    and participant `(person_id)`.
- [X] T005 Append `Annotation` to `backend/db/schema.sql` with every column in data-model.md:
  - Foreign keys: `video_id` NOT NULL, `clip_id` NULL, `person_id` NULL, `label_id` NOT NULL.
  - Span `CHECK(0 <= start_frame AND start_frame <= end_frame)`.
  - `confidence` CHECK NULL or 0–1.
  - `source` CHECK IN ('AI','HUMAN').
  - `review_status` CHECK IN the five statuses.
  - `import_key TEXT UNIQUE`, `created_at`, `updated_at`.
  - Indexes, all `CREATE INDEX IF NOT EXISTS`: `(video_id, start_frame)`, `(person_id)`,
    `(label_id)`, `(review_status)`, `(clip_id)`.
- [X] T006 Append `ReviewEvent` to `backend/db/schema.sql`:
  - Columns: all prev_/new_ columns from data-model.md, `action` CHECK IN
    ('CREATED','ACCEPTED','EDITED','REJECTED','DEFERRED'), and
    `reviewer_id TEXT NOT NULL CHECK(length(trim(reviewer_id))>0)`.
  - The FKs to Annotation and Video have **no** ON DELETE CASCADE.
  - Add triggers `review_event_no_update` and `review_event_no_delete`
    (`CREATE TRIGGER IF NOT EXISTS`) that `RAISE(ABORT, 'review history is append-only')`.
- [X] T007 Add `REVIEW_TABLES = ("Label", "ReviewClip", "ReviewClipParticipant", "Annotation", "ReviewEvent")`
  to `backend/analysis_db/contracts.py`, and leave `TABLES` unchanged
- [X] T008 Add an optional parameter to `assert_schema` in `backend/analysis_db/storage.py`:
  `assert_schema(connection, tables=TABLES)`. The default behavior is unchanged, so ingestion,
  `replace_engagement`, and `replace_identity_tables` still work on databases that haven't been
  migrated. Add `review_table_counts(connection) -> dict[str, int]` next to `table_counts`.
  `table_counts` itself stays limited to `TABLES`.
- [X] T009 Add the enums `Source`, `ReviewStatus`, `ReviewAction`, and `LabelCategory` (StrEnum),
  and the frozen dataclasses `Label`, `Annotation`, `ReviewClip`, `ReviewEvent`, `ClipInput`,
  `AnnotationInput`, `AnnotationChanges` (with an `UNSET` sentinel for `person_id`), and
  `ImportResult`, to `backend/analysis_db/contracts.py`, exactly as listed in
  `specs/001-annotation-data-model/contracts/python-api.md`
- [X] T010 Add shared fixtures to `backend/tests/conftest.py`:
  - `review_db` yields an open `connect_database` connection on a freshly initialized temp
    database. It contains one Video (fps 23.976, duration 100.0 s, so 2398 frames), a second
    Video, and Persons `Person_0001` to `Person_0003`.
  - `insert_ai_annotation(conn, **overrides) -> int` is a helper that inserts an AI/UNREVIEWED
    annotation by direct SQL, so stories can be tested independently.

### Foundational tests

- [X] T011 [P] Write `backend/tests/test_review_schema.py`. It asserts:
  - the five new tables exist after `initialize_database`
  - Label has exactly 18 rows with the expected IDs, names, and categories
  - CHECK constraints reject a bad `source`, a bad `review_status`, confidence 1.5, a reversed
    span, a negative priority score, a score without a method, and a blank `reviewer_id`
  - `UPDATE ReviewEvent` and `DELETE FROM ReviewEvent` raise `sqlite3.IntegrityError` with
    "append-only"
  - `DELETE FROM Label` raises
  - deleting an Annotation that has a ReviewEvent fails with a foreign key error
  - `initialize_database` run twice on the same file succeeds (all `IF NOT EXISTS`)
  - `assert_schema(conn)` passes on a database with only the six original tables, and
    `assert_schema(conn, tables=REVIEW_TABLES)` raises on it
- [X] T012 [P] Add tests, without changing any existing assertion:
  - In `backend/tests/test_cli.py`, add a test that `scripts/init_db.py` prints the six existing
    table counts followed by the five review-table counts (Label 18, the others 0). The existing
    "Table counts:" assertions are for `ingest.py` and stay unchanged.
  - In `backend/tests/test_storage.py`, extend `test_schema_has_no_image_path_columns` to loop over
    `TABLES + REVIEW_TABLES`.
- [X] T013 Update `backend/scripts/init_db.py` to print the review-table counts (via
  `review_table_counts`) after the existing six. Change its help text from "six-table" to describe
  creating or migrating the database idempotently.

**Checkpoint**: `uv run pytest -q` passes. The schema, safeguards, and seeds are in place.

---

## Phase 3: User Story 1 - One record serves every view (P1) 🎯 MVP

**Goal**: The same annotation records answer video/time, participant, label, category, source,
and status queries, including multi-label and group-level records. They can be exported.

**Independent Test**: Seed annotations with `insert_ai_annotation`, then query them each way and
confirm the same `annotation_id`s come back. Export as CSV and JSON.

### Tests for US1

- [X] T014 [P] [US1] Write `backend/tests/test_annotation_queries.py`:
  - three labels on one participant span are all returned by video and by participant, with
    identical IDs
  - a two-participant shared span is returned for each participant
  - a group-level annotation (`person_id` NULL) is returned by video
  - the category filter separates activity from observation
  - the time filter returns overlapping spans only
  - `start_seconds = frame / fps`, and is None when the video's fps is NULL
  - results are ordered by video, then start frame
- [X] T015 [US1] Add rejected-filter cases to `backend/tests/test_annotation_queries.py`:
  - REJECTED rows are absent by default
  - they are present with `include_rejected=True`
  - they are present when explicitly filtered with `review_status="REJECTED"`

### Implementation for US1

- [X] T016 [US1] Implement a private row-to-`Annotation` mapper in
  `backend/analysis_db/annotations.py`. It joins Label for name and category, and Video for fps to
  derive seconds.
- [X] T017 [US1] Implement `list_annotations(conn, *, video_id, start_frame, end_frame, person_id, label_id, category, source, review_status, clip_id, include_rejected=False)`
  in `backend/analysis_db/annotations.py`:
  - parameterized SQL only
  - overlap semantics for the time range
  - excludes REJECTED unless `include_rejected` is set or `review_status` is given (FR-005, FR-020)
- [X] T018 [P] [US1] Write `backend/tests/test_exports.py` for annotations:
  - CSV header and column order match `specs/001-annotation-data-model/contracts/export-format.md`
  - JSON is an array with the same keys
  - NULL becomes an empty cell or `null`
  - seconds are rounded to 3 decimals
  - REJECTED rows are excluded by default and included with the flag
  - each non-rejected annotation appears exactly once (SC-007)
- [X] T019 [US1] Implement `export_annotations(conn, out, fmt, *, include_rejected=False, **filters)`
  in `backend/analysis_db/exports.py` using `list_annotations` with stdlib `csv` and `json`. Do not
  include a priority score (FR-027, FR-031).
- [X] T020 [US1] Add CLI tests to `backend/tests/test_exports.py`. Running
  `scripts/export_annotations.py` produces a valid file, and a missing `--db` returns exit code 1
  with an error on stderr.
- [X] T021 [US1] Create `backend/scripts/export_annotations.py`:
  - argparse `--format csv|json`, `--output FILE`, `--db` (default `DEFAULT_DB`),
    `--include-rejected`, and `--history`
  - opens with `connect_database(must_exist=True)`
  - mirrors the `sys.path` and error-handling style of `backend/scripts/load_engagement.py`

**Checkpoint**: US1 is fully functional and testable on its own.

---

## Phase 4: User Story 2 - Reviewer confirms or corrects a suggestion (P1)

**Goal**: Accept, Edit, Reject, and Defer update the current state and append exactly one history
event, atomically, following the source and status rules.

**Independent Test**: Apply each action to fixture annotations. Assert value, source, status, and
confidence, and that exactly one ReviewEvent is added.

### Tests for US2

- [X] T022 [P] [US2] Write `backend/tests/test_review_actions.py` for Accept, Reject, and Defer:
  - from UNREVIEWED, each sets its status, leaves source AI, leaves label, span, and confidence
    unchanged, and writes one event with matching prev/new values
  - Accept on a HUMAN/EDITED annotation keeps HUMAN
  - Defer stores the note
- [X] T023 [US2] Add Edit cases, and the full transition matrix, to
  `backend/tests/test_review_actions.py`:
  - **Transition matrix (SC-003, FR-014)**: one `pytest.mark.parametrize` test over every
    reachable starting state × every action. The starting states are those listed in
    `specs/001-annotation-data-model/data-model.md`:
    - AI/UNREVIEWED
    - AI/ACCEPTED, AI/REJECTED, AI/DEFERRED
    - HUMAN/ACCEPTED, HUMAN/EDITED, HUMAN/REJECTED, HUMAN/DEFERRED

    The actions are Accept, Edit-with-change, no-op Edit, Reject, and Defer. Set up each state
    through `insert_ai_annotation` plus real review calls. For each case, assert the resulting
    `source`, `review_status`, and confidence against the transition table, and that exactly one
    ReviewEvent was appended. No case expects UNREVIEWED as a result.
  - a label change sets source HUMAN, status EDITED, and confidence None, and the event records
    `prev_confidence` as the original
  - a span-only change and a person change (including to None) each count as an edit
  - an edit that changes nothing is recorded as ACCEPTED with source unchanged
  - editing a REJECTED annotation makes it EDITED and visible again
- [X] T024 [US2] Add validation cases to `backend/tests/test_review_actions.py`. Each of the
  following raises `DataError` and leaves both Annotation and ReviewEvent unchanged (FR-015):
  - a cross-category label edit
  - an edit to a deactivated label
  - a reversed span
  - a span ending at or beyond `round(duration × fps)`
  - an unknown `person_id`
  - a blank or whitespace `reviewer_id`

  An unknown `annotation_id` raises `LookupError`.

  Positive case (R14): an annotation whose label has since been deactivated can be given a
  span-only or participant-only edit. It keeps that deactivated label and becomes HUMAN/EDITED.
- [X] T025 [US2] Add a concurrency case to `backend/tests/test_review_actions.py`. Two
  connections act on the same annotation in sequence, and the second event's prev values equal
  the first event's new values.

### Implementation for US2

- [X] T026 [US2] Implement private helpers in `backend/analysis_db/review.py`:
  - `_require_reviewer(reviewer_id)` rejects blank values and passes the ID through unmodified
    (FR-036)
  - `_validate_span(conn, video_id, start, end)` (FR-026, R2)
  - `_require_active_label(conn, label_id, category=None)`
  - `_now()` returns an ISO-8601 UTC string
  - public functions in `review.py`, `labels.py`, and `annotations.py` begin with
    `assert_schema(conn, tables=REVIEW_TABLES)`
- [X] T027 [US2] Implement `_apply(conn, annotation_id, action, changes, reviewer_id, note)` in
  `backend/analysis_db/review.py`:
  - opens `BEGIN IMMEDIATE`
  - re-reads the row (`LookupError` if missing)
  - computes the new state per the transition table in data-model.md
  - updates Annotation, inserts one ReviewEvent, and commits
  - rolls back on any exception (R5)
- [X] T028 [US2] Implement the public `accept`, `reject`, `defer`, and `edit` functions in
  `backend/analysis_db/review.py` on top of `_apply`. Each returns `(Annotation, ReviewEvent)`.
  `edit` takes `AnnotationChanges` and turns a no-op into ACCEPTED. When the label changes, it
  rejects a different category or an inactive label. A span- or person-only edit keeps the current
  label even if it's deactivated (R14). It never modifies the linked clip (R13).

**Checkpoint**: US1 and US2 both work independently.

---

## Phase 5: User Story 4 - Existing analysis is carried over (P1)

**Goal**: Running `init_db.py` on the current database adds the review model without changing any
existing row. Identity reclustering is blocked once review data exists.

**Independent Test**: Migrate a copy of `data/analysis.sqlite` twice. Counts and sampled scores are
unchanged, Label has 18 rows, and the new tables are empty.

### Tests for US4

- [X] T029 [P] [US4] Add migration tests to `backend/tests/test_review_schema.py`:
  - build a database with only the original six tables (by executing the pre-feature subset of the
    schema, or by creating it from a fixture), insert sample Video, Person, FaceDetection,
    Activity, and Engagement rows, then run `initialize_database` twice
  - the original rows are byte-identical, Label has 18 rows, and the new tables are empty
  - **atomic failure (FR-025)**: copy `backend/db/schema.sql` to `tmp_path`, replace its final
    `COMMIT;` with a deliberately invalid statement followed by `COMMIT;`, and point
    `analysis_db.storage.SCHEMA_PATH` at the copy with `monkeypatch.setattr`. Run
    `initialize_database` on the six-table database, assert it raises `sqlite3.Error`, and assert
    that `sqlite_master` and all original rows are exactly as before (no review tables, triggers,
    or labels)
- [X] T030 [US4] Add a real-data test to `backend/tests/test_review_schema.py`. Copy
  `../data/analysis.sqlite` to `tmp_path`, migrate it, and assert Video 12, Person 100,
  FaceDetection 50514, and Engagement 50514, with all Engagement scores equal to the original. Skip
  when the file is absent (SC-001, SC-006).
- [X] T031 [P] [US4] Add guard tests to `backend/tests/test_identity_tables.py`.
  `replace_identity_tables` raises `DataError` naming annotations or clips when any Annotation or
  ReviewClip row exists, and the database is unchanged. With no review rows, existing behavior is
  unchanged. On a database with only the six original tables (no review tables), replacement still
  succeeds.

### Implementation for US4

- [X] T032 [P] [US4] Add regression tests for existing loaders, which need no code change:
  - in `backend/tests/test_engagement_table.py`, `replace_engagement` works on a migrated database
    and on a six-table-only database
  - in `backend/tests/test_ingestion.py`, ingesting one CSV works on a six-table-only database
    (H1)
- [X] T033 [US4] Add the review-data guard at the start of `replace_identity_tables` in
  `backend/analysis_db/identity_tables.py`. Refuse with a clear `DataError` if `Annotation` or
  `ReviewClip` has rows, checking only the tables present in `sqlite_master` (R9).

**Checkpoint**: All P1 stories are done. This is the demoable MVP.

---

## Phase 6: User Story 3 - Audit how a record reached its current state (P2)

**Goal**: The full history is readable in order and exportable. The original AI value is
recoverable.

**Independent Test**: Run three actions on one annotation, then rebuild its timeline from
`get_history` alone.

- [X] T034 [P] [US3] Write history tests in `backend/tests/test_review_actions.py`:
  - three actions give three events in chronological order
  - the first event's `prev_label_id` and `prev_confidence` equal the original AI values (SC-002)
  - earlier events are unchanged after later actions
- [X] T035 [US3] Implement `get_history(conn, annotation_id) -> list[ReviewEvent]` (ordered by
  `event_id`) in `backend/analysis_db/review.py`
- [X] T036 [P] [US3] Add history-export tests to `backend/tests/test_exports.py`. The CSV and JSON
  columns match the "Review history" section of
  `specs/001-annotation-data-model/contracts/export-format.md`, ordered by `event_id`.
- [X] T037 [US3] Implement `export_history(conn, out, fmt)` in `backend/analysis_db/exports.py`, and
  wire `--history` in `backend/scripts/export_annotations.py`

---

## Phase 7: User Story 5 - Staff manage their own labels (P2)

**Goal**: Create, rename, describe, and deactivate or reactivate labels. Labels can never be
deleted.

**Independent Test**: Label CRUD-minus-delete on a fresh database. Annotations follow renames.

- [X] T038 [P] [US5] Write `backend/tests/test_labels.py`:
  - `create_label` returns a new ID, and a duplicate name in the same category (case-insensitive)
    raises `DataError`
  - the same name in the other category is allowed
  - `update_label` rename is reflected in `list_annotations` output
  - `set_label_active(False)` hides the label from `list_labels()` by default, but existing
    annotations still show it
  - a blank name or invalid category raises `DataError`
- [X] T039 [US5] Implement `list_labels`, `create_label`, `update_label`, and `set_label_active` in
  `backend/analysis_db/labels.py`, per contracts/python-api.md. There is no delete function.

---

## Phase 8: User Story 7 - Pipeline output never overwrites human work (P2)

**Goal**: `import_machine_output` upserts by `import_key` and updates only AI/UNREVIEWED rows.
It never creates duplicates.

**Independent Test**: Import, review some annotations, then re-import changed output. Reviewed
rows are unchanged, unreviewed rows are updated, and the counts add up.

### Tests for US7

- [X] T040 [P] [US7] Write `backend/tests/test_machine_import.py`:
  - the first import inserts with source AI, status UNREVIEWED
  - re-importing identical input inserts 0 and creates no duplicates (FR-019)
  - re-importing a changed label or confidence for an UNREVIEWED row updates it in place, and it
    stays AI/UNREVIEWED
  - after accept, edit, reject, or defer, a re-import leaves that row byte-identical and counts it
    in `skipped_protected` (SC-004)
  - HUMAN-created rows (NULL `import_key`) are never touched
  - an UNREVIEWED annotation missing from a later import is kept unchanged, because imports never
    delete (R3)
  - an inactive `label_id`, an invalid span, or a missing `import_key` in input raises `DataError`,
    and the whole import is rolled back

### Implementation for US7

- [X] T041 [US7] Implement annotation upsert inside `import_machine_output(conn, video_id, clips, annotations)`
  in `backend/analysis_db/annotations.py`:
  - one `BEGIN IMMEDIATE` transaction
  - `INSERT … ON CONFLICT(import_key) DO UPDATE SET … WHERE source='AI' AND review_status='UNREVIEWED'`
  - validates labels and spans first
  - computes the inserted, updated, and skipped_protected counts into `ImportResult` (R3)

---

## Phase 9: User Story 8 - Reviewers work through review clips (P2)

**Goal**: Store clips with participant sets and priority scores, query them three ways, link
annotations to them, and protect reviewed clips on replacement.

**Independent Test**: Import sample clips and annotations, then list clips by time, by priority,
and by participant. Replace clips and confirm reviewed ones survive.

### Tests for US8

- [X] T042 [P] [US8] Add clip tests to `backend/tests/test_machine_import.py`:
  - clips import with their participant set, including an empty set, plus score and method
  - re-importing upserts by clip `import_key`
  - an annotation's `clip_import_key` resolves to `clip_id`
  - a clip-level annotation whose span differs from its clip raises `DataError`
  - an annotation whose clip belongs to another video raises `DataError` (R13)
  - re-importing changed clip data updates unprotected clips in place, but leaves a clip that holds
    a protected annotation byte-identical (span, score, method, participants) and counts it in
    `skipped_protected` (FR-034, R12)
  - a clip missing from a later import is kept, with its annotations. Nothing is deleted.
- [X] T043 [P] [US8] Add clip query tests to `backend/tests/test_annotation_queries.py`:
  - `list_clips(order="time")` sorts by video, then start frame
  - `order="priority"` sorts highest first with NULL scores last, across videos
  - `person_id=` returns every clip containing that person
  - a score above 1 (for example 2.07) is returned unchanged
  - reviewing a clip annotation doesn't change the clip's score (FR-033)
  - editing a clip-level annotation's span, or giving it a participant, succeeds, and the clip row
    and participant set are unchanged (R13)
  - `list_annotations(clip_id=…)` works

### Implementation for US8

- [X] T044 [US8] Extend `import_machine_output` in `backend/analysis_db/annotations.py` to:
  - upsert clips by `import_key`, skipping any clip that holds a protected annotation
  - replace `ReviewClipParticipant` rows only for clips that were updated
  - resolve `clip_import_key`
  - validate the same-video rule for every clip-linked annotation, and the span rule for
    clip-level annotations (R13)
  - never delete clips or annotations (R12)
- [X] T045 [US8] Implement `list_clips(conn, *, video_id=None, person_id=None, order="time")` in
  `backend/analysis_db/annotations.py`. It returns `ReviewClip` with the `person_ids` tuple and
  derived seconds, and uses `ORDER BY priority_score IS NULL, priority_score DESC` for priority.

---

## Phase 10: User Story 6 - Reviewer adds a moment the machine missed (P3)

**Goal**: Create produces a HUMAN/ACCEPTED annotation with no confidence and a CREATED event.

**Independent Test**: Create an annotation, check its fields and history, and find it by video
and by participant.

**Depends on**: T026–T027 (review helpers and transaction pattern).

- [X] T046 [P] [US6] Add Create tests to `backend/tests/test_review_actions.py`:
  - the result has source HUMAN, status ACCEPTED, and confidence None, with an `import_key` of
    NULL
  - one CREATED event has all prev_* NULL plus `reviewer_id` and note
  - an inactive label, an invalid span, a blank `reviewer_id`, or a `clip_id` from another video
    raises and stores nothing
  - a later edit, reject, or defer follows the normal rules
  - the annotation is returned by `list_annotations` for its video and participant
- [X] T047 [US6] Implement `create_annotation(conn, *, video_id, label_id, start_frame, end_frame, reviewer_id, person_id=None, clip_id=None, note=None)`
  in `backend/analysis_db/review.py`. It inserts the annotation and the CREATED event in one
  `BEGIN IMMEDIATE` transaction. When `clip_id` is given, it enforces the same-video rule, and
  the clip-level span rule if there is no person (R13).

---

## Phase 11: Polish & cross-cutting

- [X] T048 [P] Add a performance check to `backend/tests/test_annotation_queries.py`. Insert about
  50,000 annotations and 5,000 clips, then assert that `list_annotations(video_id=…, start_frame…)`,
  `list_annotations(person_id=…)`, and `list_clips(order="priority")` each finish in under 1 s
  (SC-005, SC-008).
- [X] T049 [P] Update `backend/README.md` with:
  - the review model overview (current state vs. append-only history; `source` vs.
    `review_status`)
  - the migration command (`uv run python scripts/init_db.py`, idempotent)
  - the export command
  - a note that `Activity` and `Engagement` are raw machine signals
  - a note that identity replacement is blocked once review data exists
- [X] T050 Run every step in `specs/001-annotation-data-model/quickstart.md` against a copy of
  `data/analysis.sqlite` (outside the repo) and confirm each expected outcome
- [X] T051 Run `uv run pytest -q` in `backend/` and confirm the full suite passes. Run
  `git status` and confirm `data/analysis.sqlite` was not modified by tests.

---

## Dependencies & Execution Order

### Phase dependencies

- Setup (T001) → Foundational (T002–T013) → all user stories
- US1, US2, US4, US5, and US7 depend only on Foundational
- US3 depends on US2 (it reads the events US2 writes; T035 needs T027)
- US8 depends on US7 (`import_machine_output` from T041)
- US6 depends on US2's helpers (T026–T027)
- Polish depends on all stories

### Within each story

Write the tests first and confirm they fail, then implement until they pass. Tasks in the same
file run sequentially.

### Story completion order

```text
Foundational ─┬─ US1 (MVP) ─────────────┐
              ├─ US2 ─┬─ US3            │
              │       └─ US6            ├─ Polish
              ├─ US4                    │
              ├─ US5                    │
              └─ US7 ── US8 ────────────┘
```

## Parallel Opportunities

- Foundational: T011 and T012 (different test files) can be written in parallel after T002–T010,
  followed by T013.
- US4: T032 (loader regression tests in other files) can run in parallel with T029–T031.
- After Foundational: US1, US2, US4, US5, and US7 can proceed in parallel. They touch different
  modules (`annotations.py` query part, `review.py`, `identity_tables.py`, `labels.py`,
  `annotations.py` import part). US1 and US7 share `annotations.py`, so sequence T017 before T041
  if one person does both.
- Test-writing tasks marked [P] within a story can run in parallel when they're in different
  files. Same-file test tasks (for example T022–T025) are written one after another.

### Example: US2 in parallel with US5

```text
Dev A: T022 → T023 → T024 → T025 → T026 → T027 → T028   (review.py)
Dev B: T038 → T039                                     (labels.py)
```

## Implementation Strategy

### MVP (P1 stories)

1. Phases 1–2: schema, safeguards, seeds, types, fixtures.
2. US1: queries and export.
3. US2: review actions.
4. US4: verified migration and identity guard.
5. **Stop and validate.** Run quickstart steps 1–2 on a database copy. This is a demoable data
   layer.

### Incremental delivery

US3 (audit) → US5 (labels) → US7 (protected import) → US8 (clips, ready for the pipeline spec) →
US6 (create) → Polish.

---

## Phase 12: Convergence

- [X] T052 Count a protected annotation as `skipped_protected` even when the re-imported values are identical. In `_import_annotation` in `backend/analysis_db/annotations.py`, check `source`/`review_status` before the "unchanged" shortcut. Add a test to `backend/tests/test_machine_import.py` that accepts an annotation, re-imports identical input, and expects `skipped_protected == 1`. Per FR-019 / contracts/python-api.md (partial)
- [X] T053 Make an identical clip re-import a no-op. In `_import_clip` in `backend/analysis_db/annotations.py`, skip the UPDATE and the participant rewrite when the span, score, method, and participant set are unchanged, and don't count it in `clips_updated`. Add a test to `backend/tests/test_machine_import.py`. Per FR-034 / research.md R12 (partial)
- [X] T054 Update the `import_machine_output` row in `specs/001-annotation-data-model/contracts/python-api.md` to list the six `ImportResult` counters actually returned: `inserted`, `updated`, `skipped_protected`, `clips_inserted`, `clips_updated`, `clips_skipped_protected`. Per contracts/python-api.md (partial)
- [X] T055 Either document `fetch_annotation(conn, annotation_id) -> Annotation` (raises `LookupError`) in the Queries table of `specs/001-annotation-data-model/contracts/python-api.md`, or rename it to `_fetch_annotation` in `backend/analysis_db/annotations.py` and `backend/analysis_db/review.py`. Per contracts/python-api.md (unrequested)
- [X] T056 Stop `backend/scripts/export_annotations.py` from leaving a truncated output file when an export fails: write to a temporary file in the same directory and rename it on success. Add a CLI test to `backend/tests/test_exports.py` that runs against a database without review tables, then asserts exit code 1 and that no output file exists. Per Constitution IX (partial)

---

## Phase 13: Convergence

- [X] T057 Skip protected annotations before validating incoming machine data. In `_import_annotation` in `backend/analysis_db/annotations.py`, move the existing-row lookup by `import_key` and the protection check (`source`/`review_status` not AI/UNREVIEWED, so return "protected") ahead of the active-label, span, participant, and clip validations. Those validations then apply only to new or update-eligible rows. Add a test to `backend/tests/test_machine_import.py`: import, accept, deactivate the label, then re-import the same input together with one new valid annotation. Expect no exception, `skipped_protected == 1`, `inserted == 1`, and the reviewed row byte-identical. Per FR-019 / research.md R3 (partial)
