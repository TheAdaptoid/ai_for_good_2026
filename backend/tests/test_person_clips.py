from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from analysis_db.contracts import DataError


def stored_clips(c):
    return [(start, end, tuple(p for (p,) in c.execute(
        "SELECT person_id FROM ClipPerson WHERE clip_id=? ORDER BY person_id", (clip_id,))))
        for clip_id, start, end in c.execute(
            "SELECT clip_id,start_time_seconds,end_time_seconds FROM Clip ORDER BY start_time_seconds")]


@pytest.mark.parametrize("people,expected", [
    ([{"A"}] * 10, [(0, 10, ("A",))]),
    ([{"A"}] * 5 + [{"A", "B"}] * 5, [(0, 5, ("A",)), (5, 10, ("A", "B"))]),
    ([{"A", "B"}] * 5 + [{"A"}] * 5, [(0, 5, ("A", "B")), (5, 10, ("A",))]),
    ([{"A"}] * 5 + [set()] * 4 + [{"A"}] * 5, [(0, 14, ("A",))]),
    ([{"A"}] * 5 + [{"B"}] * 5, [(0, 5, ("A",)), (5, 10, ("B",))]),
    ([set()] * 10, []),
    ([], []),
    ([{"A"}] * 4, []),
    ([set()] * 2 + [{"A"}] * 5, [(2, 7, ("A",))]),
    ([{"A"}] * 5 + [set()] * 5 + [{"A"}] * 5,
     [(0, 5, ("A",)), (10, 15, ("A",))]),
    ([{"A"}] * 5 + [{"A", "B"}] * 4, [(0, 9, ("A",))]),
    ([{"A"}] * 5 + [set()] * 4, [(0, 9, ("A",))]),
    # B's arrival starts before A's departure and confirms before it.
    ([{"A"}] * 5 + [{"A", "B"}] * 2 + [{"B"}] * 5,
     [(0, 5, ("A",)), (5, 7, ("A", "B")), (7, 12, ("B",))]),
    # Aborted arrival counters must reset, independently of A's presence.
    ([{"A"}] * 5 + [{"A", "B"}] * 4 + [{"A"}] + [{"A", "B"}] * 5,
     [(0, 10, ("A",)), (10, 15, ("A", "B"))]),
])
def test_person_transitions(person_timeline, people, expected):
    from analysis_db.clips import generate_clips
    c = person_timeline(people)
    generate_clips(c, 1)
    assert stored_clips(c) == expected
    assert c.execute("SELECT COUNT(*) FROM ClipGeneration").fetchone() == (1,)
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_threshold_counts_analyzed_frames_and_uses_actual_timestamps(person_timeline):
    from analysis_db.clips import generate_clips
    c = person_timeline([{"A"}] * 3 + [{"A", "B"}] * 3,
                        times=[0.5, 2, 5, 8.5, 9, 12], duration=20)
    generate_clips(c, 1, persistence_frames=3)
    assert stored_clips(c) == [(0.5, 8.5, ("A",)), (8.5, 20, ("A", "B"))]


def test_repeated_population_keeps_ids_threshold_and_empty_result(person_timeline):
    from analysis_db.clips import generate_clips, populate_clips
    c = person_timeline([{"A"}] * 5)
    first = generate_clips(c, 1)
    assert populate_clips(c, persistence_frames=1) == {1: first}
    assert c.execute("SELECT persistence_frames FROM ClipGeneration").fetchone() == (5,)
    empty = person_timeline([{"A"}] * 4)
    assert generate_clips(empty, 1) == ()
    assert generate_clips(empty, 1, persistence_frames=1) == ()


@pytest.mark.parametrize("threshold", [0, -1, 1.5, True, "5"])
def test_invalid_threshold(person_timeline, threshold):
    from analysis_db.clips import generate_clips
    c = person_timeline([{"A"}] * 5)
    with pytest.raises(ValueError):
        generate_clips(c, 1, persistence_frames=threshold)
    assert c.execute("SELECT COUNT(*) FROM ClipGeneration").fetchone() == (0,)


@pytest.mark.parametrize("duration", [None, 0, -1, float("inf")])
def test_missing_or_invalid_duration_fails_without_finalizing(person_timeline, duration):
    from analysis_db.clips import generate_clips
    c = person_timeline([{"A"}] * 5)
    c.execute("UPDATE Video SET duration_seconds=?", (duration,))
    with pytest.raises(DataError, match="duration"):
        generate_clips(c, 1)
    assert c.execute("SELECT COUNT(*) FROM ClipGeneration").fetchone() == (0,)


@pytest.mark.parametrize("times", [[0, 1, 1, 3, 4], [0, 2, 1, 3, 4], [0, 1, 2, 3, 5]])
def test_invalid_timestamp_order_and_out_of_range(person_timeline, times):
    from analysis_db.clips import generate_clips
    c = person_timeline([{"A"}] * 5, times=times)
    with pytest.raises(DataError, match="timestamp"):
        generate_clips(c, 1)
    assert stored_clips(c) == []


