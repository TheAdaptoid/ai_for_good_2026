# Contract: Python API (`backend/analysis_db`)

This is the interface the future FastAPI layer, the clip pipeline, and notebooks will call.
Public types live in `analysis_db/contracts.py` (constitution Principle X). All functions take an
open `sqlite3.Connection` from `connect_database()`, which must be idle (not in a transaction).
They raise `DataError` for invalid input or rule violations, and `LookupError` for missing IDs.
Every write is all-or-nothing. New modules validate with
`assert_schema(conn, tables=REVIEW_TABLES)`. The default `assert_schema(conn)` still checks only
the six ingestion `TABLES`.

## Types (`analysis_db/contracts.py`)

```python
class Source(StrEnum): AI = "AI"; HUMAN = "HUMAN"
class ReviewStatus(StrEnum): UNREVIEWED, ACCEPTED, EDITED, REJECTED, DEFERRED
class ReviewAction(StrEnum): CREATED, ACCEPTED, EDITED, REJECTED, DEFERRED
class LabelCategory(StrEnum): ACTIVITY = "activity"; OBSERVATION = "observation"

@dataclass(frozen=True) class Label: label_id, name, category, description, is_active
@dataclass(frozen=True) class Annotation:
    annotation_id, video_id, clip_id, person_id, label_id, label_name, label_category,
    start_frame, end_frame, start_seconds, end_seconds,  # seconds None if fps unknown
    confidence, source, review_status, created_at, updated_at
@dataclass(frozen=True) class ReviewClip:
    clip_id, video_id, start_frame, end_frame, start_seconds, end_seconds,
    person_ids: tuple[str, ...], priority_score, priority_method, created_at
@dataclass(frozen=True) class ReviewEvent: (all ReviewEvent columns, see data-model.md)

# Pipeline input (no IDs; identity via import_key)
@dataclass(frozen=True) class ClipInput:
    import_key, start_frame, end_frame, person_ids, priority_score=None, priority_method=None
@dataclass(frozen=True) class AnnotationInput:
    import_key, label_id, start_frame, end_frame, confidence,
    person_id=None, clip_import_key=None
@dataclass(frozen=True) class AnnotationChanges:  # for Edit; None = leave unchanged
    label_id=None, start_frame=None, end_frame=None, person_id=UNSET  # UNSET vs explicit None
```

## Labels (`analysis_db/labels.py`)

| Function | Behavior |
|---|---|
| `list_labels(conn, *, category=None, include_inactive=False) -> list[Label]` | |
| `create_label(conn, name, category, description=None) -> Label` | Duplicate name within the category raises `DataError` |
| `update_label(conn, label_id, *, name=None, description=None) -> Label` | Annotations follow automatically (FR-007) |
| `set_label_active(conn, label_id, active: bool) -> Label` | Deactivate or reactivate. There is no delete function |

## Review actions (`analysis_db/review.py`)

All of these require a non-empty `reviewer_id: str` and accept `note: str | None`. Each returns
`(Annotation, ReviewEvent)`.

| Function | Rules |
|---|---|
| `create_annotation(conn, *, video_id, label_id, start_frame, end_frame, reviewer_id, person_id=None, clip_id=None, note=None)` | HUMAN, ACCEPTED, no confidence. Event CREATED |
| `accept(conn, annotation_id, *, reviewer_id, note=None)` | |
| `edit(conn, annotation_id, changes: AnnotationChanges, *, reviewer_id, note=None)` | A no-op edit is recorded as ACCEPTED. A label change must stay in the same category and use an active label. A span- or person-only edit keeps an existing deactivated label. Never modifies the linked clip |
| `reject(conn, annotation_id, *, reviewer_id, note=None)` | |
| `defer(conn, annotation_id, *, reviewer_id, note=None)` | |
| `get_history(conn, annotation_id) -> list[ReviewEvent]` | Chronological order |

## Queries (`analysis_db/annotations.py`)

| Function | Behavior |
|---|---|
| `list_annotations(conn, *, video_id=None, start_frame=None, end_frame=None, person_id=None, label_id=None, category=None, source=None, review_status=None, clip_id=None, include_rejected=False) -> list[Annotation]` | Time filter returns annotations that overlap `[start_frame, end_frame]`. Ordered by video, then start frame |
| `list_clips(conn, *, video_id=None, person_id=None, clip_id=None, order="time" \| "priority", limit=None) -> list[ReviewClip]` | `priority`: highest first, unscored last (FR-032). `clip_id` and `limit` were added by Spec 004 |
| `get_clip(conn, clip_id) -> ReviewClip` | One clip by ID. Raises `LookupError` if unknown (Spec 004) |
| `import_machine_output(conn, video_id, clips: Sequence[ClipInput], annotations: Sequence[AnnotationInput]) -> ImportResult` | Inserts or updates by `import_key` only. Never touches protected annotations, or clips holding them. Never deletes anything: rows missing from a later import are kept ([research.md R3, R12](../research.md)). Returns `ImportResult` with annotation and clip outcomes counted separately (see below) |
| `fetch_annotation(conn, annotation_id) -> Annotation` | Returns the current state of one annotation by ID, with label name, category and derived seconds, as `list_annotations` builds it. Applies **no** default filtering: REJECTED annotations are returned too, because it reads by ID. Raises `LookupError` if the ID doesn't exist. Used by `review.py` to return the post-action state |

`ImportResult` (all `int`, default 0):

| Field | Counts |
|---|---|
| `inserted` | New AI/UNREVIEWED annotations |
| `updated` | Existing AI/UNREVIEWED annotations whose values changed |
| `skipped_protected` | Annotations not touched because they've been reviewed (status not UNREVIEWED or source HUMAN), even when the incoming values are identical |
| `clips_inserted` | New clips |
| `clips_updated` | Unprotected clips whose span, score, method, or participant set changed |
| `clips_skipped_protected` | Clips not touched because they hold a reviewed annotation |
| `unchanged` | Eligible annotations identical to what's stored: not written (added by Spec 004) |
| `clips_unchanged` | Eligible clips identical to what's stored: not written (added by Spec 004) |

Errors raised for one record are prefixed with its key, for example `annotation 'k1': …`.
Multi-video, all-or-nothing file imports are in Spec 004's `analysis_db/pipeline_import.py`.

## Exports (`analysis_db/exports.py`)

| Function | Behavior |
|---|---|
| `export_annotations(conn, out: TextIO, fmt: "csv" \| "json", *, include_rejected=False, **filters)` | Fields per [export-format.md](export-format.md) |
| `export_history(conn, out: TextIO, fmt: "csv" \| "json")` | |

## CLI

- `uv run python scripts/init_db.py [--db PATH]` creates the database, or migrates an existing one.
  It is idempotent.
- `uv run python scripts/export_annotations.py --format csv|json [--history] [--include-rejected] [--db PATH] --output FILE`
