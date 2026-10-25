import sqlite3

from analysis_db.contracts import TABLES
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
    detections = tuple(
        DetectionSignal(
            detection_id, person_id, frame_number, seconds,
            None if positive is None else ExpressionScores(positive, neutral, negative),
            None if label is None else ActivitySignal(label, start, end, confidence))
        for (detection_id, person_id, frame_number, seconds, positive, neutral, negative,
             label, start, end, confidence) in connection.execute(
            "SELECT d.detection_id, d.person_id, f.frame_number, f.source_time_seconds,"
            " e.positive_score, e.neutral_score, e.negative_score,"
            " a.activity_label, a.start_frame, a.end_frame, a.confidence"
            " FROM FaceDetection d JOIN Frame f ON f.frame_id = d.frame_id"
            " LEFT JOIN Engagement e ON e.detection_id = d.detection_id"
            " LEFT JOIN Activity a ON a.detection_id = d.detection_id"
            " WHERE f.video_id = ? ORDER BY f.frame_number, d.person_id", (video_id,)))
    frame_count = round(duration * fps) if duration and fps else None
    return VideoSignals(video_id, filename, fps, frame_count, detections)
