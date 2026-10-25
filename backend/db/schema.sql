PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE IF NOT EXISTS Video (
    video_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL UNIQUE,
    created_at TEXT,
    duration_seconds REAL,
    fps REAL,
    width INTEGER,
    height INTEGER
);
CREATE TABLE IF NOT EXISTS Frame (
    frame_id TEXT NOT NULL PRIMARY KEY CHECK (length(trim(frame_id)) > 0),
    video_id INTEGER NOT NULL REFERENCES Video(video_id) ON DELETE CASCADE,
    frame_number INTEGER NOT NULL CHECK (typeof(frame_number) = 'integer' AND frame_number >= 0),
    source_time_seconds REAL NOT NULL CHECK (source_time_seconds >= 0),
    UNIQUE (video_id, frame_number)
);
CREATE TABLE IF NOT EXISTS Person (
    person_id TEXT NOT NULL PRIMARY KEY CHECK (length(trim(person_id)) > 0)
);
CREATE TABLE IF NOT EXISTS FaceDetection (
    detection_id INTEGER PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES Person(person_id),
    frame_id TEXT NOT NULL REFERENCES Frame(frame_id) ON DELETE CASCADE,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    x2 REAL NOT NULL,
    y2 REAL NOT NULL,
    det_score REAL NOT NULL CHECK (det_score BETWEEN 0 AND 1),
    CHECK (x1 < x2 AND y1 < y2),
    UNIQUE (frame_id, person_id)
);
CREATE TABLE IF NOT EXISTS Activity (
    activity_id INTEGER PRIMARY KEY,
    frame_id TEXT NOT NULL UNIQUE REFERENCES Frame(frame_id) ON DELETE CASCADE,
    window_start_seconds REAL NOT NULL,
    window_end_seconds REAL NOT NULL,
    sample_count INTEGER NOT NULL CHECK (sample_count = 32),
    activity_label TEXT NOT NULL CHECK (length(trim(activity_label)) > 0),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    sampling_json TEXT NOT NULL CHECK (json_valid(sampling_json)),
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    config_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (window_end_seconds > window_start_seconds)
);
CREATE TABLE IF NOT EXISTS Engagement (
    engagement_id INTEGER PRIMARY KEY,
    detection_id INTEGER NOT NULL UNIQUE REFERENCES FaceDetection(detection_id),
    positive_score REAL NOT NULL CHECK (positive_score BETWEEN 0 AND 1),
    neutral_score REAL NOT NULL CHECK (neutral_score BETWEEN 0 AND 1),
    negative_score REAL NOT NULL CHECK (negative_score BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS idx_frame_video_id ON Frame(video_id);
CREATE INDEX IF NOT EXISTS idx_detection_person_id ON FaceDetection(person_id);
CREATE INDEX IF NOT EXISTS idx_detection_frame_id ON FaceDetection(frame_id);
COMMIT;
