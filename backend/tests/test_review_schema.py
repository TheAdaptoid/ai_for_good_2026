import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from conftest import pre_review_schema_sql

from analysis_db import storage
from analysis_db.contracts import DataError, REVIEW_TABLES, TABLES
from analysis_db.storage import assert_schema, connect_database, initialize_database

STARTER_LABELS = [
    (1, "Singing", "activity"), (2, "Dancing", "activity"), (3, "Acting", "activity"),
    (4, "Spoken Performance", "activity"), (5, "Instrumental Performance", "activity"),
    (6, "Rehearsal", "activity"), (7, "Group Performance", "activity"),
    (8, "Solo Performance", "activity"), (9, "Presenting Creative Work", "activity"),
    (10, "Sustained Participation", "observation"), (11, "Projecting Voice", "observation"),
    (12, "Collaboration", "observation"), (13, "Leadership", "observation"),
    (14, "Increased Participation", "observation"),
    (15, "Decreased Participation", "observation"),
    (16, "Visible Positive Affect", "observation"),
    (17, "Visible Neutral Affect", "observation"),
    (18, "Visible Negative Affect", "observation"),
]
REAL_DB = Path(__file__).resolve().parents[2] / "data" / "analysis.sqlite"


def six_table_db(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(pre_review_schema_sql())
        connection.executescript("""
            INSERT INTO Video (video_id, title, filename, file_path, duration_seconds, fps)
                VALUES (1, 'v', 'v.mp4', 'data/videos/v.mp4', 10.0, 24.0);
            INSERT INTO Frame VALUES ('f0', 1, 0, 0.0);
            INSERT INTO Person VALUES ('Person_0001');
            INSERT INTO FaceDetection (detection_id, person_id, frame_id, x1, y1, x2, y2, det_score)
                VALUES (1, 'Person_0001', 'f0', 1, 2, 3, 4, 0.9);
            INSERT INTO Activity VALUES (1, 1, 0, 31, 'Singing', 0.4);
            INSERT INTO Engagement VALUES (1, 1, 0.1, 0.7, 0.2);
        """)
        connection.commit()
    return path


def snapshot(path):
    with closing(sqlite3.connect(path)) as connection:
        master = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        rows = {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in TABLES}
    return master, rows


def test_review_tables_and_starter_labels(review_db):
    present = {name for (name,) in review_db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(REVIEW_TABLES) <= present
    labels = review_db.execute(
        "SELECT label_id, name, category FROM Label ORDER BY label_id").fetchall()
    assert labels == STARTER_LABELS
    assert review_db.execute("SELECT COUNT(*) FROM Label WHERE is_active = 1").fetchone() == (18,)


def test_initialize_twice_is_idempotent(tmp_path):
    db = tmp_path / "twice.sqlite"
    initialize_database(db)
    initialize_database(db)
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Label").fetchone() == (18,)


@pytest.mark.parametrize("column, value", [
    ("source", "MODEL"),
    ("review_status", "DONE"),
    ("confidence", 1.5),
    ("start_frame", 300),  # after end_frame
    ("start_frame", -1),
])
def test_annotation_checks(review_db, insert_ai_annotation, column, value):
    with pytest.raises(sqlite3.IntegrityError):
        insert_ai_annotation(review_db, **{column: value})


@pytest.mark.parametrize("score, method", [(-0.1, "m@1"), (1.2, None)])
def test_clip_priority_checks(review_db, score, method):
    with pytest.raises(sqlite3.IntegrityError):
        review_db.execute(
            "INSERT INTO ReviewClip (video_id, start_frame, end_frame, priority_score,"
            " priority_method, created_at) VALUES (1, 0, 10, ?, ?, 'now')", (score, method))


def test_clip_priority_may_exceed_one(review_db):
    review_db.execute(
        "INSERT INTO ReviewClip (video_id, start_frame, end_frame, priority_score,"
        " priority_method, created_at) VALUES (1, 0, 10, 2.07, 'positive-weighted@1', 'now')")


def insert_event(connection, annotation_id, reviewer_id="r-1"):
    connection.execute(
        "INSERT INTO ReviewEvent (annotation_id, video_id, action, new_source, new_status,"
        " reviewer_id, created_at) VALUES (?, 1, 'ACCEPTED', 'AI', 'ACCEPTED', ?, 'now')",
        (annotation_id, reviewer_id))


@pytest.mark.parametrize("reviewer_id", ["", "   "])
def test_blank_reviewer_rejected(review_db, insert_ai_annotation, reviewer_id):
    annotation_id = insert_ai_annotation(review_db)
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(review_db, annotation_id, reviewer_id)


def test_history_is_append_only(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    insert_event(review_db, annotation_id)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        review_db.execute("UPDATE ReviewEvent SET note = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        review_db.execute("DELETE FROM ReviewEvent")
    with pytest.raises(sqlite3.IntegrityError):
        review_db.execute("DELETE FROM Annotation WHERE annotation_id = ?", (annotation_id,))


def test_labels_cannot_be_deleted(review_db):
    with pytest.raises(sqlite3.IntegrityError, match="deactivate"):
        review_db.execute("DELETE FROM Label WHERE label_id = 1")


def test_assert_schema_default_accepts_six_table_db(tmp_path):
    db = six_table_db(tmp_path / "six.sqlite")
    connection = connect_database(db, must_exist=True)
    try:
        assert_schema(connection)
        with pytest.raises(DataError, match="Label"):
            assert_schema(connection, tables=REVIEW_TABLES)
    finally:
        connection.close()


def test_migration_preserves_rows_and_is_repeatable(tmp_path):
    db = six_table_db(tmp_path / "six.sqlite")
    _, before = snapshot(db)
    initialize_database(db)
    initialize_database(db)
    _, after = snapshot(db)
    assert after == before
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Label").fetchone() == (18,)
        for table in ("ReviewClip", "ReviewClipParticipant", "Annotation", "ReviewEvent"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


def test_migration_failure_rolls_back_completely(tmp_path, monkeypatch):
    db = six_table_db(tmp_path / "six.sqlite")
    before = snapshot(db)
    broken = tmp_path / "broken_schema.sql"
    text = storage.SCHEMA_PATH.read_text(encoding="utf-8")
    head, _, _ = text.rpartition("COMMIT;")
    broken.write_text(head + "THIS IS NOT SQL;\nCOMMIT;\n", encoding="utf-8")
    monkeypatch.setattr(storage, "SCHEMA_PATH", broken)
    with pytest.raises(sqlite3.Error):
        initialize_database(db)
    assert snapshot(db) == before


@pytest.mark.skipif(not REAL_DB.is_file(), reason="data/analysis.sqlite not present")
def test_real_database_migration(tmp_path):
    db = tmp_path / "real.sqlite"
    shutil.copyfile(REAL_DB, db)
    with closing(sqlite3.connect(REAL_DB)) as original:
        engagement = original.execute("SELECT * FROM Engagement ORDER BY 1").fetchall()
    initialize_database(db)
    initialize_database(db)
    with closing(sqlite3.connect(db)) as connection:
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("Video", "Person", "FaceDetection", "Engagement", "Label")}
        assert counts == {"Video": 12, "Person": 100, "FaceDetection": 50514,
                          "Engagement": 50514, "Label": 18}
        assert connection.execute("SELECT * FROM Engagement ORDER BY 1").fetchall() == engagement
