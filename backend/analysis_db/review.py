"""Human review actions. Each one updates the current annotation and appends exactly one
ReviewEvent in a single BEGIN IMMEDIATE transaction, so concurrent reviewers are serialized.
"""

import sqlite3

from analysis_db.annotations import (
    _label_category, _now, _require_person, _validate_clip_link, _validate_span,
    fetch_annotation,
)
from analysis_db.contracts import (
    REVIEW_TABLES, UNSET, Annotation, AnnotationChanges, DataError, ReviewAction,
    ReviewEvent, ReviewStatus, Source,
)
from analysis_db.storage import assert_schema

_EVENT_COLUMNS = (
    "event_id", "annotation_id", "video_id", "action", "prev_label_id", "new_label_id",
    "prev_start_frame", "prev_end_frame", "new_start_frame", "new_end_frame",
    "prev_person_id", "new_person_id", "prev_confidence", "new_confidence", "prev_source",
    "new_source", "prev_status", "new_status", "reviewer_id", "note", "created_at",
)


def _require_reviewer(reviewer_id: object) -> str:
    # Opaque: validated non-empty, never parsed or normalized.
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise DataError("reviewer_id must be a non-empty string")
    return reviewer_id


def _event(row: tuple) -> ReviewEvent:
    values = dict(zip(_EVENT_COLUMNS, row))
    values["action"] = ReviewAction(values["action"])
    values["new_source"] = Source(values["new_source"])
    values["new_status"] = ReviewStatus(values["new_status"])
    if values["prev_source"] is not None:
        values["prev_source"] = Source(values["prev_source"])
    if values["prev_status"] is not None:
        values["prev_status"] = ReviewStatus(values["prev_status"])
    return ReviewEvent(**values)


def _insert_event(connection: sqlite3.Connection, **values) -> int:
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    return connection.execute(
        f"INSERT INTO ReviewEvent ({columns}) VALUES ({marks})", tuple(values.values())).lastrowid


def _fetch_event(connection: sqlite3.Connection, event_id: int) -> ReviewEvent:
    return _event(connection.execute(
        f"SELECT {', '.join(_EVENT_COLUMNS)} FROM ReviewEvent WHERE event_id = ?",
        (event_id,)).fetchone())


