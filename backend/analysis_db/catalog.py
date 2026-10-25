"""Read-only video and participant summaries for the dashboard, video, and participant views.

Presence intervals are computed from face detections on every read and never stored: they are
a view of machine signals, not review records.
"""

import sqlite3
from pathlib import Path

from analysis_db.contracts import (
    REVIEW_TABLES, ParticipantDetail, ParticipantSummary, ParticipantVideo, PresenceInterval,
    ReviewStatus, VideoParticipant, VideoSummary,
)
from analysis_db.paths import REPOSITORY_ROOT
from analysis_db.storage import assert_schema

# Detections are sampled about every 5 frames; shorter gaps are detection flicker.
PRESENCE_GAP_SECONDS = 2.0


def list_videos(connection: sqlite3.Connection,
                video_id: int | None = None) -> list[VideoSummary]:
    assert_schema(connection, tables=REVIEW_TABLES)
    where, params = ("WHERE video_id = ?", (video_id,)) if video_id is not None else ("", ())
    detections = {vid: (people, count) for vid, people, count in connection.execute(
        "SELECT f.video_id, COUNT(DISTINCT d.person_id), COUNT(*) FROM FaceDetection d"
        " JOIN Frame f ON f.frame_id = d.frame_id"
        + (" WHERE f.video_id = ?" if video_id is not None else "")
        + " GROUP BY f.video_id", params)}
    statuses: dict[int, dict[str, int]] = {}
    for vid, status, count in connection.execute(
            f"SELECT video_id, review_status, COUNT(*) FROM Annotation {where}"
            " GROUP BY video_id, review_status", params):
        statuses.setdefault(vid, {})[status] = count
    clips = dict(connection.execute(
        f"SELECT video_id, COUNT(*) FROM ReviewClip {where} GROUP BY video_id", params))
    stored_clips = dict(connection.execute(
        f"SELECT video_id, COUNT(*) FROM Clip {where} GROUP BY video_id", params))
    human_annotations = dict(connection.execute(
        "SELECT video_id, COUNT(*) FROM Annotation WHERE source='HUMAN'"
        + (" AND video_id=?" if video_id is not None else "") + " GROUP BY video_id", params))
    result = []
    for vid, title, filename, duration, fps in connection.execute(
            f"SELECT video_id, title, filename, duration_seconds, fps FROM Video {where}"
            " ORDER BY video_id", params):
        people, count = detections.get(vid, (0, 0))
        counts = {status.value: statuses.get(vid, {}).get(status.value, 0)
                  for status in ReviewStatus}
        result.append(VideoSummary(
            vid, title, filename, duration, fps,
            round(duration * fps) if duration and fps else None,
            people, count, counts, clips.get(vid, 0), stored_clips.get(vid, 0), human_annotations.get(vid, 0)))
    return result


def get_video(connection: sqlite3.Connection, video_id: int) -> VideoSummary:
    found = list_videos(connection, video_id)
    if not found:
        raise LookupError(f"video {video_id} does not exist")
    return found[0]


def _intervals(times: list[float], gap: float) -> tuple[PresenceInterval, ...]:
    intervals, start, previous, count = [], times[0], times[0], 1
    for moment in times[1:]:
        if moment - previous > gap:
            intervals.append(PresenceInterval(start, previous, count))
            start, count = moment, 0
        previous = moment
        count += 1
    intervals.append(PresenceInterval(start, previous, count))
    return tuple(intervals)


def video_participants(connection: sqlite3.Connection, video_id: int, *,
                       gap_seconds: float = PRESENCE_GAP_SECONDS) -> list[VideoParticipant]:
    """Each participant seen in the video, ordered by first appearance."""
    get_video(connection, video_id)
    times: dict[str, list[float]] = {}
    for person_id, moment in connection.execute(
            "SELECT d.person_id, f.source_time_seconds FROM FaceDetection d"
            " JOIN Frame f ON f.frame_id = d.frame_id WHERE f.video_id = ?"
            " ORDER BY d.person_id, f.source_time_seconds", (video_id,)):
        times.setdefault(person_id, []).append(moment)
    participants = [VideoParticipant(person_id, values[0], values[-1], len(values),
                                     _intervals(values, gap_seconds))
                    for person_id, values in times.items()]
    return sorted(participants, key=lambda p: (p.first_seconds, p.person_id))


def list_participants(connection: sqlite3.Connection) -> list[ParticipantSummary]:
    return [ParticipantSummary(*row) for row in connection.execute(
        "SELECT p.person_id, COUNT(DISTINCT f.video_id), COUNT(d.detection_id) FROM Person p"
        " LEFT JOIN FaceDetection d ON d.person_id = p.person_id"
        " LEFT JOIN Frame f ON f.frame_id = d.frame_id"
        " GROUP BY p.person_id ORDER BY p.person_id")]


def get_participant(connection: sqlite3.Connection, person_id: str) -> ParticipantDetail:
    if connection.execute("SELECT 1 FROM Person WHERE person_id = ?",
                          (person_id,)).fetchone() is None:
        raise LookupError(f"participant {person_id!r} does not exist")
    videos = tuple(ParticipantVideo(*row) for row in connection.execute(
        "SELECT f.video_id, v.title, MIN(f.source_time_seconds), MAX(f.source_time_seconds),"
        " COUNT(*) FROM FaceDetection d JOIN Frame f ON f.frame_id = d.frame_id"
        " JOIN Video v ON v.video_id = f.video_id WHERE d.person_id = ?"
        " GROUP BY f.video_id ORDER BY f.video_id", (person_id,)))
    return ParticipantDetail(person_id, videos)


def video_file(connection: sqlite3.Connection, video_id: int, video_dir: Path) -> Path:
    """The video's file, only if it exists inside ``video_dir``; never a path outside it."""
    row = connection.execute("SELECT file_path FROM Video WHERE video_id = ?",
                             (video_id,)).fetchone()
    if row is None:
        raise LookupError(f"video {video_id} does not exist")
    path = (REPOSITORY_ROOT / row[0]).resolve()
    if not path.is_relative_to(video_dir.resolve()) or not path.is_file():
        raise LookupError(f"the file for video {video_id} is unavailable")
    return path
