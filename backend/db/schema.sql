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
    detection_id INTEGER NOT NULL UNIQUE REFERENCES FaceDetection(detection_id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    activity_label TEXT NOT NULL,
    confidence REAL NOT NULL,
    CHECK (end_frame = start_frame + 31)
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

-- Review model (Spec 001). Additive only: Activity and Engagement above stay as raw machine signals.
CREATE TABLE IF NOT EXISTS Label (
    label_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    category TEXT NOT NULL CHECK (category IN ('activity', 'observation')),
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_label_category_name ON Label(category, name COLLATE NOCASE);
CREATE TRIGGER IF NOT EXISTS label_no_delete BEFORE DELETE ON Label
BEGIN
    SELECT RAISE(ABORT, 'labels cannot be deleted; deactivate instead');
END;
INSERT OR IGNORE INTO Label (label_id, name, category) VALUES
    (1, 'Singing', 'activity'),
    (2, 'Dancing', 'activity'),
    (3, 'Acting', 'activity'),
    (4, 'Spoken Performance', 'activity'),
    (5, 'Instrumental Performance', 'activity'),
    (6, 'Rehearsal', 'activity'),
    (7, 'Group Performance', 'activity'),
    (8, 'Solo Performance', 'activity'),
    (9, 'Presenting Creative Work', 'activity'),
    (10, 'Sustained Participation', 'observation'),
    (11, 'Projecting Voice', 'observation'),
    (12, 'Collaboration', 'observation'),
    (13, 'Leadership', 'observation'),
    (14, 'Increased Participation', 'observation'),
    (15, 'Decreased Participation', 'observation'),
    (16, 'Visible Positive Affect', 'observation'),
    (17, 'Visible Neutral Affect', 'observation'),
    (18, 'Visible Negative Affect', 'observation');
CREATE TABLE IF NOT EXISTS ReviewClip (
    clip_id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES Video(video_id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    priority_score REAL CHECK (priority_score IS NULL OR priority_score >= 0),
    priority_method TEXT,
    import_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    CHECK (0 <= start_frame AND start_frame <= end_frame),
    CHECK (priority_score IS NULL OR priority_method IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_clip_video_start ON ReviewClip(video_id, start_frame);
CREATE INDEX IF NOT EXISTS idx_clip_priority ON ReviewClip(priority_score DESC);
CREATE TABLE IF NOT EXISTS ReviewClipParticipant (
    clip_id INTEGER NOT NULL REFERENCES ReviewClip(clip_id) ON DELETE CASCADE,
    person_id TEXT NOT NULL REFERENCES Person(person_id),
    PRIMARY KEY (clip_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_clip_participant_person ON ReviewClipParticipant(person_id);
CREATE TABLE IF NOT EXISTS Annotation (
    annotation_id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES Video(video_id),
    clip_id INTEGER REFERENCES ReviewClip(clip_id),
    person_id TEXT REFERENCES Person(person_id),
    label_id INTEGER NOT NULL REFERENCES Label(label_id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    source TEXT NOT NULL CHECK (source IN ('AI', 'HUMAN')),
    review_status TEXT NOT NULL
        CHECK (review_status IN ('UNREVIEWED', 'ACCEPTED', 'EDITED', 'REJECTED', 'DEFERRED')),
    import_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (0 <= start_frame AND start_frame <= end_frame)
);
CREATE INDEX IF NOT EXISTS idx_annotation_video_start ON Annotation(video_id, start_frame);
CREATE INDEX IF NOT EXISTS idx_annotation_person ON Annotation(person_id);
CREATE INDEX IF NOT EXISTS idx_annotation_label ON Annotation(label_id);
CREATE INDEX IF NOT EXISTS idx_annotation_status ON Annotation(review_status);
CREATE INDEX IF NOT EXISTS idx_annotation_clip ON Annotation(clip_id);
CREATE TABLE IF NOT EXISTS ReviewEvent (
    event_id INTEGER PRIMARY KEY,
    annotation_id INTEGER NOT NULL REFERENCES Annotation(annotation_id),
    video_id INTEGER NOT NULL REFERENCES Video(video_id),
    action TEXT NOT NULL
        CHECK (action IN ('CREATED', 'ACCEPTED', 'EDITED', 'REJECTED', 'DEFERRED')),
    prev_label_id INTEGER REFERENCES Label(label_id),
    new_label_id INTEGER REFERENCES Label(label_id),
    prev_start_frame INTEGER,
    prev_end_frame INTEGER,
    new_start_frame INTEGER,
    new_end_frame INTEGER,
    prev_person_id TEXT,
    new_person_id TEXT,
    prev_confidence REAL,
    new_confidence REAL,
    prev_source TEXT,
    new_source TEXT NOT NULL,
    prev_status TEXT,
    new_status TEXT NOT NULL,
    reviewer_id TEXT NOT NULL CHECK (length(trim(reviewer_id)) > 0),
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_event_annotation ON ReviewEvent(annotation_id);
CREATE TRIGGER IF NOT EXISTS review_event_no_update BEFORE UPDATE ON ReviewEvent
BEGIN
    SELECT RAISE(ABORT, 'review history is append-only');
END;
CREATE TRIGGER IF NOT EXISTS review_event_no_delete BEFORE DELETE ON ReviewEvent
BEGIN
    SELECT RAISE(ABORT, 'review history is append-only');
END;
COMMIT;
