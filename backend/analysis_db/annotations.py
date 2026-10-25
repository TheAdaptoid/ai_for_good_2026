import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from analysis_db.contracts import (
    REVIEW_TABLES, Annotation, AnnotationInput, ClipInput, DataError, ImportResult,
    LabelCategory, ReviewClip, ReviewStatus, Source,
)
from analysis_db.storage import assert_schema

_ANNOTATION_SELECT = (
    "SELECT a.annotation_id, a.video_id, a.clip_id, a.person_id, a.label_id, l.name,"
    " l.category, a.start_frame, a.end_frame, v.fps, a.confidence, a.source,"
    " a.review_status, a.created_at, a.updated_at"
    " FROM Annotation a JOIN Label l ON l.label_id = a.label_id"
    " JOIN Video v ON v.video_id = a.video_id"
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _seconds(frame: int, fps: float | None) -> float | None:
    return frame / fps if fps else None


def _validate_span(connection: sqlite3.Connection, video_id: int, start: int, end: int) -> None:
    """0 <= start <= end, and end inside the video when its length is known."""
    row = connection.execute(
        "SELECT duration_seconds, fps FROM Video WHERE video_id = ?", (video_id,)).fetchone()
    if row is None:
        raise LookupError(f"video {video_id} does not exist")
    if not (isinstance(start, int) and isinstance(end, int)) \
            or isinstance(start, bool) or isinstance(end, bool):
        raise DataError("start_frame and end_frame must be integers")
    if not 0 <= start <= end:
        raise DataError(f"invalid span: start_frame {start}, end_frame {end}")
    duration, fps = row
    if duration and fps and end >= round(duration * fps):
        raise DataError(f"end_frame {end} is beyond the video's {round(duration * fps)} frames")


def _label_category(connection: sqlite3.Connection, label_id: int, *,
                    require_active: bool) -> str:
    row = connection.execute(
        "SELECT category, is_active FROM Label WHERE label_id = ?", (label_id,)).fetchone()
    if row is None:
        raise DataError(f"label {label_id} does not exist")
    if require_active and not row[1]:
        raise DataError(f"label {label_id} is inactive and cannot be newly applied")
    return row[0]


def _require_person(connection: sqlite3.Connection, person_id: str | None) -> None:
    if person_id is not None and connection.execute(
            "SELECT 1 FROM Person WHERE person_id = ?", (person_id,)).fetchone() is None:
        raise DataError(f"participant {person_id!r} does not exist")


def _validate_clip_link(connection: sqlite3.Connection, clip_id: int, video_id: int,
                        person_id: str | None, start: int, end: int) -> None:
    """Applied at import and Create only; later edits may diverge from the clip."""
    row = connection.execute(
        "SELECT video_id, start_frame, end_frame FROM ReviewClip WHERE clip_id = ?",
        (clip_id,)).fetchone()
    if row is None:
        raise DataError(f"review clip {clip_id} does not exist")
    if row[0] != video_id:
        raise DataError(f"review clip {clip_id} belongs to video {row[0]}, not {video_id}")
    if person_id is None and (start, end) != (row[1], row[2]):
        raise DataError(f"clip-level annotation span must equal clip {clip_id}'s span")


def _annotation(row: tuple) -> Annotation:
    (annotation_id, video_id, clip_id, person_id, label_id, label_name, category,
     start_frame, end_frame, fps, confidence, source, status, created_at, updated_at) = row
    return Annotation(
        annotation_id, video_id, clip_id, person_id, label_id, label_name,
        LabelCategory(category), start_frame, end_frame, _seconds(start_frame, fps),
        _seconds(end_frame, fps), confidence, Source(source), ReviewStatus(status),
        created_at, updated_at)


def fetch_annotation(connection: sqlite3.Connection, annotation_id: int) -> Annotation:
    row = connection.execute(
        _ANNOTATION_SELECT + " WHERE a.annotation_id = ?", (annotation_id,)).fetchone()
    if row is None:
        raise LookupError(f"annotation {annotation_id} does not exist")
    return _annotation(row)


def list_annotations(connection: sqlite3.Connection, *, video_id: int | None = None,
                     start_frame: int | None = None, end_frame: int | None = None,
                     person_id: str | None = None, label_id: int | None = None,
                     category: str | None = None, source: str | None = None,
                     review_status: str | None = None, clip_id: int | None = None,
                     include_rejected: bool = False) -> list[Annotation]:
    """Current annotations matching every given filter; REJECTED hidden unless asked for.

    The frame range selects annotations that overlap it, not ones contained in it.
    """
    assert_schema(connection, tables=REVIEW_TABLES)
    clauses, params = [], []
    for column, value in (("a.video_id", video_id), ("a.person_id", person_id),
                          ("a.label_id", label_id), ("a.clip_id", clip_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if category is not None:
        clauses.append("l.category = ?")
        params.append(LabelCategory(category).value)
    if source is not None:
        clauses.append("a.source = ?")
        params.append(Source(source).value)
    if review_status is not None:
        clauses.append("a.review_status = ?")
        params.append(ReviewStatus(review_status).value)
    elif not include_rejected:
        clauses.append("a.review_status != 'REJECTED'")
    if start_frame is not None:
        clauses.append("a.end_frame >= ?")
        params.append(start_frame)
    if end_frame is not None:
        clauses.append("a.start_frame <= ?")
        params.append(end_frame)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = connection.execute(
        _ANNOTATION_SELECT + where + " ORDER BY a.video_id, a.start_frame, a.annotation_id",
        params).fetchall()
    return [_annotation(row) for row in rows]


def list_clips(connection: sqlite3.Connection, *, video_id: int | None = None,
               person_id: str | None = None, clip_id: int | None = None,
               order: str = "time", limit: int | None = None) -> list[ReviewClip]:
    """Clips by video/time, or by review priority (highest first, unscored last)."""
    assert_schema(connection, tables=REVIEW_TABLES)
    orders = {"time": "c.video_id, c.start_frame, c.clip_id",
              "priority": "c.priority_score IS NULL, c.priority_score DESC,"
                          " c.video_id, c.start_frame"}
    if order not in orders:
        raise ValueError(f"order must be 'time' or 'priority', not {order!r}")
    clauses, params = [], []
    if video_id is not None:
        clauses.append("c.video_id = ?")
        params.append(video_id)
    if clip_id is not None:
        clauses.append("c.clip_id = ?")
        params.append(clip_id)
    if person_id is not None:
        clauses.append("c.clip_id IN"
                       " (SELECT clip_id FROM ReviewClipParticipant WHERE person_id = ?)")
        params.append(person_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    participants: dict[int, list[str]] = {}
    for clip_id, member in connection.execute(
            "SELECT p.clip_id, p.person_id FROM ReviewClipParticipant p"
            " JOIN ReviewClip c ON c.clip_id = p.clip_id" + where + " ORDER BY p.person_id",
            params):
        participants.setdefault(clip_id, []).append(member)
    rows = connection.execute(
        "SELECT c.clip_id, c.video_id, c.start_frame, c.end_frame, v.fps, c.priority_score,"
        " c.priority_method, c.created_at FROM ReviewClip c"
        " JOIN Video v ON v.video_id = c.video_id" + where + " ORDER BY " + orders[order]
        + ("" if limit is None else f" LIMIT {int(limit)}"), params).fetchall()
    return [ReviewClip(clip_id, video, start, end, _seconds(start, fps), _seconds(end, fps),
                       tuple(participants.get(clip_id, ())), score, method, created_at)
            for clip_id, video, start, end, fps, score, method, created_at in rows]


def get_clip(connection: sqlite3.Connection, clip_id: int) -> ReviewClip:
    found = list_clips(connection, clip_id=clip_id)
    if not found:
        raise LookupError(f"review clip {clip_id} does not exist")
    return found[0]


def _require_keys(items: Sequence, kind: str) -> None:
    keys = [item.import_key for item in items]
    if any(not isinstance(key, str) or not key.strip() for key in keys):
        raise DataError(f"every {kind} needs a non-empty import_key")
    if len(set(keys)) != len(keys):
        raise DataError(f"duplicate {kind} import_key in one import")


def _clip_is_protected(connection: sqlite3.Connection, clip_id: int) -> bool:
    return connection.execute(
        "SELECT 1 FROM Annotation WHERE clip_id = ? AND review_status != 'UNREVIEWED' LIMIT 1",
        (clip_id,)).fetchone() is not None


def _import_clip(connection: sqlite3.Connection, video_id: int, clip: ClipInput,
                 now: str) -> tuple[int, str]:
    _validate_span(connection, video_id, clip.start_frame, clip.end_frame)
    for member in clip.person_ids:
        _require_person(connection, member)
    values = (clip.start_frame, clip.end_frame, clip.priority_score, clip.priority_method)
    existing = connection.execute(
        "SELECT clip_id, video_id FROM ReviewClip WHERE import_key = ?",
        (clip.import_key,)).fetchone()
    if existing is None:
        clip_id = connection.execute(
            "INSERT INTO ReviewClip (video_id, start_frame, end_frame, priority_score,"
            " priority_method, import_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (video_id, *values, clip.import_key, now)).lastrowid
        outcome = "inserted"
    else:
        clip_id, stored_video = existing
        if stored_video != video_id:
            raise DataError(f"clip import_key {clip.import_key!r} belongs to video {stored_video}")
        if _clip_is_protected(connection, clip_id):
            return clip_id, "protected"
        stored = connection.execute(
            "SELECT start_frame, end_frame, priority_score, priority_method FROM ReviewClip"
            " WHERE clip_id = ?", (clip_id,)).fetchone()
        members = {member for (member,) in connection.execute(
            "SELECT person_id FROM ReviewClipParticipant WHERE clip_id = ?", (clip_id,))}
        if stored == values and members == set(clip.person_ids):
            return clip_id, "unchanged"
        connection.execute(
            "UPDATE ReviewClip SET start_frame = ?, end_frame = ?, priority_score = ?,"
            " priority_method = ? WHERE clip_id = ?", (*values, clip_id))
        connection.execute("DELETE FROM ReviewClipParticipant WHERE clip_id = ?", (clip_id,))
        outcome = "updated"
    connection.executemany(
        "INSERT INTO ReviewClipParticipant (clip_id, person_id) VALUES (?, ?)",
        [(clip_id, member) for member in sorted(set(clip.person_ids))])
    return clip_id, outcome


def _import_annotation(connection: sqlite3.Connection, video_id: int,
                       item: AnnotationInput, clip_ids: dict[str, int], now: str) -> str:
    existing = connection.execute(
        "SELECT annotation_id, video_id, clip_id, person_id, label_id, start_frame, end_frame,"
        " confidence, source, review_status FROM Annotation WHERE import_key = ?",
        (item.import_key,)).fetchone()
    if existing is not None:
        if existing[1] != video_id:
            raise DataError(
                f"annotation import_key {item.import_key!r} belongs to video {existing[1]}")
        # Protection wins before any validation of incoming values: a reviewed row is never
        # touched, so e.g. its since-deactivated label must not fail the whole import.
        if existing[8:] != ("AI", "UNREVIEWED"):
            return "protected"
    _label_category(connection, item.label_id, require_active=True)
    _validate_span(connection, video_id, item.start_frame, item.end_frame)
    _require_person(connection, item.person_id)
    clip_id = None
    if item.clip_import_key is not None:
        clip_id = clip_ids.get(item.clip_import_key)
        if clip_id is None:
            row = connection.execute("SELECT clip_id FROM ReviewClip WHERE import_key = ?",
                                     (item.clip_import_key,)).fetchone()
            if row is None:
                raise DataError(f"unknown clip import_key {item.clip_import_key!r}")
            clip_id = row[0]
        _validate_clip_link(connection, clip_id, video_id, item.person_id,
                            item.start_frame, item.end_frame)
    values = (clip_id, item.person_id, item.label_id, item.start_frame, item.end_frame,
              item.confidence)
    if existing is None:
        connection.execute(
            "INSERT INTO Annotation (video_id, clip_id, person_id, label_id, start_frame,"
            " end_frame, confidence, source, review_status, import_key, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'AI', 'UNREVIEWED', ?, ?, ?)",
            (video_id, *values, item.import_key, now, now))
        return "inserted"
    if tuple(existing[2:8]) == values:
        return "unchanged"
    # The WHERE guard makes protection a database rule: reviewed rows are never overwritten.
    cursor = connection.execute(
        "UPDATE Annotation SET clip_id = ?, person_id = ?, label_id = ?, start_frame = ?,"
        " end_frame = ?, confidence = ?, updated_at = ?"
        " WHERE annotation_id = ? AND source = 'AI' AND review_status = 'UNREVIEWED'",
        (*values, now, existing[0]))
    return "updated" if cursor.rowcount else "protected"


def _import_video(connection: sqlite3.Connection, video_id: int, clips: Sequence[ClipInput],
                  annotations: Sequence[AnnotationInput], now: str) -> ImportResult:
    """Upsert one video's output inside the caller's transaction (no commit or rollback here)."""
    _require_keys(clips, "clip")
    _require_keys(annotations, "annotation")
    counts = dict.fromkeys(("inserted", "updated", "protected", "unchanged"), 0)
    clip_counts = dict.fromkeys(("inserted", "updated", "protected", "unchanged"), 0)
    clip_ids = {}
    for clip in clips:
        try:
            clip_ids[clip.import_key], outcome = _import_clip(connection, video_id, clip, now)
        except DataError as exc:
            raise DataError(f"clip {clip.import_key!r}: {exc}") from exc
        clip_counts[outcome] += 1
    for item in annotations:
        try:
            counts[_import_annotation(connection, video_id, item, clip_ids, now)] += 1
        except DataError as exc:
            raise DataError(f"annotation {item.import_key!r}: {exc}") from exc
    return ImportResult(counts["inserted"], counts["updated"], counts["protected"],
                        clip_counts["inserted"], clip_counts["updated"],
                        clip_counts["protected"], counts["unchanged"],
                        clip_counts["unchanged"])


def import_machine_output(connection: sqlite3.Connection, video_id: int,
                          clips: Sequence[ClipInput],
                          annotations: Sequence[AnnotationInput]) -> ImportResult:
    """Insert or update pipeline output by import_key, all or nothing.

    Never deletes: rows missing from a later import are kept. Only AI/UNREVIEWED annotations,
    and clips holding no reviewed annotation, are updated; everything else counts as protected.
    """
    if connection.in_transaction:
        raise DataError("import requires an idle database connection")
    assert_schema(connection, tables=REVIEW_TABLES)
    connection.execute("BEGIN IMMEDIATE")
    try:
        result = _import_video(connection, video_id, clips, annotations, _now())
        connection.commit()
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise DataError(f"invalid machine output: {exc}") from exc
    except BaseException:
        connection.rollback()
        raise
    return result