def _begin(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        raise DataError("review actions require an idle database connection")
    assert_schema(connection, tables=REVIEW_TABLES)
    connection.execute("BEGIN IMMEDIATE")


def _apply(connection: sqlite3.Connection, annotation_id: int, action: ReviewAction,
           changes: AnnotationChanges | None, reviewer_id: str,
           note: str | None) -> tuple[Annotation, ReviewEvent]:
    reviewer_id = _require_reviewer(reviewer_id)
    _begin(connection)
    try:
        row = connection.execute(
            "SELECT video_id, label_id, start_frame, end_frame, person_id, confidence, source,"
            " review_status FROM Annotation WHERE annotation_id = ?", (annotation_id,)).fetchone()
        if row is None:
            raise LookupError(f"annotation {annotation_id} does not exist")
        video_id, label, start, end, person, confidence, source, status = row
        new_label, new_start, new_end, new_person = label, start, end, person
        new_confidence, new_source = confidence, source
        if action is ReviewAction.EDITED:
            new_label = label if changes.label_id is None else changes.label_id
            new_start = start if changes.start_frame is None else changes.start_frame
            new_end = end if changes.end_frame is None else changes.end_frame
            new_person = person if changes.person_id is UNSET else changes.person_id
            if (new_label, new_start, new_end, new_person) == (label, start, end, person):
                action = ReviewAction.ACCEPTED  # a no-op edit is an acceptance
            else:
                if new_label != label:
                    current = _label_category(connection, label, require_active=False)
                    if _label_category(connection, new_label, require_active=True) != current:
                        raise DataError("an edit cannot change the label's category")
                _validate_span(connection, video_id, new_start, new_end)
                _require_person(connection, new_person)
                new_confidence, new_source = None, Source.HUMAN.value
        new_status = action.value  # every action name doubles as the resulting status
        now = _now()
        connection.execute(
            "UPDATE Annotation SET label_id = ?, start_frame = ?, end_frame = ?, person_id = ?,"
            " confidence = ?, source = ?, review_status = ?, updated_at = ?"
            " WHERE annotation_id = ?",
            (new_label, new_start, new_end, new_person, new_confidence, new_source, new_status,
             now, annotation_id))
        event_id = _insert_event(
            connection, annotation_id=annotation_id, video_id=video_id, action=action.value,
            prev_label_id=label, new_label_id=new_label, prev_start_frame=start,
            prev_end_frame=end, new_start_frame=new_start, new_end_frame=new_end,
            prev_person_id=person, new_person_id=new_person, prev_confidence=confidence,
            new_confidence=new_confidence, prev_source=source, new_source=new_source,
            prev_status=status, new_status=new_status, reviewer_id=reviewer_id, note=note,
            created_at=now)
        result = fetch_annotation(connection, annotation_id), _fetch_event(connection, event_id)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return result


def accept(connection: sqlite3.Connection, annotation_id: int, *, reviewer_id: str,
           note: str | None = None) -> tuple[Annotation, ReviewEvent]:
    return _apply(connection, annotation_id, ReviewAction.ACCEPTED, None, reviewer_id, note)


def reject(connection: sqlite3.Connection, annotation_id: int, *, reviewer_id: str,
           note: str | None = None) -> tuple[Annotation, ReviewEvent]:
    return _apply(connection, annotation_id, ReviewAction.REJECTED, None, reviewer_id, note)


def defer(connection: sqlite3.Connection, annotation_id: int, *, reviewer_id: str,
          note: str | None = None) -> tuple[Annotation, ReviewEvent]:
    return _apply(connection, annotation_id, ReviewAction.DEFERRED, None, reviewer_id, note)


def edit(connection: sqlite3.Connection, annotation_id: int, changes: AnnotationChanges, *,
         reviewer_id: str, note: str | None = None) -> tuple[Annotation, ReviewEvent]:
    """Change label (same category, active), span, and/or participant; never touches the clip.

    A span- or participant-only edit keeps the current label even if it is now deactivated.
    """
    return _apply(connection, annotation_id, ReviewAction.EDITED, changes, reviewer_id, note)


def get_history(connection: sqlite3.Connection, annotation_id: int) -> list[ReviewEvent]:
    assert_schema(connection, tables=REVIEW_TABLES)
    rows = connection.execute(
        f"SELECT {', '.join(_EVENT_COLUMNS)} FROM ReviewEvent WHERE annotation_id = ?"
        " ORDER BY event_id", (annotation_id,)).fetchall()
    return [_event(row) for row in rows]


def create_annotation(connection: sqlite3.Connection, *, video_id: int, label_id: int,
                      start_frame: int, end_frame: int, reviewer_id: str,
                      person_id: str | None = None, clip_id: int | None = None,
                      note: str | None = None) -> tuple[Annotation, ReviewEvent]:
    """Record a moment the pipeline missed: HUMAN, ACCEPTED, no model confidence."""
    reviewer_id = _require_reviewer(reviewer_id)
    _begin(connection)
    try:
        _validate_span(connection, video_id, start_frame, end_frame)
        _label_category(connection, label_id, require_active=True)
        _require_person(connection, person_id)
        if clip_id is not None:
            _validate_clip_link(connection, clip_id, video_id, person_id, start_frame, end_frame)
        now = _now()
        annotation_id = connection.execute(
            "INSERT INTO Annotation (video_id, clip_id, person_id, label_id, start_frame,"
            " end_frame, confidence, source, review_status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, 'HUMAN', 'ACCEPTED', ?, ?)",
            (video_id, clip_id, person_id, label_id, start_frame, end_frame, now, now)).lastrowid
        event_id = _insert_event(
            connection, annotation_id=annotation_id, video_id=video_id,
            action=ReviewAction.CREATED.value, new_label_id=label_id,
            new_start_frame=start_frame, new_end_frame=end_frame, new_person_id=person_id,
            new_source=Source.HUMAN.value, new_status=ReviewStatus.ACCEPTED.value,
            reviewer_id=reviewer_id, note=note, created_at=now)
        result = fetch_annotation(connection, annotation_id), _fetch_event(connection, event_id)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return result
