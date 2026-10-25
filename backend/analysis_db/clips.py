"""One-time person-presence segmentation using existing analyzed frames."""

from collections import defaultdict
from datetime import datetime, timezone
from itertools import groupby
import math
import operator
import sqlite3

from analysis_db.contracts import DataError
from analysis_db.storage import write_transaction


def _threshold(value):
    if isinstance(value, bool):
        raise ValueError("persistence_frames must be a positive integer")
    try:
        value = operator.index(value)
    except TypeError as exc:
        raise ValueError("persistence_frames must be a positive integer") from exc
    if value < 1:
        raise ValueError("persistence_frames must be a positive integer")
    return value


def _segments(connection, video_id, duration, threshold):
    rows = connection.execute(
        "SELECT f.frame_id,f.source_time_seconds,d.person_id FROM Frame f"
        " LEFT JOIN FaceDetection d ON d.frame_id=f.frame_id"
        " WHERE f.video_id=? ORDER BY f.frame_number,d.person_id", (video_id,))
    confirmed = set()
    pending = {}
    events = defaultdict(list)
    previous_time = -1
    for (_, time), detections in groupby(rows, key=lambda row: (row[0], row[1])):
        if not math.isfinite(time) or not previous_time < time < duration:
            raise DataError("Frame timestamps must increase in presentation order and lie within video duration")
        previous_time = time
        present = {row[2] for row in detections if row[2] is not None}
        for person in present | confirmed | pending.keys():
            observed = person in present
            if observed == (person in confirmed):
                pending.pop(person, None)
                continue
            start, count = pending.get(person, (time, 0))
            count += 1
            if count < threshold:
                pending[person] = (start, count)
                continue
            pending.pop(person, None)
            if observed:
                confirmed.add(person)
            else:
                confirmed.remove(person)
            events[start].append((person, observed))

    # Confirmation order differs from boundary order when person runs overlap.
    # Replay backdated events in temporal order, grouping simultaneous changes.
    visible = set()
    start = 0.0
    for time, changes in sorted(events.items()):
        if visible and time > start:
            yield start, time, tuple(sorted(visible))
        for person, arrived in changes:
            if arrived:
                visible.add(person)
            else:
                visible.discard(person)
        start = time
    if visible and duration > start:
        yield start, duration, tuple(sorted(visible))


def generate_clips(connection: sqlite3.Connection, video_id: int, *,
                   persistence_frames: int = 5) -> tuple[int, ...]:
    """Finalize one video's clips atomically, or return its already frozen IDs.

    Call after all analyzed frames/identities have been populated. Unconfirmed
    trailing arrivals/departures are ignored. No inferred empty frames are added.
    """
    threshold = _threshold(persistence_frames)
    with write_transaction(connection):
        video = connection.execute(
            "SELECT duration_seconds FROM Video WHERE video_id=?", (video_id,)).fetchone()
        if video is None:
            raise LookupError(f"Video {video_id} does not exist")
        existing = tuple(row[0] for row in connection.execute(
            "SELECT clip_id FROM Clip WHERE video_id=? ORDER BY start_time_seconds", (video_id,)))
        if connection.execute("SELECT 1 FROM ClipGeneration WHERE video_id=?", (video_id,)).fetchone():
            return existing
        if existing:
            raise DataError("Video has clips without a finalization marker; refusing to regenerate")
        duration = video[0]
        if duration is None or not math.isfinite(duration) or duration <= 0:
            raise DataError(f"Video {video_id} requires a finite positive duration")
        timestamp = datetime.now(timezone.utc).isoformat()
        ids = []
        for start, end, people in _segments(connection, video_id, duration, threshold):
            cursor = connection.execute(
                "INSERT INTO Clip(video_id,start_time_seconds,end_time_seconds,created_at) VALUES(?,?,?,?)",
                (video_id, start, end, timestamp))
            clip_id = cursor.lastrowid
            connection.executemany("INSERT INTO ClipPerson(clip_id,person_id) VALUES(?,?)",
                                   ((clip_id, person) for person in people))
            ids.append(clip_id)
        connection.execute(
            "INSERT INTO ClipGeneration(video_id,persistence_frames,created_at) VALUES(?,?,?)",
            (video_id, threshold, timestamp))
    return tuple(ids)


def populate_clips(connection: sqlite3.Connection, *,
                   persistence_frames: int = 5) -> dict[int, tuple[int, ...]]:
    """Finalize all videos, one atomic transaction per video; safe to resume."""
    threshold = _threshold(persistence_frames)
    if connection.in_transaction:
        raise DataError("clip population requires an idle database connection")
    videos = [row[0] for row in connection.execute("SELECT video_id FROM Video ORDER BY video_id")]
    return {video_id: generate_clips(connection, video_id, persistence_frames=threshold)
            for video_id in videos}
