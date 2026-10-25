# Implementation Plan: Review and Annotation Data Model

**Branch**: `001-annotation-data-model` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-annotation-data-model/spec.md`

## Summary

Add the current-state annotation model, staff-managed labels, review clips, and an append-only
review history to the existing SQLite analysis database. Also add a Python API for review actions,
queries, machine-output import, and JSON/CSV export.

The migration is purely additive. New tables, triggers, and label seeds are appended to
`backend/db/schema.sql`, and running the existing `scripts/init_db.py` applies them. The existing
`Activity` and `Engagement` tables already hold per-detection machine output, so they stay unchanged
as the machine-signal tables. Nothing is copied or converted, so nothing can be lost.

Database-level rules make the key guarantees hold for every client:
- `CHECK` constraints on `source` and `review_status`
- append-only triggers on history
- a guarded upsert that cannot touch reviewed rows

## Technical Context

**Language/Version**: Python 3.13 (`backend/`, `requires-python >=3.13,<3.14`)

**Primary Dependencies**: Standard library only (`sqlite3`, `csv`, `json`, `dataclasses`, `enum`).
No new dependencies.

**Storage**: SQLite at `data/analysis.sqlite`, with `backend/db/schema.sql` as the only schema
definition

**Testing**: pytest (existing `backend/tests/`, `uv run pytest -q`)

**Target Platform**: Local team laptops (macOS/Linux), offline

**Project Type**: Library package plus CLI scripts inside the backend of a web application
(FastAPI and React come in later features)

**Performance Goals**: Video, time, participant, and priority queries on the migrated dataset
return in under 1 s (SC-005, SC-008). Indexes are listed in data-model.md.

**Constraints**: The migration must be all-or-nothing and idempotent. There is no network access,
no cloud services, and no raw media is touched.

**Scale/Scope**: 12 videos, 100 participants, 50,514 detections, and up to tens of thousands of
annotations and clips

No NEEDS CLARIFICATION items remain. Decisions are in [research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan complies |
|---|---|---|
| I. Local-only sensitive media | ✅ | Only derived records. No media read or written, no network. The `analysis.sqlite` publication TODO is unaffected |
| II. Anonymous identity | ✅ | Keeps existing anonymous `person_id`. No identity fields added. Identity-replacement guard protects reviewed links (R9) |
| III. Data minimization | ✅ | No new personal or biometric fields. Affect labels are observational names only |
| IV. Humans decide | ✅ | Confidence, priority score, and review status are separate columns. Confidence is cleared on human edit (R6). Priority score is unbounded and never a percentage |
| V. Current state + history | ✅ | One `Annotation` table. `source` and `review_status` are CHECK-constrained. Atomic action + event (R5). Triggers make history immutable (R4). Guarded upsert (R3). Rejected rows hidden by default. Schema stays in `schema.sql`. Migration is all-or-nothing |
| VI. Multi-label model | ✅ | One label per row, many rows per moment. Activity and observation categories. Labels as data, deactivate only |
| VII. Modular monolith | ✅ | New modules in the existing `analysis_db` package. No services. API layer deferred |
| VIII. Secure by default | ✅ | Parameterized SQL only. `reviewer_id` validated non-empty. Export output path chosen by CLI user |
| IX. Visible failure, safe ops | ✅ | All writes are transactional and raise on error. No delete paths at all in Spec 001: labels and history are blocked by triggers, and imports only insert or update (R3, R12). Import reports skipped protected rows |
| X. Tested workflows | ✅ | pytest for every review transition, history immutability, protection, multi-label queries, exports, migration counts (real DB test skips if absent) |
| XI. Reproducible | ✅ | No new dependencies. `uv.lock` unchanged. README updated with migrate/export commands |
| XII. Simple, typed | ✅ | Stdlib only. Frozen dataclasses and StrEnums in `contracts.py`. No migration framework (R1) |

**Gate result: PASS** (pre-research and post-design). No violations, so Complexity Tracking is
empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-annotation-data-model/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── python-api.md
│   └── export-format.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── db/schema.sql                  # + Label, ReviewClip, ReviewClipParticipant, Annotation,
│                                  #   ReviewEvent, indexes, triggers, 18 label seeds
├── analysis_db/
│   ├── contracts.py               # + REVIEW_TABLES, enums, dataclasses
│   ├── storage.py                 # assert_schema(conn, tables=TABLES) param; review_table_counts
│   ├── identity_tables.py         # + refuse replacement when annotations/clips exist (R9),
│                                  #   checked only if those tables exist
│   ├── labels.py                  # new
│   ├── review.py                  # new: create/accept/edit/reject/defer/get_history
│   ├── annotations.py             # new: list_annotations, list_clips, import_machine_output
│   └── exports.py                 # new: CSV/JSON export
├── scripts/
│   ├── init_db.py                 # unchanged logic; doubles as migration; help text updated
│   └── export_annotations.py      # new
├── tests/
│   ├── test_review_schema.py      # constraints, triggers, seeds, migration of real DB copy
│   ├── test_labels.py
│   ├── test_review_actions.py
│   ├── test_annotation_queries.py
│   ├── test_machine_import.py
│   └── test_exports.py
└── README.md                      # + migrate, review model, export sections
```

**Structure Decision**: Extend the existing `backend/analysis_db` package, which already owns the
schema, connections, and loaders. A separate package would have to duplicate connection and schema
handling.

`TABLES` stays as the six ingestion tables. It is used for:

- `assert_schema`'s default presence check
- `table_counts` and `zero_counts`, which feed ingestion stats and `ingest.py`'s "Table counts:"
  output
- the no-image-path schema test

Nothing asserts that the database has exactly six tables. The new `REVIEW_TABLES` is separate,
and `assert_schema` keeps its default, so ingestion works unchanged on databases that haven't been
migrated. The existing six-table count assertions in `test_cli.py` (ingest output) and
`test_storage.py` stay unchanged. `init_db.py` output gains review-table counts, which get a new
test.

## Complexity Tracking

No violations.
