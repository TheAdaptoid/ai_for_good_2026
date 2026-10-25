from datetime import datetime, timedelta
import sqlite3

import pytest

from analysis_db.contracts import DataError
from analysis_db.storage import connect_database, initialize_database


@pytest.fixture
def records(tmp_path):
    path = tmp_path / "analysis.sqlite"
    initialize_database(path)
    c = connect_database(path)
    c.executescript("""
        INSERT INTO Video(video_id,title,filename,file_path,duration_seconds)
        VALUES(1,'v','v.mp4','v.mp4',30);
        INSERT INTO Frame VALUES('f',1,0,0);
        INSERT INTO Person VALUES('A');
        INSERT INTO FaceDetection VALUES(1,'A','f',0,0,10,10,0.9);
        INSERT INTO Engagement VALUES(1,1,0.2,0.3,0.5);
        INSERT INTO Activity(activity_id,frame_id,window_start_seconds,window_end_seconds,
            sample_count,activity_label,score,result_json,sampling_json,config_json,
            config_hash,input_hash)
        VALUES(1,'f',-7.5,7.5,32,'discussion',0.7,'{}','{}','{}','c','i');
    """)
    yield c
    c.close()


def test_activity_corrections_preserve_history_and_skip_noops(records):
    from analysis_db.corrections import correct_activity
    c = records
    assert correct_activity(c, 1, "writing", changed_by="reviewer")
    assert not correct_activity(c, 1, "writing")
    assert correct_activity(c, 1, "reading")
    assert c.execute("SELECT activity_label FROM Activity").fetchall() == [("reading",)]
    assert c.execute("SELECT old_label,new_label,changed_by FROM ActivityAudit ORDER BY audit_id").fetchall() == [
        ("discussion", "writing", "reviewer"), ("writing", "reading", None)]
    for (timestamp,) in c.execute("SELECT changed_at FROM ActivityAudit"):
        assert datetime.fromisoformat(timestamp).utcoffset() == timedelta(0)
    assert not c.in_transaction


def test_engagement_corrections_preserve_all_scores(records):
    from analysis_db.corrections import correct_engagement
    c = records
    assert correct_engagement(c, 1, 0.6, 0.3, 0.1)
    assert not correct_engagement(c, 1, 0.6, 0.3, 0.1)
    assert correct_engagement(c, 1, 0.7, 0.2, 0.1)
    assert c.execute("SELECT positive_score,neutral_score,negative_score FROM Engagement").fetchone() == (0.7, 0.2, 0.1)
    assert c.execute("SELECT old_positive_score,new_positive_score,old_neutral_score,"
                     "new_neutral_score,old_negative_score,new_negative_score FROM EngagementAudit ORDER BY audit_id").fetchall() == [
        (0.2, 0.6, 0.3, 0.3, 0.5, 0.1), (0.6, 0.7, 0.3, 0.2, 0.1, 0.1)]


