# Research: Review and Annotation Data Model

All Technical Context unknowns are resolved below. No new dependencies are introduced.

## R1. Migration strategy

- **Decision**: Additive schema. Append the new tables, indexes, triggers, and label seeds to
  `backend/db/schema.sql` using `CREATE … IF NOT EXISTS` and `INSERT OR IGNORE`. Running the
  existing `scripts/init_db.py` against the current database *is* the migration. The existing
  `Activity` and `Engagement` tables already hold per-detection machine output, so they stay
  unchanged and are formally treated as the machine-signal tables (FR-022, FR-024).
- **Rationale**: Nothing moves, so nothing can be lost (SC-001). `schema.sql` already runs in one
  `BEGIN … COMMIT` script through `initialize_database`, so the migration is all-or-nothing
  (FR-025) and idempotent (SC-006). The constitution keeps `schema.sql` as the only schema
  definition (Principle V).
- **Alternatives considered**: Alembic or another migration framework would add a dependency and
  is overkill for additive tables. Renaming `Activity`/`Engagement` to `*Signal` would break
  `engagement_table.py`, `identity_tables.py`, notebooks, and tests for no functional gain. Copying
  scores into a new signal table would duplicate data.
- **Idempotency**: Every new table, index, and trigger uses `IF NOT EXISTS`, and seeds use
  `INSERT OR IGNORE`, so a second run is a no-op.
- **Schema check**: `assert_schema(connection, tables=TABLES)` keeps its current default (the six
  ingestion tables), so ingestion, engagement loading, and identity replacement keep working on
  databases that have not been migrated. The new review modules call
  `assert_schema(connection, tables=REVIEW_TABLES)`.
- **Limit**: This works only while changes stay additive. The first non-additive change needs a
  versioned migration step (for example `PRAGMA user_version`), which is deferred until needed.

## R2. Annotation time representation

- **Decision**: Store `start_frame`/`end_frame` as inclusive integer frame indices. Derive
  seconds as `frame / Video.fps` at read time. The upper bound is
  `end_frame < round(duration_seconds × fps)`, checked in Python when both values are known.
  Otherwise only the lower bound and ordering are enforced.
- **Rationale**: Existing data is frame-accurate. All 12 videos have fps (23.976) and duration.
  Derived seconds can't drift from frames.
- **Alternatives**: Storing seconds too would duplicate data and risk drift.

## R3. Deterministic import identity (FR-019, FR-034)

- **Decision**: `Annotation.import_key` and `ReviewClip.import_key` are nullable `TEXT UNIQUE`.
  Machine imports MUST supply them. Human-created annotations have `NULL`. The pipeline
  constructs the key from stable inputs that do not include the predicted value (for example
  `"{method}:{video_id}:{clip_key}:{participant or '-'}:{label category}:{slot}"`), so a new
  prediction for the same slot updates rather than duplicates.
- **Upsert**:
  `INSERT … ON CONFLICT(import_key) DO UPDATE SET … WHERE source = 'AI' AND review_status = 'UNREVIEWED'`.
  The `WHERE` makes protection a database rule rather than a convention. Protected rows are
  silently skipped and counted.
- **No deletion**: Imports only insert or update. Unreviewed annotations and clips missing from a
  later import are not deleted in Spec 001. Constitution Principle IX requires an explicit,
  confirmed user action for deletions, and removal is left to the clip pipeline spec.
- **Alternatives**: Matching on (video, span, participant, label) breaks when the model changes the
  label, and creates duplicates.

## R4. History immutability (FR-017)

- **Decision**: SQLite triggers `BEFORE UPDATE` and `BEFORE DELETE` on `ReviewEvent` that
  `RAISE(ABORT, 'review history is append-only')`. `ReviewEvent` foreign keys use no
  `ON DELETE CASCADE`, so deleting an annotation or video that has history is refused.
- **Rationale**: Enforced for every client, including notebooks and ad hoc SQL through the
  normal connection, and costs two statements.
- **Alternatives**: Convention only (no enforcement). A separate append-only file (an extra
  storage mechanism).

