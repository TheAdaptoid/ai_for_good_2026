"""Read stored analysis directly, without copying it into staff review tables."""

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


def list_person_clips(connection: sqlite3.Connection, *, video_id: int | None = None,
                      person_id: str | None = None, clip_id: int | None = None,
                      limit: int | None = None, offset: int = 0) -> list[PersonClip]:
    clauses, params = [], []
    for column, value in (("video_id", video_id), ("clip_id", clip_id)):
        if value is not None:
            clauses.append(f"c.{column}=?")
            params.append(value)
    if person_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM ClipPerson p WHERE p.clip_id=c.clip_id AND p.person_id=?)")
        params.append(person_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    page = where + " ORDER BY c.video_id,c.start_time_seconds,c.clip_id LIMIT ? OFFSET ?"
    values = (*params, -1 if limit is None else limit, offset)
    rows = connection.execute(
        "SELECT c.clip_id,c.video_id,c.start_time_seconds,c.end_time_seconds,c.created_at"
        " FROM Clip c" + page, values).fetchall()
    if not rows:
        return []
    members: dict[int, list[str]] = {}
    for identity, person in connection.execute(
            "SELECT p.clip_id,p.person_id FROM ClipPerson p WHERE p.clip_id IN ("
            "SELECT c.clip_id FROM Clip c" + page + ") ORDER BY p.person_id", values):
        members.setdefault(identity, []).append(person)
    return [PersonClip(identity, video, start, end, tuple(members.get(identity, ())), created)
            for identity, video, start, end, created in rows]


def get_person_clip(connection: sqlite3.Connection, clip_id: int) -> PersonClip:
    clips = list_person_clips(connection, clip_id=clip_id)
    if not clips:
        raise LookupError(f"Clip {clip_id} does not exist")
    return clips[0]


def person_clip_summary(connection: sqlite3.Connection, clip_id: int) -> StoredClipSummary:
    result = get_clip_summary(connection, clip_id)
    return StoredClipSummary(result['activity']['dominant_label'],
                             result['activity']['distribution'], AffectScores(**result['engagement']))


DATABASE_EXPORTS = {
    "clips": "SELECT c.clip_id,c.video_id,c.start_time_seconds,c.end_time_seconds,"
             "(SELECT GROUP_CONCAT(person_id, ', ') FROM (SELECT person_id FROM ClipPerson"
             " WHERE clip_id=c.clip_id ORDER BY person_id)) AS person_ids,c.created_at"
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
}


def export_database(connection: sqlite3.Connection, dataset: str, out: TextIO, fmt: str) -> None:
    cursor = connection.execute(DATABASE_EXPORTS[dataset])
    columns = tuple(column[0] for column in cursor.description)
    _write([dict(zip(columns, row)) for row in cursor], columns, out, fmt)
