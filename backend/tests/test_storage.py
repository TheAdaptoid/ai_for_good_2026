import sqlite3

import pytest

from analysis_db.contracts import DataError, REVIEW_TABLES, TABLES, VideoMetadata
from analysis_db.storage import (
    assert_schema,
    connect_database,
    ensure_detection,
    ensure_frame,
    ensure_person,
    ensure_video,
    initialize_database,
    table_counts,
)


def test_idempotent_init_and_conflicting_reimport(tmp_path, make_row):
    db = tmp_path / "analysis.sqlite"
    assert initialize_database(db) == dict.fromkeys(TABLES, 0)
    con = connect_database(db)
    try:
        assert con.execute("PRAGMA foreign_keys").fetchone() == (1,)
        con.execute("BEGIN")
        row = make_row()
        vid, inserted = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata(fps=24.0))
        assert inserted
        assert ensure_person(con, row.person_id)
        assert ensure_frame(con, row, vid)
        first_id, inserted = ensure_detection(con, row)
        assert inserted
        assert ensure_detection(con, row) == (first_id, False)
        with pytest.raises(DataError):
            ensure_detection(con, make_row(x2=99.0))
        con.commit()
    finally:
        con.close()
    assert initialize_database(db)["FaceDetection"] == 1


def test_foreign_key_enforced_without_csv_validator(tmp_path):
    db = tmp_path / "analysis.sqlite"
    initialize_database(db)
    con = connect_database(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO Frame VALUES (?, ?, ?, ?)", ("f", 999, 0, 0.0))
    finally:
        con.close()


@pytest.mark.parametrize("entity,statement", [
    ("Person", "INSERT INTO Person VALUES (?)"),
    ("Frame", "INSERT INTO Frame VALUES (?, ?, ?, ?)"),
    ("FaceDetection",
     "INSERT INTO FaceDetection (person_id, frame_id, x1, y1, x2, y2, det_score)"
     " VALUES (?, ?, ?, ?, ?, ?, ?)"),
])
def test_required_ids_reject_null_and_blank(tmp_path, entity, statement):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        for bad in (None, "", "   "):
            if entity == "FaceDetection":
                params = (bad, bad, 1.0, 2.0, 10.0, 20.0, 0.9)
            elif entity == "Frame":
                params = (bad, 1, 0, 0.0)
            else:
                params = (bad,)
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(statement, params)
    finally:
        con.close()


def test_frame_alternate_unique_key_rejects_second_id(tmp_path, make_row):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        con.execute("BEGIN")
        row = make_row()
        vid, _ = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata())
        assert ensure_frame(con, row, vid)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO Frame VALUES (?, ?, ?, ?)",
                        ("frame-0-b", vid, 0, 0.0))
        con.rollback()
    finally:
        con.close()


@pytest.mark.parametrize("change", [None, "title", "filename", "path", "fps", "width"])
def test_video_conflicts_raise(tmp_path, make_row, change):
    db = tmp_path / "db.sqlite"
    initialize_database(db)
    con = connect_database(db)
    try:
        row = make_row()
        metadata = VideoMetadata(fps=24.0, width=1920)
        vid, inserted = ensure_video(con, row, "data/videos/clip.mp4", metadata)
        assert inserted
        if change is None:
            again, inserted = ensure_video(con, row, "data/videos/clip.mp4", metadata)
            assert not inserted
            assert again == vid
            return
        changed_row, changed_meta, path = row, metadata, "data/videos/clip.mp4"
        if change == "title":
            changed_row = make_row(video_title="Other")
        elif change == "filename":
            changed_row = make_row(video_filename="other.mp4")
        elif change == "path":
            path = "data/videos/other.mp4"
        elif change == "fps":
            changed_meta = VideoMetadata(fps=30.0, width=1920)
        else:
            changed_meta = VideoMetadata(fps=24.0, width=1280)
        with pytest.raises(DataError):
            ensure_video(con, changed_row, path, changed_meta)
    finally:
        con.close()


def test_video_duplicate_metadata_match_reuses_id(tmp_path, make_row):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        row = make_row()
        vid, inserted = ensure_video(con, row, "data/videos/clip.mp4",
                                     VideoMetadata(fps=24.0, width=None, height=None))
        assert inserted
        again, inserted = ensure_video(con, row, "data/videos/clip.mp4",
                                       VideoMetadata(fps=24.0, width=None, height=None))
        assert (again, inserted) == (vid, False)
    finally:
        con.close()


@pytest.mark.parametrize("change", ["video", "timestamp"])
def test_frame_conflicts_raise(tmp_path, make_row, change):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        con.execute("BEGIN")
        row = make_row()
        vid, _ = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata())
        other_vid, _ = ensure_video(con, make_row(video_filename="other.mp4"),
                                    "data/videos/other.mp4", VideoMetadata())
        assert ensure_frame(con, row, vid)
        if change == "video":
            with pytest.raises(DataError):
                ensure_frame(con, row, other_vid)
        else:
            with pytest.raises(DataError):
                ensure_frame(con, make_row(source_time_seconds=1.5), vid)
        con.rollback()
    finally:
        con.close()


