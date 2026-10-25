"""Read stored analysis directly, without copying it into staff review tables."""

import math
import sqlite3
from dataclasses import dataclass
from typing import TextIO

from analysis_db.clip_analytics import get_clip_summary
from analysis_db.exports import _write


@dataclass(frozen=True)
class PersonClip:
    clip_id: int
    video_id: int
    start_seconds: float
    end_seconds: float
    person_ids: tuple[str, ...]
    created_at: str
    mean_positive_score: float | None = None
    impact_score: float | None = None
    review_status: str = "UNREVIEWED"


@dataclass(frozen=True)
class AffectScores:
    positive: float | None
    neutral: float | None
    negative: float | None
    observation_count: int


@dataclass(frozen=True)
class StoredClipSummary:
    dominant_activity: str | None
    activity_distribution: dict[str, float]
    visible_affect: AffectScores
    impact_score: float | None = None
    activity_source: str = "AI"


def clip_impact_score(mean_positive: float | None, participant_count: int,
                      duration_seconds: float) -> float | None:
    """Staff-selected ranking heuristic (D031), not model confidence or a probability."""
    if mean_positive is None:
        return None
    return math.log1p(duration_seconds / 3) * 1.5 ** participant_count * mean_positive


def list_person_clips(connection: sqlite3.Connection, *, video_id: int | None = None,
                      person_id: str | None = None, clip_id: int | None = None,
                      review_status: str | None = None, search: str | None = None,
                      limit: int | None = None, offset: int = 0) -> list[PersonClip]:
    clauses, params = [], []
    for column, value in (("video_id", video_id), ("clip_id", clip_id), ("review_status", review_status)):
        if value is not None:
            clauses.append(f"c.{column}=?")
            params.append(value)
    if person_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM ClipPerson p WHERE p.clip_id=c.clip_id AND p.person_id=?)")
        params.append(person_id)
    search_clause, search_params = _clip_search(search)
    if search_clause:
        clauses.append(search_clause)
        params.extend(search_params)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    page = where + " ORDER BY c.video_id,c.start_time_seconds,c.clip_id LIMIT ? OFFSET ?"
    values = (*params, -1 if limit is None else limit, offset)
    rows = connection.execute(
        "SELECT c.clip_id,c.video_id,c.start_time_seconds,c.end_time_seconds,c.created_at,c.review_status"
        " FROM Clip c" + page, values).fetchall()
    if not rows:
        return []
    members: dict[int, list[str]] = {}
    for identity, person in connection.execute(
            "SELECT p.clip_id,p.person_id FROM ClipPerson p WHERE p.clip_id IN ("
            "SELECT c.clip_id FROM Clip c" + page + ") ORDER BY p.person_id", values):
        members.setdefault(identity, []).append(person)
    means = dict(connection.execute(
        "SELECT c.clip_id,AVG(e.positive_score) FROM Clip c"
        " JOIN Frame f ON f.video_id=c.video_id AND f.source_time_seconds>=c.start_time_seconds"
        " AND f.source_time_seconds<c.end_time_seconds"
        " JOIN FaceDetection d ON d.frame_id=f.frame_id"
        " JOIN ClipPerson p ON p.clip_id=c.clip_id AND p.person_id=d.person_id"
        " JOIN Engagement e ON e.detection_id=d.detection_id"
        " WHERE c.clip_id IN (SELECT c.clip_id FROM Clip c" + page + ") GROUP BY c.clip_id", values))
    return [PersonClip(identity, video, start, end, tuple(members.get(identity, ())), created,
                       means.get(identity), clip_impact_score(means.get(identity), len(members.get(identity, ())), end - start),
                       status)
            for identity, video, start, end, created, status in rows]


@dataclass(frozen=True)
class ActivityCount:
    activity_label: str
    count: int
    mean_positive_score: float | None = None
    observation_count: int = 0


def activity_counts(connection: sqlite3.Connection) -> list[ActivityCount]:
    """Each current activity label: how many windows carry it, most frequent first, and the mean
    positive visible-affect score of the face observations inside those windows (half-open, same
    video). An observation inside two overlapping windows counts once per window."""
    # CROSS JOIN pins the order (windows first, then the frame-time index): SQLite's own choice
    # scanned every frame of the video per detection and took ~33 s on the real database.
    affect = {label: (mean, n) for label, mean, n in connection.execute(
        "SELECT a.activity_label,AVG(e.positive_score),COUNT(*) FROM Activity a"
        " CROSS JOIN Frame af ON af.frame_id=a.frame_id"
        " CROSS JOIN Frame f ON f.video_id=af.video_id AND f.source_time_seconds>=a.window_start_seconds"
        " AND f.source_time_seconds<a.window_end_seconds"
        " CROSS JOIN FaceDetection d ON d.frame_id=f.frame_id"
        " CROSS JOIN Engagement e ON e.detection_id=d.detection_id"
        " GROUP BY a.activity_label")}
    return [ActivityCount(label, count, *affect.get(label, (None, 0))) for label, count in connection.execute(
        "SELECT activity_label,COUNT(*) FROM Activity GROUP BY activity_label"
        " ORDER BY COUNT(*) DESC, activity_label")]


@dataclass(frozen=True)
class StageProgress:
    stage: str  # "activity" | "engagement" | "clips"
    done: int
    total: int


@dataclass(frozen=True)
class VideoProgress:
    video_id: int
    title: str
    stages: tuple[StageProgress, ...]