## R5. Atomic review actions and concurrency (FR-015, concurrent-review edge case)

- **Decision**: Each review function opens `BEGIN IMMEDIATE`, re-reads the current row, validates,
  updates the row, inserts the `ReviewEvent`, and commits. Any error rolls back.
- **Rationale**: `BEGIN IMMEDIATE` takes the write lock before reading, so two reviewers are
  serialized and the second sees the first's result as its "previous" value.

## R6. Confidence on human edit

- **Decision**: Edit and Create set `confidence = NULL` on the current record. `ReviewEvent` stores
  `prev_confidence` and `new_confidence`. Accept, Reject, and Defer keep confidence.
- **Rationale**: A model's confidence describes the model's value, so showing it next to a
  human-chosen label would misstate it (Principle IV). History keeps the original value
  recoverable (FR-017). "Original" is the AI value at the first human review, because automated
  re-imports write no history.

## R7. Labels

- **Decision**: `label_id INTEGER PRIMARY KEY`. The 18 starter labels are seeded with fixed IDs
  1–18 via `INSERT OR IGNORE`. `UNIQUE(category, name COLLATE NOCASE)`. There is no delete path in
  code, and a `BEFORE DELETE` trigger refuses deletes (FR-008). Category is `CHECK`-constrained to
  `activity` and `observation`.
- **Rationale**: Fixed seed IDs make the seeds idempotent and stable across machines.

## R8. Rules that live in Python, not SQL

The following are application rules in `analysis_db/review.py`, covered by tests:

- An edit keeps the label within its category.
- Deactivated labels can't be newly applied.
- A no-op edit becomes Accept.
- The span is validated against video length.

Expressing these as triggers would be harder to read and test.

## R9. Identity-replacement guard

- **Decision**: `replace_identity_tables` (which deletes and reloads `Person`/`FaceDetection`)
  MUST refuse with a `DataError` when any `Annotation` or `ReviewClip` row exists. The check runs
  only for review tables present in `sqlite_master`, so databases that have not been migrated
  keep their current behavior. Re-clustering
  would silently reassign anonymous IDs under reviewed work.
- **Rationale**: Foreign keys would already abort the load, but with an unclear message. An
  explicit check gives a clear one.

## R10. Exports (FR-027, FR-028)

- **Decision**: Use stdlib `csv` and `json`, through functions in `analysis_db/exports.py` and a
  thin `scripts/export_annotations.py`. CSV is UTF-8 with a header. JSON is an array of objects.
  Both use the same field names ([contracts/export-format.md](contracts/export-format.md)).

## R11. `reviewer_id` (FR-036)

- **Decision**: `TEXT NOT NULL CHECK (length(trim(reviewer_id)) > 0)` on `ReviewEvent`. It is
  passed through unmodified and never parsed.

## R12. Clip re-import (FR-034)

- **Decision**: `import_machine_output(video_id, clips, annotations)` runs in one transaction and
  only inserts or updates, by `import_key`.
  - A clip that holds any protected annotation (status not UNREVIEWED) is left untouched: its
    span, score, method, and participant set.
  - Other clips are updated in place.
  - No clip or annotation is ever deleted by an import.
- **Rationale**: Constitution Principle IX requires an explicit, confirmed user action to delete
  annotations. FR-034 only forbids altering protected clips. Clip replacement and removal belong
  to the later clip pipeline spec.

## R13. Clip-linked annotations after review

- **Decision**: An annotation's clip MUST be in the same video, checked at import, Create, and
  whenever `clip_id` is set. The clip-level span-equals-clip rule is checked only at import and
  Create. An Edit MAY move a clip-linked annotation's span or participant away from the clip. The
  clip records the review context that surfaced the annotation, and after a human edit the
  annotation's current state is authoritative. Edits never modify the clip.

## R14. Deactivated labels during Edit

- **Decision**: Edit checks that the label is active only when `changes.label_id` is set and
  differs from the current label. A span-only or participant-only edit keeps an existing
  deactivated label.
