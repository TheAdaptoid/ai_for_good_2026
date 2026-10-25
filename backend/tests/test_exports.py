import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from analysis_db.exports import ANNOTATION_COLUMNS, export_annotations, export_history

EXPORT_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_annotations.py"
EXPECTED_ANNOTATION_COLUMNS = [
    "annotation_id", "video_id", "clip_id", "person_id", "label_id", "label_name",
    "label_category", "start_frame", "end_frame", "start_seconds", "end_seconds", "confidence",
    "source", "review_status", "updated_at",
]


def test_annotation_columns_match_contract():
    assert list(ANNOTATION_COLUMNS) == EXPECTED_ANNOTATION_COLUMNS


def test_csv_export(review_db, insert_ai_annotation):
    first = insert_ai_annotation(review_db, start_frame=1000, end_frame=1100)
    group = insert_ai_annotation(review_db, person_id=None, confidence=None, label_id=7)
    out = io.StringIO()
    export_annotations(review_db, out, "csv")
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert list(rows[0]) == EXPECTED_ANNOTATION_COLUMNS
    assert [int(row["annotation_id"]) for row in rows] == [group, first]
    assert rows[0]["person_id"] == "" and rows[0]["confidence"] == ""
    assert rows[1]["start_seconds"] == "41.708"  # 1000 / 23.976, 3 decimals
    assert rows[1]["label_name"] == "Singing" and rows[1]["source"] == "AI"


def test_json_export(review_db, insert_ai_annotation):
    insert_ai_annotation(review_db, person_id=None, confidence=None)
    out = io.StringIO()
    export_annotations(review_db, out, "json")
    [record] = json.loads(out.getvalue())
    assert list(record) == EXPECTED_ANNOTATION_COLUMNS
    assert record["person_id"] is None and record["confidence"] is None
    assert record["start_seconds"] == round(100 / 23.976, 3)


def test_rejected_excluded_unless_requested(review_db, insert_ai_annotation):
    kept = insert_ai_annotation(review_db)
    rejected = insert_ai_annotation(review_db, review_status="REJECTED")
    default, everything = io.StringIO(), io.StringIO()
    export_annotations(review_db, default, "json")
    export_annotations(review_db, everything, "json", include_rejected=True)
    assert [r["annotation_id"] for r in json.loads(default.getvalue())] == [kept]
    assert [r["annotation_id"] for r in json.loads(everything.getvalue())] == [kept, rejected]


def test_unknown_format_rejected(review_db):
    with pytest.raises(ValueError):
        export_annotations(review_db, io.StringIO(), "xml")


def run_export(*args):
    return subprocess.run([sys.executable, str(EXPORT_SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_export_cli_writes_file(review_db, insert_ai_annotation, tmp_path):
    insert_ai_annotation(review_db)
    db = review_db.execute("PRAGMA database_list").fetchone()[2]
    output = tmp_path / "out.csv"
    result = run_export("--db", db, "--format", "csv", "--output", output)
    assert result.returncode == 0, result.stderr
    assert len(list(csv.DictReader(output.open(encoding="utf-8")))) == 1


def test_export_cli_missing_db(tmp_path):
    result = run_export("--db", tmp_path / "absent.sqlite", "--format", "json",
                        "--output", tmp_path / "out.json")
    assert result.returncode == 1
    assert "error:" in result.stderr and "Traceback" not in result.stderr


EXPECTED_HISTORY_COLUMNS = [
    "event_id", "annotation_id", "video_id", "action", "prev_label_id", "new_label_id",
    "prev_start_frame", "prev_end_frame", "new_start_frame", "new_end_frame", "prev_person_id",
    "new_person_id", "prev_confidence", "new_confidence", "prev_source", "new_source",
    "prev_status", "new_status", "reviewer_id", "note", "created_at",
]


def reviewed(review_db, insert_ai_annotation):
    from analysis_db.contracts import AnnotationChanges
    from analysis_db.review import accept, edit
    annotation_id = insert_ai_annotation(review_db)
    edit(review_db, annotation_id, AnnotationChanges(label_id=4), reviewer_id="r-1", note="fix")
    accept(review_db, annotation_id, reviewer_id="r-2")
    return annotation_id


def test_history_csv(review_db, insert_ai_annotation):
    reviewed(review_db, insert_ai_annotation)
    out = io.StringIO()
    export_history(review_db, out, "csv")
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert list(rows[0]) == EXPECTED_HISTORY_COLUMNS
    assert [row["action"] for row in rows] == ["EDITED", "ACCEPTED"]
    assert rows[0]["prev_confidence"] == "0.6" and rows[0]["new_confidence"] == ""
    assert int(rows[0]["event_id"]) < int(rows[1]["event_id"])


def test_history_json(review_db, insert_ai_annotation):
    reviewed(review_db, insert_ai_annotation)
    out = io.StringIO()
    export_history(review_db, out, "json")
    records = json.loads(out.getvalue())
    assert list(records[0]) == EXPECTED_HISTORY_COLUMNS
    assert [r["reviewer_id"] for r in records] == ["r-1", "r-2"]
    assert records[0]["note"] == "fix" and records[1]["note"] is None


def test_export_cli_history(review_db, insert_ai_annotation, tmp_path):
    reviewed(review_db, insert_ai_annotation)
    db = review_db.execute("PRAGMA database_list").fetchone()[2]
    output = tmp_path / "history.json"
    result = run_export("--db", db, "--format", "json", "--history", "--output", output)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 2


# --- Convergence: safe export writes (T056) -----------------------------------------------

def six_table_db(tmp_path):
    from conftest import pre_review_schema_sql
    from analysis_db.storage import connect_database
    path = tmp_path / "six.sqlite"
    connection = connect_database(path)
    connection.executescript(pre_review_schema_sql())
    connection.close()
    return path


@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_failed_export_leaves_no_new_file(tmp_path, fmt):
    output = tmp_path / "out" / f"export.{fmt}"
    output.parent.mkdir()
    result = run_export("--db", six_table_db(tmp_path), "--format", fmt, "--output", output)
    assert result.returncode == 1
    assert "error:" in result.stderr and "Traceback" not in result.stderr
    assert list(output.parent.iterdir()) == []


@pytest.mark.parametrize("extra", [[], ["--history"]])
def test_failed_export_keeps_existing_destination(tmp_path, extra):
    output = tmp_path / "out" / "export.json"
    output.parent.mkdir()
    output.write_text("previous export", encoding="utf-8")
    result = run_export("--db", six_table_db(tmp_path), "--format", "json", *extra,
                        "--output", output)
    assert result.returncode == 1
    assert output.read_text(encoding="utf-8") == "previous export"
    assert list(output.parent.iterdir()) == [output]


def test_successful_export_replaces_destination(review_db, insert_ai_annotation, tmp_path):
    insert_ai_annotation(review_db)
    db = review_db.execute("PRAGMA database_list").fetchone()[2]
    output = tmp_path / "out" / "export.json"
    output.parent.mkdir()
    output.write_text("previous export", encoding="utf-8")
    result = run_export("--db", db, "--format", "json", "--output", output)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 1
    assert list(output.parent.iterdir()) == [output]