def processing_progress(connection: sqlite3.Connection) -> list[VideoProgress]:
    """How far each video's stored analysis has got, read from what the database holds.

    Activity: frames with a face detection (the activity pipeline's work list) that have a result.
    Engagement: face detections with visible-affect scores. Clips: 1 of 1 once the video's person
    clips are finalized. A video with no detections has 0 of 0 for the first two stages.
    """
    activity = {vid: (done, total) for vid, done, total in connection.execute(
        "SELECT f.video_id,COUNT(a.activity_id),COUNT(*) FROM Frame f"
        " LEFT JOIN Activity a ON a.frame_id=f.frame_id"
        " WHERE EXISTS (SELECT 1 FROM FaceDetection d WHERE d.frame_id=f.frame_id) GROUP BY f.video_id")}
    engagement = {vid: (done, total) for vid, done, total in connection.execute(
        "SELECT f.video_id,COUNT(e.engagement_id),COUNT(*) FROM FaceDetection d"
        " JOIN Frame f ON f.frame_id=d.frame_id LEFT JOIN Engagement e ON e.detection_id=d.detection_id"
        " GROUP BY f.video_id")}
    finalized = {vid for (vid,) in connection.execute("SELECT video_id FROM ClipGeneration")}
    return [VideoProgress(vid, title, (
        StageProgress("activity", *activity.get(vid, (0, 0))),
        StageProgress("engagement", *engagement.get(vid, (0, 0))),
        StageProgress("clips", int(vid in finalized), 1)))
        for vid, title in connection.execute("SELECT video_id,title FROM Video ORDER BY video_id")]


CLIP_REVIEW_STATUSES = ("UNREVIEWED", "ACCEPTED", "EDITED", "DEFERRED")


def _clip_search(search: str | None) -> tuple[str, tuple[str, ...]]:
    query = (search or "").strip()
    if not query:
        return "", ()
    identity = query.removeprefix("#").strip()
    if identity.isdecimal():
        identity = str(int(identity))
    return ("(c.video_id IN (SELECT video_id FROM Video WHERE INSTR(LOWER(title),LOWER(?))>0)"
            " OR CAST(c.clip_id AS TEXT)=?)", (query, identity))


def person_clip_status_counts(connection: sqlite3.Connection, *, search: str | None = None) -> dict[str, int]:
    clause, params = _clip_search(search)
    counts = dict(connection.execute("SELECT c.review_status,COUNT(*) FROM Clip c"
                                     + (" WHERE " + clause if clause else "")
                                     + " GROUP BY c.review_status", params))
    return {status: counts.get(status, 0) for status in CLIP_REVIEW_STATUSES}


def get_person_clip(connection: sqlite3.Connection, clip_id: int) -> PersonClip:
    clips = list_person_clips(connection, clip_id=clip_id)
    if not clips:
        raise LookupError(f"Clip {clip_id} does not exist")
    return clips[0]


def person_clip_summary(connection: sqlite3.Connection, clip_id: int) -> StoredClipSummary:
    result = get_clip_summary(connection, clip_id)
    manual = connection.execute(
        "SELECT l.name FROM Annotation a JOIN Label l ON l.label_id=a.label_id"
        " WHERE a.import_key=? AND a.source='HUMAN' AND a.review_status!='REJECTED'",
        (f"staff:clip:{clip_id}:activity",)).fetchone()
    return StoredClipSummary(manual[0] if manual else result['activity']['dominant_label'],
                             {manual[0]: 1.0} if manual else result['activity']['distribution'], AffectScores(**result['engagement']),
                             clip_impact_score(result['engagement']['positive'], len(result['person_ids']),
                                               result['end_time_seconds'] - result['start_time_seconds']),
                             "HUMAN" if manual else "AI")


DATABASE_EXPORTS = {
    "clips": "SELECT c.clip_id,c.video_id,c.start_time_seconds,c.end_time_seconds,"
             "(SELECT GROUP_CONCAT(person_id, ', ') FROM (SELECT person_id FROM ClipPerson"
             " WHERE clip_id=c.clip_id ORDER BY person_id)) AS person_ids,c.created_at,c.review_status"
             " FROM Clip c ORDER BY c.video_id,c.start_time_seconds,c.clip_id",
    "activity": "SELECT a.activity_id,f.video_id,a.frame_id,a.window_start_seconds,"
                "a.window_end_seconds,a.activity_label,a.score FROM Activity a"
                " JOIN Frame f ON f.frame_id=a.frame_id ORDER BY f.video_id,a.window_start_seconds,a.activity_id",
    "engagement": "SELECT e.engagement_id,f.video_id,d.person_id,e.detection_id,"
                  "f.source_time_seconds,e.positive_score,e.neutral_score,e.negative_score"
                  " FROM Engagement e JOIN FaceDetection d ON d.detection_id=e.detection_id"
                  " JOIN Frame f ON f.frame_id=d.frame_id ORDER BY f.video_id,f.source_time_seconds,e.engagement_id",
    "activity-history": "SELECT * FROM ActivityAudit ORDER BY audit_id",
    "engagement-history": "SELECT * FROM EngagementAudit ORDER BY audit_id",
    "clip-review-history": "SELECT * FROM ClipReviewEvent ORDER BY event_id",
}


def export_database(connection: sqlite3.Connection, dataset: str, out: TextIO, fmt: str) -> None:
    cursor = connection.execute(DATABASE_EXPORTS[dataset])
    columns = tuple(column[0] for column in cursor.description)
    _write([dict(zip(columns, row)) for row in cursor], columns, out, fmt)
