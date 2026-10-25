"""Live clip summaries from current labels and available score observations."""

from collections import defaultdict
from dataclasses import asdict
import math
import sqlite3

from analysis_db.contracts import ClipInfo


def get_clip_info(connection: sqlite3.Connection, clip_id: int) -> ClipInfo:
    row = connection.execute(
        "SELECT c.clip_id,c.video_id,c.start_time_seconds,c.end_time_seconds,c.created_at,v.file_path"
        " FROM Clip c JOIN Video v ON v.video_id=c.video_id WHERE c.clip_id=?", (clip_id,)).fetchone()
    if row is None:
        raise LookupError(f"Clip {clip_id} does not exist")
    people = tuple(person for (person,) in connection.execute(
        "SELECT person_id FROM ClipPerson WHERE clip_id=? ORDER BY person_id", (clip_id,)))
    return ClipInfo(row[0], row[1], row[2], row[3], people, row[4], row[5])


def _activity_summary(connection, clip, include_details):
    cursor = connection.execute(
        "SELECT a.*,MIN(a.window_end_seconds,?)-MAX(a.window_start_seconds,?) AS overlap_seconds"
        " FROM Activity a JOIN Frame f ON f.frame_id=a.frame_id"
        " WHERE f.video_id=? AND a.window_start_seconds<? AND a.window_end_seconds>?"
        " ORDER BY a.window_start_seconds,a.activity_id",
        (clip.end_time_seconds, clip.start_time_seconds, clip.video_id,
         clip.end_time_seconds, clip.start_time_seconds))
    columns = tuple(item[0] for item in cursor.description)
    weights = defaultdict(list)
    records = []
    label_index = columns.index("activity_label")
    for row in cursor:
        weights[row[label_index]].append(row[-1])
        if include_details:
            records.append(dict(zip(columns, row)))
    totals = {label: math.fsum(values) for label, values in weights.items()}
    total = math.fsum(totals.values())
    result = {
        "dominant_label": min(totals, key=lambda label: (-totals[label], label)) if totals else None,
        "distribution": {label: weight / total for label, weight in sorted(totals.items())},
    }
    if include_details:
        result["records"] = records
    return result


def _scores(positive=None, neutral=None, negative=None, count=0):
    return {"positive": positive, "neutral": neutral, "negative": negative,
            "observation_count": count}


def _engagement_summary(connection, clip):
    rows = connection.execute(
        "SELECT d.person_id,AVG(e.positive_score),AVG(e.neutral_score),AVG(e.negative_score),COUNT(*)"
        " FROM Engagement e JOIN FaceDetection d ON d.detection_id=e.detection_id"
        " JOIN Frame f ON f.frame_id=d.frame_id"
        " JOIN ClipPerson cp ON cp.person_id=d.person_id AND cp.clip_id=?"
        " WHERE f.video_id=? AND f.source_time_seconds>=? AND f.source_time_seconds<?"
        " GROUP BY d.person_id ORDER BY d.person_id",
        (clip.clip_id, clip.video_id, clip.start_time_seconds, clip.end_time_seconds)).fetchall()
    by_person = {person: _scores() for person in clip.person_ids}
    for person, positive, neutral, negative, count in rows:
        by_person[person] = _scores(positive, neutral, negative, count)
    count = sum(row[4] for row in rows)
    group = _scores()
    if count:
        means = [math.fsum(row[column] * row[4] for row in rows) / count for column in (1, 2, 3)]
        group = _scores(*means, count)
    return group, by_person


def get_clip_summary(connection: sqlite3.Connection, clip_id: int, *,
                     include_details: bool = False) -> dict:
    """Return JSON-serializable live aggregates in one read snapshot.

    Activity windows contribute their positive overlap duration as independent
    evidence. Engagement is an equal-weight mean of available observations, not
    a mean over frames or an unweighted mean over person means. Intervals are
    half-open. A caller's active transaction is preserved.
    """
    owns_snapshot = not connection.in_transaction
    if owns_snapshot:
        connection.execute("BEGIN")
    try:
        clip = get_clip_info(connection, clip_id)
        result = asdict(clip)
        result["person_ids"] = list(clip.person_ids)
        result["activity"] = _activity_summary(connection, clip, include_details)
        result["engagement"], result["engagement_by_person"] = _engagement_summary(connection, clip)
        return result
    finally:
        if owns_snapshot:
            connection.rollback()
