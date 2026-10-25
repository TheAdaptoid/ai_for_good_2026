import csv
import sqlite3
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND.parent
INIT_SCRIPT = BACKEND / "scripts" / "init_db.py"
INGEST_SCRIPT = BACKEND / "scripts" / "ingest.py"

HEADER = ["video_title", "video_filename", "frame_number", "frame_id", "person_id",
          "source_time_seconds", "face_bbox_x1", "face_bbox_y1", "face_bbox_x2",
          "face_bbox_y2", "det_score"]
EXPECTED_TABLES = ("Video", "Frame", "Person", "FaceDetection", "Activity", "Engagement")


def write_csv(path, rows, delimiter=","):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(HEADER)
        writer.writerows(rows)


def repo_data_root(prefix="analysis_db_cli_"):
    return TemporaryDirectory(prefix=prefix, dir=REPOSITORY_ROOT)


def test_init_cli_from_unrelated_cwd(tmp_path):
    db = tmp_path / "nested" / "test.sqlite"
    command = [sys.executable, str(INIT_SCRIPT), "--db", str(db)]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert db.is_file()
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert "Video" in second.stdout and "Engagement" in second.stdout


def test_ingest_cli_requires_input(tmp_path):
    result = subprocess.run(
        [sys.executable, str(INGEST_SCRIPT), "--db", str(tmp_path / "x.sqlite")],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "--input" in result.stderr
    assert "Traceback" not in result.stderr


def test_ingest_cli_missing_database_is_not_created(tmp_path):
    with repo_data_root() as root:
        videos = Path(root) / "videos"
        videos.mkdir()
        source = tmp_path / "header.csv"
        write_csv(source, [])
        db = tmp_path / "missing.sqlite"
        result = subprocess.run(
            [sys.executable, str(INGEST_SCRIPT), "--input", str(source),
             "--db", str(db), "--video-dir", str(videos)],
            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert not db.exists()
    assert result.stderr.startswith("error: ")
    assert "Traceback" not in result.stderr


def test_ingest_cli_uninitialized_database_reports_missing_tables(tmp_path):
    with repo_data_root() as root:
        videos = Path(root) / "videos"
        videos.mkdir()
        source = tmp_path / "header.csv"
        write_csv(source, [])
        db = tmp_path / "empty.sqlite"
        db.write_text("")
        result = subprocess.run(
            [sys.executable, str(INGEST_SCRIPT), "--input", str(source),
             "--db", str(db), "--video-dir", str(videos)],
            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert "missing tables" in result.stderr
    assert "Traceback" not in result.stderr
    with sqlite3.connect(db) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert tables == []



def test_init_cli_reports_review_table_counts(tmp_path):
    db = tmp_path / "review.sqlite"
    result = subprocess.run([sys.executable, str(INIT_SCRIPT), "--db", str(db)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()[1:]
    assert lines == [f"  {table}: 0" for table in EXPECTED_TABLES] + [
        "  Label: 18", "  ReviewClip: 0", "  ReviewClipParticipant: 0",
        "  Annotation: 0", "  ReviewEvent: 0", "  StaffAccount: 0", "  StaffSession: 0"]

def test_ingest_cli_rejected_file_reports_error_and_continues(tmp_path):
    with repo_data_root() as root:
        videos = Path(root) / "videos"
        videos.mkdir()
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "notes.txt").write_text("not a data file", encoding="utf-8")
        write_csv(input_dir / "bad.csv",
                  [["Clip", "clip.mp4", 0, "frame-0", "person-1", 0.0,
                    1.0, 1.0, 2.0, 2.0, 2.0]])
        write_csv(input_dir / "fine.csv", [])
        db = tmp_path / "out.sqlite"
        init = subprocess.run([sys.executable, str(INIT_SCRIPT), "--db", str(db)],
                              cwd=tmp_path, capture_output=True, text=True)
        assert init.returncode == 0, init.stderr
        result = subprocess.run(
            [sys.executable, str(INGEST_SCRIPT), "--input", str(input_dir),
             "--db", str(db), "--video-dir", str(videos)],
            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "bad.csv" in result.stderr and ":2:" in result.stderr
    assert "det_score" in result.stderr
    assert "notes.txt" in result.stdout
    stdout = result.stdout
    assert stdout.index("bad.csv: rolled back") < stdout.index("fine.csv: committed")
    assert "rows=0 inserted=0 skipped=0 rejected=0" in stdout
    counts_section = stdout.split("Table counts:\n", 1)[1].splitlines()
    assert counts_section == [f"  {table}: 0" for table in EXPECTED_TABLES]


def test_ingest_cli_exit_zero_for_all_successful_files(tmp_path):
    with repo_data_root() as root:
        videos = Path(root) / "videos"
        videos.mkdir()
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        write_csv(input_dir / "b.csv", [])
        write_csv(input_dir / "a.csv", [])
        write_csv(input_dir / "c.tsv", [], delimiter="\t")
        db = tmp_path / "out.sqlite"
        init = subprocess.run([sys.executable, str(INIT_SCRIPT), "--db", str(db)],
                              cwd=tmp_path, capture_output=True, text=True)
        assert init.returncode == 0, init.stderr
        first = subprocess.run(
            [sys.executable, str(INGEST_SCRIPT), "--input", str(input_dir),
             "--db", str(db), "--video-dir", str(videos)],
            cwd=tmp_path, capture_output=True, text=True)
        assert first.returncode == 0, first.stderr
        assert first.stdout.index("a.csv") < first.stdout.index("b.csv") \
            < first.stdout.index("c.tsv")
        repeat = subprocess.run(
            [sys.executable, str(INGEST_SCRIPT), "--input", str(input_dir),
             "--db", str(db), "--video-dir", str(videos)],
            cwd=tmp_path, capture_output=True, text=True)
    assert repeat.returncode == 0, repeat.stderr
    counts_section = first.stdout.split("Table counts:\n", 1)[1].splitlines()
    assert counts_section == [f"  {table}: 0" for table in EXPECTED_TABLES]
