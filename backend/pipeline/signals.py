import sqlite3

from analysis_db.contracts import DataError, TABLES
from analysis_db.storage import assert_schema
from pipeline.contracts import ActivitySignal, DetectionSignal, ExpressionScores, VideoSignals


def load_video_signals(connection: sqlite3.Connection, video_id: int) -> VideoSignals:
    """Read one video's detections with their expression and activity signals; SELECTs only."""
    assert_schema(connection, tables=TABLES)
    video = connection.execute(
        "SELECT filename, fps, duration_seconds FROM Video WHERE video_id = ?",
        (video_id,)).fetchone()
    if video is None:
        raise LookupError(f"video {video_id} does not exist")
    filename, fps, duration = video
    frame_linked = any(row[1] == "frame_id" for row in connection.execute("PRAGMA table_info(Activity)"))
    activity_columns = ("a.activity_label, a.window_start_seconds, a.window_end_seconds, a.score"
                        if frame_linked else "a.activity_label, a.start_frame, a.end_frame, a.confidence")
    activity_join = "a.frame_id = f.frame_id" if frame_linked else "a.detection_id = d.detection_id"
    detections = []
    for (detection_id, person_id, frame_number, seconds, positive, neutral, negative,
         label, start, end, confidence) in connection.execute(
            "SELECT d.detection_id, d.person_id, f.frame_number, f.source_time_seconds,"
            f" e.positive_score, e.neutral_score, e.negative_score, {activity_columns}"
            " FROM FaceDetection d JOIN Frame f ON f.frame_id = d.frame_id"
            " LEFT JOIN Engagement e ON e.detection_id = d.detection_id"
            f" LEFT JOIN Activity a ON {activity_join}"
            " WHERE f.video_id = ? ORDER BY f.frame_number, d.person_id", (video_id,)):
        activity = None
        if label is not None:
            if frame_linked:
                if fps is None or fps <= 0:
                    raise DataError(f"video {video_id} needs positive fps to read activity windows")
                start, end = round(start * fps), round(end * fps)
            activity = ActivitySignal(label, start, end, confidence)
        detections.append(DetectionSignal(
            detection_id, person_id, frame_number, seconds,
            None if positive is None else ExpressionScores(positive, neutral, negative), activity))
    frame_count = round(duration * fps) if duration and fps else None
    return VideoSignals(video_id, filename, fps, frame_count, tuple(detections))