def test_frame_duplicate_reuses(tmp_path, make_row):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        con.execute("BEGIN")
        row = make_row()
        vid, _ = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata())
        assert ensure_frame(con, row, vid)
        assert not ensure_frame(con, row, vid)
        con.rollback()
    finally:
        con.close()


def test_person_reuse(tmp_path, make_row):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        con.execute("BEGIN")
        assert ensure_person(con, make_row().person_id)
        assert not ensure_person(con, make_row().person_id)
        con.rollback()
    finally:
        con.close()


@pytest.mark.parametrize("field,value", [
    ("x1", 10.0), ("y1", 20.0), ("x2", 1.0), ("y2", 2.0), ("det_score", 1.5), ("det_score", -0.1),
])
def test_detection_sql_checks_reject_invalid(tmp_path, make_row, field, value):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        con.execute("BEGIN")
        row = make_row()
        vid, _ = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata())
        ensure_person(con, row.person_id)
        ensure_frame(con, row, vid)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO FaceDetection (person_id, frame_id, x1, y1, x2, y2, det_score)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row.person_id, row.frame_id,
                 value if field == "x1" else row.x1,
                 value if field == "y1" else row.y1,
                 value if field == "x2" else row.x2,
                 value if field == "y2" else row.y2,
                 value if field == "det_score" else row.det_score))
        con.rollback()
    finally:
        con.close()


@pytest.mark.parametrize("start,end,valid", [(0, 0, False), (-7.5, 7.5, True)])
def test_activity_frame_interval(tmp_path, make_row, start, end, valid):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        con.execute("BEGIN")
        row = make_row()
        vid, _ = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata())
        ensure_person(con, row.person_id)
        ensure_frame(con, row, vid)
        det = ensure_detection(con, row)[0]
        statement = ("INSERT INTO Activity (frame_id,window_start_seconds,window_end_seconds,"
                     " sample_count,activity_label,score,result_json,sampling_json,config_json,config_hash,input_hash)"
                     " VALUES (?, ?, ?, 32, ?, ?, '{}', '{}', '{}', 'c', 'i')")
        params = (row.frame_id, start, end, "walking", 0.5)
        if valid:
            con.execute(statement, params)
        else:
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(statement, params)
        con.rollback()
    finally:
        con.close()


@pytest.mark.parametrize("scores,valid", [
    ((1.1, 0.8, 0.8), False), ((0.8, -0.1, 0.8), False), ((0.8, 0.8, 1.5), False),
    ((0.8, 0.8, 0.8), True),
])
def test_engagement_score_ranges(tmp_path, make_row, scores, valid):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        con.execute("BEGIN")
        row = make_row()
        vid, _ = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata())
        ensure_person(con, row.person_id)
        ensure_frame(con, row, vid)
        det = ensure_detection(con, row)[0]
        statement = ("INSERT INTO Engagement (detection_id, positive_score,"
                     " neutral_score, negative_score) VALUES (?, ?, ?, ?)")
        params = (det, *scores)
        if valid:
            con.execute(statement, params)
        else:
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(statement, params)
        con.rollback()
    finally:
        con.close()


def test_required_indexes_exist(tmp_path):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        names = {row[0] for row in
                 con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert {"idx_frame_video_id", "idx_detection_person_id",
                "idx_detection_frame_id"} <= names
    finally:
        con.close()


def test_schema_has_no_image_path_columns(tmp_path):
    initialize_database(tmp_path / "db2.sqlite")
    con = connect_database(tmp_path / "db2.sqlite")
    try:
        for table in TABLES + REVIEW_TABLES:
            columns = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
            assert columns
            for column in columns:
                lowered = column.lower()
                assert "image" not in lowered and "img" not in lowered
                assert not ("path" in lowered and table != "Video")
    finally:
        con.close()


def test_assert_schema_requires_initialization(tmp_path):
    con = connect_database(tmp_path / "empty.sqlite")
    try:
        with pytest.raises(DataError, match="initialize"):
            assert_schema(con)
    finally:
        con.close()
    initialize_database(tmp_path / "empty.sqlite")
    con = connect_database(tmp_path / "empty.sqlite")
    try:
        assert_schema(con)
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_rollback_leaves_zero_rows(tmp_path, make_row):
    db = tmp_path / "db.sqlite"
    initialize_database(db)
    con = connect_database(db)
    try:
        con.execute("BEGIN")
        row = make_row()
        vid, _ = ensure_video(con, row, "data/videos/clip.mp4", VideoMetadata(fps=24.0))
        ensure_person(con, row.person_id)
        ensure_frame(con, row, vid)
        ensure_detection(con, row)
        con.rollback()
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_must_exist_never_creates(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        connect_database(missing, must_exist=True)
    assert not missing.exists()


def test_read_only_connection_reads_but_rejects_writes(tmp_path):
    database = tmp_path / "read_only.sqlite"
    initialize_database(database)
    connection = connect_database(database, read_only=True)
    try:
        assert table_counts(connection) == dict.fromkeys(TABLES, 0)
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO Person VALUES ('blocked')")
    finally:
        connection.close()


def test_read_only_connection_never_creates_database(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        connect_database(missing, read_only=True)
    assert not missing.exists()
