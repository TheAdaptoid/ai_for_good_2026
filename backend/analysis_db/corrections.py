"""Explicit user corrections. Automated prediction writers do not call these."""

from datetime import datetime, timezone
import math
import sqlite3

from analysis_db.clip_analytics import get_clip_info
from analysis_db.contracts import ClipInfo, DataError
from analysis_db.annotations import _now, _validate_span, fetch_annotation
from analysis_db.review import _insert_event, _require_reviewer
from analysis_db.storage import write_transaction


def _apply(connection, table, record_id, columns, values, audit_columns, changed_by):
    """Update one record and append its audit row inside the caller's transaction."""
    key = table.lower() + "_id"
    old = connection.execute(
        f"SELECT {','.join(columns)} FROM {table} WHERE {key}=?",
        (record_id,),
    ).fetchone()
    if old is None:
        raise LookupError(f"{table} {record_id} does not exist")
    if old == values:
        return False
    connection.execute(
        f"UPDATE {table} SET {','.join(column + '=?' for column in columns)} WHERE {key}=?",
        (*values, record_id),
    )
    pairs = tuple(value for pair in zip(old, values) for value in pair)
    names = (key, *audit_columns, "changed_at", "changed_by")
    connection.execute(
        f"INSERT INTO {table}Audit ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
        (record_id, *pairs, datetime.now(timezone.utc).isoformat(), changed_by),
    )
    return True


def _correct(connection, table, record_id, columns, values, audit_columns, changed_by):
    if changed_by is not None and not isinstance(changed_by, str):
        raise ValueError("changed_by must be text or None")
    with write_transaction(connection):
        return _apply(connection, table, record_id, columns, values, audit_columns, changed_by)


def correct_activity(connection: sqlite3.Connection, activity_id: int,
                     new_label: str, *, changed_by: str | None = None) -> bool:
    """Update the current label and append history atomically; False on no-op.

    Model scores and result_json remain the original prediction provenance.
    activity_label is the authoritative current, potentially corrected label.
    """
    if not isinstance(new_label, str) or not new_label.strip():
        raise ValueError("Activity label must be nonempty text")
    return _correct(connection, "Activity", activity_id, ("activity_label",),
                    (new_label,), ("old_label", "new_label"), changed_by)


ENGAGEMENT_COLUMNS = ("positive_score", "neutral_score", "negative_score")
ENGAGEMENT_AUDIT = tuple(prefix + column for column in ENGAGEMENT_COLUMNS for prefix in ("old_", "new_"))


def _check_scores(values):
    for value in values:
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Engagement scores must be finite numbers between 0 and 1")


def correct_engagement(connection: sqlite3.Connection, engagement_id: int,
                       positive_score: float, neutral_score: float,
                       negative_score: float, *, changed_by: str | None = None) -> bool:
    """Update all current scores and append history atomically; False on no-op."""
    values = (positive_score, neutral_score, negative_score)
    _check_scores(values)
    return _correct(connection, "Engagement", engagement_id, ENGAGEMENT_COLUMNS,
                    values, ENGAGEMENT_AUDIT, changed_by)


CLIP_RESULT = {"ACCEPT": "ACCEPTED", "EDIT": "EDITED", "DEFER": "DEFERRED"}


def _set_clip_activity(connection: sqlite3.Connection, clip: ClipInfo, label_id: int, reviewer_id: str) -> bool:
    start, end = connection.execute(
        "SELECT MIN(frame_number),MAX(frame_number) FROM Frame"
        " WHERE video_id=? AND source_time_seconds>=? AND source_time_seconds<?",
        (clip.video_id, clip.start_time_seconds, clip.end_time_seconds)).fetchone()
    if start is None:
        raise DataError("No analyzed frames belong to this clip")
    _validate_span(connection, clip.video_id, start, end)
    reviewer_id = _require_reviewer(reviewer_id)
    key = f"staff:clip:{clip.clip_id}:activity"
    row = connection.execute("SELECT annotation_id FROM Annotation WHERE import_key=?", (key,)).fetchone()
    previous = fetch_annotation(connection, row[0]) if row else None
    if previous and previous.source != "HUMAN":
        raise DataError("The clip activity record is not a human annotation")
    if previous and previous.label_id == label_id and previous.review_status != "REJECTED":
        return False
    now = _now()
    status = "EDITED" if previous else "ACCEPTED"
    if previous:
        identity = previous.annotation_id
        connection.execute(
            "UPDATE Annotation SET label_id=?,start_frame=?,end_frame=?,confidence=NULL,"
            " source='HUMAN',review_status=?,updated_at=? WHERE annotation_id=?",
            (label_id, start, end, status, now, identity))
    else:
        identity = connection.execute(
            "INSERT INTO Annotation(video_id,label_id,start_frame,end_frame,source,review_status,"
            " import_key,created_at,updated_at) VALUES(?,?,?,?,'HUMAN',?,?,?,?)",
            (clip.video_id, label_id, start, end, status, key, now, now)).lastrowid
    _insert_event(
        connection, annotation_id=identity, video_id=clip.video_id,
        action="EDITED" if previous else "CREATED",
        prev_label_id=previous.label_id if previous else None, new_label_id=label_id,
        prev_start_frame=previous.start_frame if previous else None,
        prev_end_frame=previous.end_frame if previous else None,
        new_start_frame=start, new_end_frame=end,
        prev_person_id=previous.person_id if previous else None,
        new_person_id=previous.person_id if previous else None,
        prev_confidence=previous.confidence if previous else None, new_confidence=None,
        prev_source=previous.source if previous else None, new_source="HUMAN",
        prev_status=previous.review_status if previous else None, new_status=status,
        reviewer_id=reviewer_id, created_at=now)
    return True