@pytest.mark.parametrize("kind", ["activity", "engagement"])
def test_failed_audit_insertion_rolls_back_correction(records, kind):
    from analysis_db.corrections import correct_activity, correct_engagement
    c = records
    table = "ActivityAudit" if kind == "activity" else "EngagementAudit"
    c.execute(f"CREATE TRIGGER fail BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        if kind == "activity":
            correct_activity(c, 1, "writing")
        else:
            correct_engagement(c, 1, 0.8, 0.1, 0.1)
    assert c.execute("SELECT activity_label FROM Activity").fetchone() == ("discussion",)
    assert c.execute("SELECT positive_score FROM Engagement").fetchone() == (0.2,)
    assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
    assert not c.in_transaction


@pytest.mark.parametrize("kind", ["activity", "engagement"])
@pytest.mark.parametrize("operation", ["update", "delete", "replace"])
def test_audits_are_append_only(records, kind, operation):
    from analysis_db.corrections import correct_activity, correct_engagement
    c = records
    if kind == "activity":
        correct_activity(c, 1, "writing")
        table = "ActivityAudit"
    else:
        correct_engagement(c, 1, 0.6, 0.3, 0.1)
        table = "EngagementAudit"
    before = c.execute(f"SELECT * FROM {table}").fetchall()
    statements = {"update": f"UPDATE {table} SET changed_by='other'",
                  "delete": f"DELETE FROM {table}",
                  "replace": f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"}
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(statements[operation])
    assert c.execute(f"SELECT * FROM {table}").fetchall() == before


def test_predictions_do_not_create_audits(records):
    records.execute("UPDATE Activity SET activity_label='automated'")
    records.execute("UPDATE Engagement SET positive_score=0.9")
    assert records.execute("SELECT COUNT(*) FROM ActivityAudit").fetchone() == (0,)
    assert records.execute("SELECT COUNT(*) FROM EngagementAudit").fetchone() == (0,)


@pytest.mark.parametrize("label", [None, "", "  ", 123])
def test_invalid_labels_leave_records_unchanged(records, label):
    from analysis_db.corrections import correct_activity
    with pytest.raises(ValueError):
        correct_activity(records, 1, label)
    assert records.execute("SELECT activity_label FROM Activity").fetchone() == ("discussion",)


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf"), None, True, "0.5"])
def test_invalid_scores_leave_records_unchanged(records, score):
    from analysis_db.corrections import correct_engagement
    with pytest.raises(ValueError):
        correct_engagement(records, 1, score, 0.3, 0.5)
    assert records.execute("SELECT positive_score FROM Engagement").fetchone() == (0.2,)


def test_missing_records_and_active_transaction(records):
    from analysis_db.corrections import correct_activity, correct_engagement
    with pytest.raises(LookupError):
        correct_activity(records, 99, "writing")
    with pytest.raises(LookupError):
        correct_engagement(records, 99, 0.2, 0.3, 0.5)
    records.execute("BEGIN")
    with pytest.raises(DataError, match="idle"):
        correct_activity(records, 1, "writing")
    assert records.in_transaction
    records.rollback()


def test_additive_initialization_preserves_existing_data(tmp_path):
    from analysis_db.paths import SCHEMA_PATH
    path = tmp_path / "old.sqlite"
    c = connect_database(path)
    c.executescript(SCHEMA_PATH.read_text())
    c.execute("INSERT INTO Person VALUES('existing')")
    c.close()
    initialize_database(path)
    initialize_database(path)
    c = connect_database(path)
    try:
        assert c.execute("SELECT * FROM Person").fetchall() == [("existing",)]
        for table in ("ActivityAudit", "EngagementAudit", "Clip", "ClipPerson", "ClipGeneration"):
            assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        c.close()


def test_initialization_preserves_existing_audits(records):
    from analysis_db.corrections import correct_activity, correct_engagement
    correct_activity(records, 1, "writing")
    correct_engagement(records, 1, 0.6, 0.3, 0.1)
    path = records.execute("PRAGMA database_list").fetchone()[2]
    before = {table: records.execute(f"SELECT * FROM {table}").fetchall()
              for table in ("Activity", "Engagement", "ActivityAudit", "EngagementAudit")}
    initialize_database(path)
    assert {table: records.execute(f"SELECT * FROM {table}").fetchall() for table in before} == before


def test_failed_extension_installation_is_transactional(tmp_path):
    from analysis_db.paths import SCHEMA_PATH
    path = tmp_path / "incompatible.sqlite"
    c = connect_database(path)
    try:
        c.executescript(SCHEMA_PATH.read_text())
        c.execute("INSERT INTO Person VALUES('existing')")
        # An incompatible preexisting extension makes index creation fail.
        c.execute("CREATE TABLE ActivityAudit(unrecognized TEXT)")
        with pytest.raises(sqlite3.OperationalError):
            initialize_database(path)
        tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "Clip" not in tables
        assert "EngagementAudit" not in tables
        assert c.execute("SELECT * FROM Person").fetchall() == [("existing",)]
    finally:
        c.close()
