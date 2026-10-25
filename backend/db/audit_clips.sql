BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS ActivityAudit (
    audit_id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES Activity(activity_id),
    old_label TEXT NOT NULL,
    new_label TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    changed_by TEXT
);
CREATE TABLE IF NOT EXISTS EngagementAudit (
    audit_id INTEGER PRIMARY KEY,
    engagement_id INTEGER NOT NULL REFERENCES Engagement(engagement_id),
    old_positive_score REAL NOT NULL,
    new_positive_score REAL NOT NULL,
    old_neutral_score REAL NOT NULL,
    new_neutral_score REAL NOT NULL,
    old_negative_score REAL NOT NULL,
    new_negative_score REAL NOT NULL,
    changed_at TEXT NOT NULL,
    changed_by TEXT
);
CREATE TABLE IF NOT EXISTS Clip (
    clip_id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES Video(video_id),
    start_time_seconds REAL NOT NULL CHECK (start_time_seconds >= 0),
    end_time_seconds REAL NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (end_time_seconds > start_time_seconds)
);
CREATE TABLE IF NOT EXISTS ClipPerson (
    clip_id INTEGER NOT NULL REFERENCES Clip(clip_id),
    person_id TEXT NOT NULL REFERENCES Person(person_id),
    PRIMARY KEY (clip_id, person_id)
);
CREATE TABLE IF NOT EXISTS ClipGeneration (
    video_id INTEGER PRIMARY KEY REFERENCES Video(video_id),
    persistence_frames INTEGER NOT NULL CHECK (
        typeof(persistence_frames) = 'integer' AND persistence_frames > 0),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_audit_activity ON ActivityAudit(activity_id, audit_id);
CREATE INDEX IF NOT EXISTS idx_engagement_audit_engagement ON EngagementAudit(engagement_id, audit_id);
CREATE INDEX IF NOT EXISTS idx_clip_video_time ON Clip(video_id, start_time_seconds, end_time_seconds);
CREATE INDEX IF NOT EXISTS idx_clip_person_person ON ClipPerson(person_id);
CREATE INDEX IF NOT EXISTS idx_frame_video_time ON Frame(video_id, source_time_seconds);

CREATE TRIGGER IF NOT EXISTS activity_audit_no_update BEFORE UPDATE ON ActivityAudit
BEGIN SELECT RAISE(ABORT, 'ActivityAudit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS activity_audit_no_delete BEFORE DELETE ON ActivityAudit
BEGIN SELECT RAISE(ABORT, 'ActivityAudit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS activity_audit_no_replace BEFORE INSERT ON ActivityAudit
WHEN EXISTS (SELECT 1 FROM ActivityAudit WHERE audit_id = NEW.audit_id)
BEGIN SELECT RAISE(ABORT, 'ActivityAudit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS engagement_audit_no_update BEFORE UPDATE ON EngagementAudit
BEGIN SELECT RAISE(ABORT, 'EngagementAudit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS engagement_audit_no_delete BEFORE DELETE ON EngagementAudit
BEGIN SELECT RAISE(ABORT, 'EngagementAudit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS engagement_audit_no_replace BEFORE INSERT ON EngagementAudit
WHEN EXISTS (SELECT 1 FROM EngagementAudit WHERE audit_id = NEW.audit_id)
BEGIN SELECT RAISE(ABORT, 'EngagementAudit is append-only'); END;

CREATE TRIGGER IF NOT EXISTS clip_validate_insert BEFORE INSERT ON Clip
BEGIN
    SELECT RAISE(ABORT, 'Clip video duration is missing or boundaries are outside video')
    WHERE NOT EXISTS (
        SELECT 1 FROM Video WHERE video_id = NEW.video_id
        AND duration_seconds > 0 AND duration_seconds < 1e999
        AND NEW.start_time_seconds >= 0 AND NEW.end_time_seconds <= duration_seconds);
    SELECT RAISE(ABORT, 'Clips must not overlap') WHERE EXISTS (
        SELECT 1 FROM Clip WHERE video_id = NEW.video_id
        AND start_time_seconds < NEW.end_time_seconds
        AND end_time_seconds > NEW.start_time_seconds);
    SELECT RAISE(ABORT, 'Clips are immutable') WHERE EXISTS (
        SELECT 1 FROM Clip WHERE clip_id = NEW.clip_id);
    SELECT RAISE(ABORT, 'Video clips are finalized') WHERE EXISTS (
        SELECT 1 FROM ClipGeneration WHERE video_id = NEW.video_id);
END;
CREATE TRIGGER IF NOT EXISTS clip_no_update BEFORE UPDATE ON Clip
BEGIN SELECT RAISE(ABORT, 'Clips are immutable'); END;
CREATE TRIGGER IF NOT EXISTS clip_no_delete BEFORE DELETE ON Clip
BEGIN SELECT RAISE(ABORT, 'Clips are immutable'); END;
CREATE TRIGGER IF NOT EXISTS clip_person_no_update BEFORE UPDATE ON ClipPerson
BEGIN SELECT RAISE(ABORT, 'Clip membership is immutable'); END;
CREATE TRIGGER IF NOT EXISTS clip_person_no_delete BEFORE DELETE ON ClipPerson
BEGIN SELECT RAISE(ABORT, 'Clip membership is immutable'); END;
CREATE TRIGGER IF NOT EXISTS clip_person_validate_insert BEFORE INSERT ON ClipPerson
WHEN EXISTS (
    SELECT 1 FROM Clip JOIN ClipGeneration USING (video_id) WHERE clip_id = NEW.clip_id)
OR EXISTS (SELECT 1 FROM ClipPerson WHERE clip_id = NEW.clip_id AND person_id = NEW.person_id)
BEGIN SELECT RAISE(ABORT, 'Clip membership is immutable'); END;
CREATE TRIGGER IF NOT EXISTS clip_generation_no_update BEFORE UPDATE ON ClipGeneration
BEGIN SELECT RAISE(ABORT, 'Clip generation is final'); END;
CREATE TRIGGER IF NOT EXISTS clip_generation_no_delete BEFORE DELETE ON ClipGeneration
BEGIN SELECT RAISE(ABORT, 'Clip generation is final'); END;
CREATE TRIGGER IF NOT EXISTS clip_generation_no_replace BEFORE INSERT ON ClipGeneration
WHEN EXISTS (SELECT 1 FROM ClipGeneration WHERE video_id = NEW.video_id)
BEGIN SELECT RAISE(ABORT, 'Clip generation is final'); END;
CREATE TRIGGER IF NOT EXISTS clip_video_duration_guard BEFORE UPDATE OF duration_seconds ON Video
WHEN EXISTS (SELECT 1 FROM Clip WHERE video_id = OLD.video_id)
AND (NEW.duration_seconds IS NULL OR NEW.duration_seconds <= 0
     OR NEW.duration_seconds >= 1e999
     OR NEW.duration_seconds < (SELECT MAX(end_time_seconds) FROM Clip WHERE video_id = OLD.video_id))
BEGIN SELECT RAISE(ABORT, 'Video duration would invalidate clips'); END;
CREATE TRIGGER IF NOT EXISTS clip_video_no_replace BEFORE INSERT ON Video
WHEN EXISTS (
    SELECT 1 FROM Video v
    WHERE (v.video_id = NEW.video_id OR v.filename = NEW.filename OR v.file_path = NEW.file_path)
    AND (EXISTS (SELECT 1 FROM ClipGeneration WHERE video_id = v.video_id)
         OR EXISTS (SELECT 1 FROM Clip WHERE video_id = v.video_id)))
BEGIN SELECT RAISE(ABORT, 'Video replacement would invalidate finalized clips'); END;
CREATE TRIGGER IF NOT EXISTS clip_video_no_replace_update BEFORE UPDATE ON Video
WHEN EXISTS (
    SELECT 1 FROM Video v
    WHERE v.video_id != OLD.video_id
    AND (v.video_id = NEW.video_id OR v.filename = NEW.filename OR v.file_path = NEW.file_path)
    AND (EXISTS (SELECT 1 FROM ClipGeneration WHERE video_id = v.video_id)
         OR EXISTS (SELECT 1 FROM Clip WHERE video_id = v.video_id)))
BEGIN SELECT RAISE(ABORT, 'Video replacement would invalidate finalized clips'); END;
COMMIT;
