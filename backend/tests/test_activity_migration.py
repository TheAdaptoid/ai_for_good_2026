import sqlite3

import pytest

from analysis_db.storage import connect_database, initialize_database
from analysis_db.contracts import DataError


LEGACY = """CREATE TABLE Activity (
    activity_id INTEGER PRIMARY KEY,
    detection_id INTEGER NOT NULL UNIQUE REFERENCES FaceDetection(detection_id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    activity_label TEXT NOT NULL,
    confidence REAL NOT NULL,
    CHECK (end_frame = start_frame + 31)
)"""


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "legacy.sqlite"
    initialize_database(path)
    c = connect_database(path)
    c.executescript("""
        DROP TABLE Activity;
        INSERT INTO Video(video_id,title,filename,file_path) VALUES(1,'v','v.mp4','v.mp4');
        INSERT INTO Frame VALUES('f',1,0,0);
        INSERT INTO Person VALUES('p');
        INSERT INTO FaceDetection VALUES(1,'p','f',0,0,10,10,0.9);
        INSERT INTO Engagement VALUES(1,1,0.2,0.3,0.5);
    """ + LEGACY + ";")
    yield c
    c.close()


def snapshot(c):
    return {t: c.execute(f"SELECT * FROM {t}").fetchall()
            for t in ("Video", "Frame", "Person", "FaceDetection", "Engagement")}


def test_migration_preserves_other_tables_and_is_idempotent(legacy):
    from analysis_db.activity_schema import migrate_activity
    before = snapshot(legacy)
    assert migrate_activity(legacy) is True
    assert snapshot(legacy) == before
    assert "frame_id" in [r[1] for r in legacy.execute("PRAGMA table_info(Activity)")]
    assert migrate_activity(legacy) is False
    assert legacy.execute("PRAGMA foreign_key_check").fetchall() == []


def test_nonempty_legacy_is_rejected_without_losing_results(legacy):
    from analysis_db.activity_schema import migrate_activity
    legacy.execute("INSERT INTO Activity VALUES(1,1,0,31,'Dancing',0.5)")
    with pytest.raises(DataError, match="not empty"):
        migrate_activity(legacy)
    assert legacy.execute("SELECT COUNT(*) FROM Activity").fetchone() == (1,)


def test_unknown_schema_is_rejected(legacy):
    from analysis_db.activity_schema import migrate_activity
    legacy.execute("ALTER TABLE Activity ADD COLUMN surprise TEXT")
    with pytest.raises(DataError, match="Unknown"):
        migrate_activity(legacy)


def test_integrity_failure_rolls_back_schema_change(legacy, monkeypatch):
    import analysis_db.activity_schema as module
    before = legacy.execute("SELECT sql FROM sqlite_master WHERE name='Activity'").fetchone()
    def fail(_):
        raise DataError("injected validation failure")
    monkeypatch.setattr(module, "check_integrity", fail)
    with pytest.raises(DataError, match="injected"):
        module.migrate_activity(legacy)
    assert legacy.execute("SELECT sql FROM sqlite_master WHERE name='Activity'").fetchone() == before


def test_fresh_and_migrated_constraints_match(legacy, tmp_path):
    from analysis_db.activity_schema import migrate_activity
    migrate_activity(legacy)
    path = tmp_path / "fresh.sqlite"
    initialize_database(path)
    fresh = connect_database(path)
    try:
        assert fresh.execute("PRAGMA table_info(Activity)").fetchall() == legacy.execute("PRAGMA table_info(Activity)").fetchall()
        assert fresh.execute("PRAGMA foreign_key_list(Activity)").fetchall() == legacy.execute("PRAGMA foreign_key_list(Activity)").fetchall()
    finally:
        fresh.close()


def test_schema_comparison_preserves_sql_string_literals(legacy):
    from analysis_db.activity_schema import activity_ddl, migrate_activity
    legacy.execute("DROP TABLE Activity")
    legacy.execute(activity_ddl().replace("%H", "%h"))
    with pytest.raises(DataError, match="Unknown"):
        migrate_activity(legacy)


@pytest.mark.parametrize("field,value", [
    ("frame_id","missing"),("sample_count",31),("score",1.1),
    ("activity_label"," "),("window_end_seconds",-8),("result_json","not-json"),
])
def test_migrated_schema_rejects_invalid_activity(legacy,field,value):
    from analysis_db.activity_schema import migrate_activity
    migrate_activity(legacy)
    row={"frame_id":"f","window_start_seconds":-7.5,"window_end_seconds":7.5,
         "sample_count":32,"activity_label":"Dancing","score":0.5,
         "result_json":"{}","sampling_json":"{}","config_json":"{}",
         "config_hash":"c","input_hash":"i"}
    row[field]=value
    with pytest.raises(sqlite3.IntegrityError):
        legacy.execute(f"INSERT INTO Activity ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))