def review_clip(connection: sqlite3.Connection, clip_id: int, action: str, *, reviewer_id: str,
                activity_label: str | None = None,
                scores: tuple[float, float, float] | None = None,
                create_activity_label: bool = False) -> str:
    """Apply one staff review action to a stored clip and return its new review status.

    EDIT records a human activity annotation for this clip's frames without changing model
    activity rows, and applies audited visible-affect corrections inside the clip. A new label
    remains available for staff use. Status, annotation, and history commit together.
    """
    if action not in CLIP_RESULT:
        raise ValueError(f"Unknown clip review action {action!r}")
    if action != "EDIT" and (activity_label is not None or scores is not None):
        raise DataError("Only an edit changes activity or engagement values")
    if create_activity_label:
        if activity_label is None or not activity_label.strip():
            raise DataError("A new activity label needs a name")
        activity_label = activity_label.strip()
    if action == "EDIT":
        if activity_label is None and scores is None:
            raise DataError("An edit must change the activity label or the engagement scores")
        if scores is not None:
            _check_scores(scores)
    with write_transaction(connection):
        clip = get_clip_info(connection, clip_id)
        (previous,) = connection.execute(
            "SELECT review_status FROM Clip WHERE clip_id=?", (clip_id,)).fetchone()
        if action == "EDIT":
            changed = False
            if activity_label is not None:
                if create_activity_label:
                    if connection.execute("SELECT 1 FROM Label WHERE category='activity' AND name=? COLLATE NOCASE",
                                          (activity_label,)).fetchone():
                        raise DataError(f"Activity label {activity_label!r} already exists")
                    connection.execute("INSERT INTO Label(name,category) VALUES(?,'activity')",
                                       (activity_label,))
                label = connection.execute(
                        "SELECT label_id FROM Label WHERE category='activity' AND is_active=1 AND name=?",
                        (activity_label,)).fetchone()
                if label is None:
                    raise DataError(f"{activity_label!r} is not an active activity label")
                changed |= _set_clip_activity(connection, clip, label[0], reviewer_id)
            if scores is not None:
                for (engagement_id,) in connection.execute(
                        "SELECT e.engagement_id FROM Engagement e"
                        " JOIN FaceDetection d ON d.detection_id=e.detection_id"
                        " JOIN Frame f ON f.frame_id=d.frame_id"
                        " JOIN ClipPerson cp ON cp.person_id=d.person_id AND cp.clip_id=?"
                        " WHERE f.video_id=? AND f.source_time_seconds>=? AND f.source_time_seconds<?",
                        (clip_id, clip.video_id, clip.start_time_seconds,
                         clip.end_time_seconds)).fetchall():
                    changed |= _apply(connection, "Engagement", engagement_id, ENGAGEMENT_COLUMNS,
                                      tuple(scores), ENGAGEMENT_AUDIT, reviewer_id)
            if not changed:
                raise DataError("The edit changes no stored value in this clip")
        status = CLIP_RESULT[action]
        connection.execute("UPDATE Clip SET review_status=? WHERE clip_id=?", (status, clip_id))
        connection.execute(
            "INSERT INTO ClipReviewEvent(clip_id,action,previous_status,resulting_status,"
            "reviewer_id,created_at) VALUES(?,?,?,?,?,?)",
            (clip_id, action, previous, status, reviewer_id, datetime.now(timezone.utc).isoformat()))
    return status
