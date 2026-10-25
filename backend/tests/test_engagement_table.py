import csv
import sqlite3

import pytest

from analysis_db.contracts import DataError
from analysis_db.engagement_table import replace_engagement
from analysis_db.storage import connect_database, initialize_database
from conftest import pre_review_schema_sql

HEADER = ["observation_row", "detection_id", "person_id", "positive_score", "negative_score",
          "neutral_score", "suggested_label"]


def write(path, *rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "analysis.sqlite"
    initialize_database(path)
    con = connect_database(path)
    con.executescript("""
        INSERT INTO Video (video_id, title, filename, file_path)
            VALUES (1, 'Clip', 'clip.mp4', 'data/videos/clip.mp4');
        INSERT INTO Person VALUES ('Person_0001');
        INSERT INTO Frame VALUES ('V0001_F000000010', 1, 10, 0.5);
        INSERT INTO Frame VALUES ('V0001_F000000011', 1, 11, 0.55);
        INSERT INTO FaceDetection VALUES (4, 'Person_0001', 'V0001_F000000010', 0, 0, 5, 5, 0.9);
        INSERT INTO FaceDetection VALUES (8, 'Person_0001', 'V0001_F000000011', 0, 0, 5, 5, 0.9);
        INSERT INTO Engagement VALUES (1, 4, 0.1, 0.1, 0.8);
    """)
    con.close()
    return path


def engagement(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT detection_id, positive_score, neutral_score, negative_score"
                           " FROM Engagement ORDER BY detection_id").fetchall()
    finally:
        con.close()


def run(path, source):
    con = connect_database(path)
    try:
        return replace_engagement(con, source)
    finally:
        con.close()


def test_replaces_scores_and_skips_unscored_rows(tmp_path, db):
    source = write(tmp_path / "results.csv",
                   [0, 4, "Person_0001", 0.7, 0.1, 0.2, "Positive"],
                   [1, 8, "Person_0001", "", "", "", ""])
    assert run(db, source) == {"inserted": 1, "skipped": 1, "skipped_missing_detections": 0,
                               "detections_without_engagement": 1}
    assert engagement(db) == [(4, 0.7, 0.2, 0.1)]


def test_skip_missing_detections_drops_reclustered_ids(tmp_path, db):
    source = write(tmp_path / "results.csv",
                   [0, 4, "Person_0001", 0.7, 0.1, 0.2, "Positive"],
                   [1, 99, "Person_0001", 0.6, 0.2, 0.2, "Positive"])
    con = connect_database(db)
    try:
        result = replace_engagement(con, source, skip_missing_detections=True)
    finally:
        con.close()
    assert result["inserted"] == 1 and result["skipped_missing_detections"] == 1
    assert engagement(db) == [(4, 0.7, 0.2, 0.1)]


def test_unknown_detection_rolls_back(tmp_path, db):
    before = engagement(db)
    source = write(tmp_path / "results.csv", [0, 99, "Person_0001", 0.7, 0.1, 0.2, "Positive"])
    with pytest.raises(sqlite3.IntegrityError):
        run(db, source)
    assert engagement(db) == before


@pytest.mark.parametrize("row", [
    [0, 4, "Person_0001", 1.5, 0.1, 0.2, "Positive"],
    [0, "x", "Person_0001", 0.7, 0.1, 0.2, "Positive"],
])
def test_invalid_rows_rejected_before_writing(tmp_path, db, row):
    before = engagement(db)
    with pytest.raises(DataError):
        run(db, write(tmp_path / "results.csv", row))
    assert engagement(db) == before


def test_duplicate_detection_rejected(tmp_path, db):
    source = write(tmp_path / "results.csv",
                   [0, 4, "Person_0001", 0.7, 0.1, 0.2, "Positive"],
                   [1, 4, "Person_0001", 0.6, 0.2, 0.2, "Positive"])
    with pytest.raises(DataError, match="duplicate"):
        run(db, source)


def test_replace_engagement_on_six_table_database(tmp_path):
    path = tmp_path / "six.sqlite"
    con = connect_database(path)
    con.executescript(pre_review_schema_sql())
    con.executescript("""
        INSERT INTO Video (video_id, title, filename, file_path)
            VALUES (1, 'Clip', 'clip.mp4', 'data/videos/clip.mp4');
        INSERT INTO Person VALUES ('Person_0001');
        INSERT INTO Frame VALUES ('V0001_F000000010', 1, 10, 0.5);
        INSERT INTO FaceDetection VALUES (4, 'Person_0001', 'V0001_F000000010', 0, 0, 5, 5, 0.9);
    """)
    con.close()
    source = write(tmp_path / "results.csv", [0, 4, "Person_0001", 0.7, 0.1, 0.2, "Positive"])
    assert run(path, source)["inserted"] == 1
    assert engagement(path) == [(4, 0.7, 0.2, 0.1)]


def test_reimport_preserves_audited_record_ids_and_history(tmp_path, db):
    from analysis_db.corrections import correct_engagement
    con = connect_database(db)
    try:
        correct_engagement(con, 1, 0.6, 0.3, 0.1)
        history = con.execute("SELECT * FROM EngagementAudit").fetchall()
        source = write(tmp_path / "results.csv", [0, 4, "Person_0001", 0.7, 0.1, 0.2, "Positive"])
        replace_engagement(con, source)
        assert con.execute("SELECT engagement_id,positive_score FROM Engagement").fetchall() == [(1, 0.7)]
        assert con.execute("SELECT * FROM EngagementAudit").fetchall() == history
    finally:
        con.close()


def test_import_cannot_remove_audited_records(tmp_path, db):
    from analysis_db.corrections import correct_engagement
    con = connect_database(db)
    try:
        correct_engagement(con, 1, 0.6, 0.3, 0.1)
        before = con.execute("SELECT * FROM Engagement").fetchall()
        source = write(tmp_path / "results.csv", [0, 8, "Person_0001", 0.7, 0.1, 0.2, "Positive"])
        with pytest.raises(sqlite3.IntegrityError):
            replace_engagement(con, source)
        assert con.execute("SELECT * FROM Engagement").fetchall() == before
        assert con.execute("SELECT COUNT(*) FROM EngagementAudit").fetchone() == (1,)
    finally:
        con.close()
