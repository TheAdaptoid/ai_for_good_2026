import csv
import sqlite3

import pytest

from analysis_db.contracts import DataError
from analysis_db.identity_tables import replace_identity_tables
from analysis_db.storage import connect_database, initialize_database


def write(path, header, *rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "analysis.sqlite"
    initialize_database(path)
    con = connect_database(path)
    con.executescript("""
        INSERT INTO Video (video_id, title, filename, file_path)
            VALUES (3, 'Clip', 'clip.mp4', 'data/videos/clip.mp4');
        INSERT INTO Person VALUES ('Person_old');
        INSERT INTO Frame VALUES ('old-frame', 3, 0, 0.0);
        INSERT INTO FaceDetection VALUES (1, 'Person_old', 'old-frame', 0, 0, 5, 5, 0.5);
        INSERT INTO Activity (frame_id,window_start_seconds,window_end_seconds,
            sample_count,activity_label,score,result_json,sampling_json,config_json,config_hash,input_hash)
            VALUES ('old-frame',-7.5,7.5,32,'Dancing',0.9,'{}','{}','{}','c','i');
    """)
    con.close()
    return path


def write_tables(directory, detections):
    directory.mkdir()
    # VIDEO.csv numbers videos differently from the database: rows map by filename.
    write(directory / "VIDEO.csv", ["video_id", "title", "filename", "file_path"],
          [1, "Clip", "clip.mp4", "GivenData/clip.mp4"])
    write(directory / "FRAME.csv", ["frame_id", "video_id", "frame_number", "source_time_seconds"],
          ["V0001_F000000010", 1, 10, 0.5], ["V0001_F000000011", 1, 11, 0.55])
    write(directory / "PERSON.csv", ["person_id"], ["Person_0001"], ["Person_0002"])
    write(directory / "FACE_DETECTION.csv",
          ["detection_id", "person_id", "frame_id", "x1", "y1", "x2", "y2", "det_score"],
          *detections)
    return directory


def snapshot(path):
    con = sqlite3.connect(path)
    try:
        return {table: con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("Video", "Frame", "Person", "FaceDetection", "Activity")}
    finally:
        con.close()


def test_replaces_identity_tables_and_keeps_video(tmp_path, db):
    before = snapshot(db)
    tables = write_tables(tmp_path / "Database", [
        [7, "Person_0001", "V0001_F000000010", 1, 2, 30, 40, 0.9],
        [9, "Person_0002", "V0001_F000000011", 5, 6, 50, 60, 0.8]])
    con = connect_database(db)
    try:
        counts = replace_identity_tables(con, tables)
    finally:
        con.close()
    after = snapshot(db)
    assert counts["Frame"] == 2 and counts["FaceDetection"] == 2 and counts["Activity"] == 0
    assert after["Video"] == before["Video"]
    assert after["Frame"] == [("V0001_F000000010", 3, 10, 0.5), ("V0001_F000000011", 3, 11, 0.55)]
    assert [row[0] for row in after["FaceDetection"]] == [7, 9]
    assert after["Person"] == [("Person_0001",), ("Person_0002",)]


def test_failure_rolls_back_everything(tmp_path, db):
    before = snapshot(db)
    tables = write_tables(tmp_path / "Database", [
        [7, "Person_0001", "V0001_F000000010", 1, 2, 30, 40, 0.9],
        [9, "Person_missing", "V0001_F000000011", 5, 6, 50, 60, 0.8]])
    con = connect_database(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            replace_identity_tables(con, tables)
    finally:
        con.close()
    assert snapshot(db) == before


def test_unknown_video_rejected_before_writing(tmp_path, db):
    before = snapshot(db)
    tables = write_tables(tmp_path / "Database", [])
    write(tables / "VIDEO.csv", ["video_id", "filename"], [1, "other.mp4"])
    con = connect_database(db)
    try:
        with pytest.raises(DataError, match="other.mp4"):
            replace_identity_tables(con, tables)
    finally:
        con.close()
    assert snapshot(db) == before