def test_population_failure_is_atomic(person_timeline):
    from analysis_db.clips import generate_clips
    c = person_timeline([{"A", "B"}] * 5)
    c.execute("CREATE TRIGGER fail BEFORE INSERT ON ClipPerson WHEN NEW.person_id='B'"
              " BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        generate_clips(c, 1)
    for table in ("Clip", "ClipPerson", "ClipGeneration"):
        assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)


@pytest.mark.parametrize("sql", [
    "UPDATE Clip SET start_time_seconds=1",
    "UPDATE Clip SET video_id=2",
    "DELETE FROM Clip",
    "INSERT OR REPLACE INTO Clip SELECT * FROM Clip",
    "DELETE FROM ClipPerson",
    "UPDATE ClipPerson SET person_id='B'",
    "INSERT OR REPLACE INTO ClipPerson SELECT * FROM ClipPerson",
    "INSERT INTO ClipPerson SELECT clip_id,'B' FROM Clip",
    "DELETE FROM ClipGeneration",
    "UPDATE ClipGeneration SET persistence_frames=1",
    "INSERT OR REPLACE INTO ClipGeneration SELECT * FROM ClipGeneration",
    "INSERT INTO Clip(video_id,start_time_seconds,end_time_seconds,created_at) VALUES(1,5,6,'now')",
    "UPDATE Video SET duration_seconds=1 WHERE video_id=1",
])
def test_finalized_clip_data_is_immutable(person_timeline, sql):
    from analysis_db.clips import generate_clips
    c = person_timeline([{"A"}] * 5, duration=10)
    c.execute("INSERT INTO Person VALUES('B')")
    generate_clips(c, 1)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(sql)
    assert stored_clips(c) == [(0, 10, ("A",))]


@pytest.mark.parametrize("start,end", [(-1, 2), (0, 0), (2, 1), (0, 11), (0, float("inf"))])
def test_sql_rejects_invalid_boundaries(person_timeline, start, end):
    c = person_timeline([], duration=10)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO Clip(video_id,start_time_seconds,end_time_seconds,created_at) VALUES(1,?,?, 'now')",
                  (start, end))


def test_sql_rejects_overlaps_but_allows_adjacent_clips(person_timeline):
    c = person_timeline([], duration=10)
    c.execute("INSERT INTO Clip VALUES(1,1,0,5,'now')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO Clip VALUES(2,1,4,7,'now')")
    c.execute("INSERT INTO Clip VALUES(2,1,5,10,'now')")


def test_missing_video_and_active_transaction(person_timeline):
    from analysis_db.clips import generate_clips
    c = person_timeline([])
    with pytest.raises(LookupError):
        generate_clips(c, 99)
    c.execute("BEGIN")
    with pytest.raises(DataError, match="idle"):
        generate_clips(c, 1)
    assert c.in_transaction
    c.rollback()


def test_population_cli(person_timeline):
    c = person_timeline([{"A"}] * 5)
    db = c.execute("PRAGMA database_list").fetchone()[2]
    script = Path(__file__).resolve().parents[1] / "scripts" / "populate_clips.py"
    command = [sys.executable, str(script), "--db", db, "--persistence-frames", "5"]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert stored_clips(c) == [(0, 5, ("A",))]
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert len(stored_clips(c)) == 1
    missing = subprocess.run(command + ["--video-id", "99"], capture_output=True, text=True)
    assert missing.returncode == 1
    assert "99" in missing.stderr


@pytest.mark.parametrize("threshold", [1, 5])
@pytest.mark.parametrize("operation", ["insert", "update"])
def test_video_replacement_cannot_delete_finalized_timeline(person_timeline, threshold, operation):
    from analysis_db.clips import generate_clips
    c = person_timeline([{"A"}] * 3, duration=10)
    generate_clips(c, 1, persistence_frames=threshold)
    c.execute("INSERT INTO Video(video_id,title,filename,file_path,duration_seconds)"
              " VALUES(2,'other','other.mp4','other.mp4',10)")
    tables = ("Video", "Frame", "FaceDetection", "Clip", "ClipPerson", "ClipGeneration")
    before = {table: c.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
    with pytest.raises(sqlite3.IntegrityError):
        if operation == "insert":
            c.execute("INSERT OR REPLACE INTO Video(video_id,title,filename,file_path,duration_seconds)"
                      " VALUES(1,'replacement','timeline.mp4','timeline.mp4',1)")
        else:
            c.execute("UPDATE OR REPLACE Video SET video_id=1,filename='timeline.mp4',"
                      "file_path='timeline.mp4',duration_seconds=1 WHERE video_id=2")
    assert {table: c.execute(f"SELECT * FROM {table}").fetchall() for table in tables} == before
