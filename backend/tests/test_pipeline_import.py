"""Synthetic import files only: nothing here reads or generates data from real footage."""

import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from analysis_db.annotations import list_annotations, list_clips
from analysis_db.contracts import AnnotationChanges, DataError
from analysis_db.labels import set_label_active
from analysis_db.pipeline_import import import_file, list_import_runs, parse_import_file
from analysis_db.review import accept, defer, edit, reject
from analysis_db.storage import initialize_database

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_pipeline_output.py"
SINGING, SPOKEN = 1, 4
REVIEWER = "r-1"


def synthetic() -> dict:
    """Two videos; a three-person clip with clip-level multi-label activity and per-person affect."""
    return {
        "format": "tpa-review-import/1",
        "pipeline": {"name": "synthetic-fixture", "version": "0.1",
                     "generated_at": "2026-10-25T12:00:00Z",
                     "models": [{"name": "fake-model", "revision": "abc123"}]},
        "videos": [
            {"filename": "one.mp4",
             "clips": [
                 {"key": "c1", "start_frame": 0, "end_frame": 239,
                  "participants": ["Person_0001", "Person_0002", "Person_0003"],
                  "priority": {"score": 1.37, "method": "synthetic@1"}},
                 {"key": "c2", "start_frame": 240, "end_frame": 240, "participants": []},
             ],
             "annotations": [
                 {"key": "a-sing", "clip_key": "c1", "confidence": 0.71,
                  "label": {"name": "Singing", "category": "activity"}},
                 {"key": "a-group", "clip_key": "c1", "confidence": 0.4,
                  "label": {"name": "group performance", "category": "activity"}},
                 {"key": "a-pos-1", "clip_key": "c1", "person_id": "Person_0001",
                  "start_frame": 0, "end_frame": 239, "confidence": 0.64,
                  "label": {"name": "Visible Positive Affect", "category": "observation"}},
                 {"key": "a-neu-2", "clip_key": "c1", "person_id": "Person_0002",
                  "start_frame": 10, "end_frame": 200, "confidence": 0.5,
                  "label": {"name": "Visible Neutral Affect", "category": "observation"}},
                 {"key": "a-neg-3", "person_id": "Person_0003", "start_frame": 0,
                  "end_frame": 2397, "confidence": 1.0,
                  "label": {"name": "Visible Negative Affect", "category": "observation"}},
             ]},
            {"filename": "two.mp4",
             "clips": [{"key": "c3", "start_frame": 0, "end_frame": 100,
                        "participants": ["Person_0001"],
                        "priority": {"score": 2.5, "method": "synthetic@1"}}],
             "annotations": [
                 {"key": "a-two", "clip_key": "c3", "confidence": 0.0,
                  "label": {"name": "Dancing", "category": "activity"}},
                 {"key": "a-two-nc", "person_id": "Person_0001", "start_frame": 5,
                  "end_frame": 6, "label": {"name": "Sustained Participation",
                                            "category": "observation"}},
             ]},
        ],
    }


def run(connection, data: dict):
    text = json.dumps(data)
    return import_file(connection, parse_import_file(text), source_name="synthetic.json",
                       sha256=hashlib.sha256(text.encode()).hexdigest())


def by_key(connection) -> dict[str, tuple]:
    return {key: tuple(row) for key, *row in connection.execute(
        "SELECT import_key, clip_id, person_id, label_id, start_frame, end_frame, confidence,"
        " source, review_status, updated_at FROM Annotation")}


def snapshot(connection):
    return [connection.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
            for t in ("ReviewClip", "ReviewClipParticipant", "Annotation", "ReviewEvent")]


def annotation_id(connection, key):
    return connection.execute("SELECT annotation_id FROM Annotation WHERE import_key = ?",
                              (key,)).fetchone()[0]


# --- Happy path ----------------------------------------------------------------------------

def test_import_stores_multi_person_multi_label_output_as_ai_unreviewed(review_db):
    result = run(review_db, synthetic())
    counts = result.counts
    assert (counts.clips_inserted, counts.inserted) == (3, 7)
    rows = by_key(review_db)
    assert {row[6:8] for row in rows.values()} == {("AI", "UNREVIEWED")}
    clip = list_clips(review_db, video_id=1)[0]
    assert clip.person_ids == ("Person_0001", "Person_0002", "Person_0003")
    assert (clip.priority_score, clip.priority_method) == (1.37, "synthetic@1")
    clip_annotations = list_annotations(review_db, clip_id=clip.clip_id)
    assert sorted(a.label_name for a in clip_annotations) == [
        "Group Performance", "Singing", "Visible Neutral Affect", "Visible Positive Affect"]
    # Clip-level annotations take the clip span; confidence 0, 1, and null are all kept.
    assert rows["a-sing"][3:5] == (0, 239) and rows["a-sing"][1] is None
    assert rows["a-two"][5] == 0.0 and rows["a-neg-3"][5] == 1.0 and rows["a-two-nc"][5] is None


def test_confidence_and_priority_stay_separate(review_db):
    run(review_db, synthetic())
    clip = list_clips(review_db, video_id=1)[0]
    singing = next(a for a in list_annotations(review_db, clip_id=clip.clip_id)
                   if a.label_name == "Singing")
    assert singing.confidence == 0.71 and clip.priority_score == 1.37
    assert "priority" not in {f for f in singing.__dataclass_fields__}


def test_rerun_is_idempotent(review_db):
    run(review_db, synthetic())
    before = snapshot(review_db)
    counts = run(review_db, synthetic()).counts
    assert (counts.inserted, counts.updated, counts.unchanged) == (0, 0, 7)
    assert (counts.clips_inserted, counts.clips_updated, counts.clips_unchanged) == (0, 0, 3)
    assert snapshot(review_db) == before


def test_rerun_updates_unreviewed_in_place(review_db):
    run(review_db, synthetic())
    changed = synthetic()
    changed["videos"][0]["annotations"][0]["confidence"] = 0.9
    changed["videos"][0]["clips"][0]["priority"]["score"] = 3.0
    counts = run(review_db, changed).counts
    assert (counts.updated, counts.clips_updated) == (1, 1)
    assert by_key(review_db)["a-sing"][5:8] == (0.9, "AI", "UNREVIEWED")


@pytest.mark.parametrize("act", [
    lambda c, i: accept(c, i, reviewer_id=REVIEWER),
    lambda c, i: reject(c, i, reviewer_id=REVIEWER),
    lambda c, i: defer(c, i, reviewer_id=REVIEWER),
    lambda c, i: edit(c, i, AnnotationChanges(label_id=SPOKEN), reviewer_id=REVIEWER),
], ids=["accepted", "rejected", "deferred", "edited"])
def test_reviewed_annotations_and_their_clips_are_protected(review_db, act):
    run(review_db, synthetic())
    act(review_db, annotation_id(review_db, "a-sing"))
    before = snapshot(review_db)
    changed = synthetic()
    changed["videos"][0]["annotations"][0]["confidence"] = 0.99
    changed["videos"][0]["clips"][0]["end_frame"] = 300
    changed["videos"][0]["clips"][0]["participants"] = ["Person_0001"]
    counts = run(review_db, changed).counts
    assert (counts.skipped_protected, counts.clips_skipped_protected) == (1, 1)
    assert snapshot(review_db) == before


def test_missing_records_are_never_deleted(review_db):
    run(review_db, synthetic())
    smaller = synthetic()
    smaller["videos"] = smaller["videos"][:1]
    smaller["videos"][0]["clips"] = smaller["videos"][0]["clips"][:1]
    smaller["videos"][0]["annotations"] = smaller["videos"][0]["annotations"][:1]
    run(review_db, smaller)
    assert len(by_key(review_db)) == 7 and len(list_clips(review_db)) == 3


def test_rejected_import_stays_hidden_by_default(review_db):
    run(review_db, synthetic())
    reject(review_db, annotation_id(review_db, "a-sing"), reviewer_id=REVIEWER)
    run(review_db, synthetic())
    labels = [a.label_name for a in list_annotations(review_db, video_id=1)]
    assert "Singing" not in labels
    assert "Singing" in [a.label_name for a in list_annotations(review_db, include_rejected=True)]


def test_inactive_label_refused_for_new_rows_but_tolerated_when_protected(review_db):
    run(review_db, synthetic())
    accept(review_db, annotation_id(review_db, "a-sing"), reviewer_id=REVIEWER)
    set_label_active(review_db, SINGING, False)
    assert run(review_db, synthetic()).counts.skipped_protected == 1
    fresh = synthetic()
    fresh["videos"][0]["annotations"].append(
        {"key": "a-new-sing", "start_frame": 1, "end_frame": 2,
         "label": {"name": "Singing", "category": "activity"}})
    with pytest.raises(DataError, match="a-new-sing.*inactive"):
        run(review_db, fresh)


def test_priority_order_puts_unscored_clips_last(review_db):
    run(review_db, synthetic())
    assert [c.priority_score for c in list_clips(review_db, order="priority")] == [2.5, 1.37, None]


def test_import_run_is_recorded_only_on_success(review_db):
    first = run(review_db, synthetic())
    assert (first.pipeline_name, first.pipeline_version, first.source_name) == (
        "synthetic-fixture", "0.1", "synthetic.json")
    assert first.models[0].name == "fake-model" and first.models[0].revision == "abc123"
    assert first.counts.inserted == 7 and len(first.input_sha256) == 64
    bad = synthetic()
    bad["videos"][1]["filename"] = "missing.mp4"
    with pytest.raises(DataError):
        run(review_db, bad)
    assert [r.run_id for r in list_import_runs(review_db)] == [first.run_id]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        review_db.execute("DELETE FROM ImportRun")


# --- All-or-nothing validation ---------------------------------------------------------------

def mutate(path: str, value):
    def apply(data):
        target = data
        *parts, last = path.split(".")
        for part in parts:
            target = target[int(part)] if part.isdigit() else target[part]
        if value is DELETE:
            del target[int(last) if last.isdigit() else last]
        else:
            target[int(last) if last.isdigit() else last] = value
        return data
    return apply


DELETE = object()
INVALID = {
    "unknown video": (mutate("videos.1.filename", "nope.mp4"), "unknown video"),
    "unknown clip participant": (mutate("videos.1.clips.0.participants", ["Person_9999"]), "unknown participants"),
    "unknown annotation participant": (mutate("videos.1.annotations.1.person_id", "Person_9999"), "unknown participant"),
    "unknown label": (mutate("videos.1.annotations.0.label.name", "Juggling"), "unknown activity label"),
    "wrong category": (mutate("videos.1.annotations.0.label.category", "observation"), "unknown observation label"),
    "span beyond video": (mutate("videos.1.annotations.1.end_frame", 99_999), "beyond the video"),
    "reversed span": (mutate("videos.1.clips.0.start_frame", 500), "end_frame must be"),
    "negative frame": (mutate("videos.1.annotations.1.start_frame", -1), "greater than or equal"),
    "confidence > 1": (mutate("videos.1.annotations.0.confidence", 1.01), "less than or equal"),
    "negative priority": (mutate("videos.1.clips.0.priority.score", -0.1), "greater than or equal"),
    "priority without method": (mutate("videos.1.clips.0.priority", {"score": 1}), "method"),
    "duplicate key": (mutate("videos.1.annotations.1.key", "a-sing"), "duplicate annotation keys"),
    "duplicate filename": (mutate("videos.1.filename", "one.mp4"), "only once"),
    "blank key": (mutate("videos.1.clips.0.key", "  "), "key"),
    "bad format": (mutate("format", "tpa-review-import/2"), "format"),
    "unknown field": (mutate("videos.1.clips.0.colour", "red"), "Extra inputs"),
    "nested parameter": (mutate("pipeline.parameters", {"thresholds": {"a": 1}}), "parameters"),
    "repeated participant": (mutate("videos.1.clips.0.participants", ["Person_0001", "Person_0001"]), "repeat"),
    "missing span for person": (mutate("videos.1.annotations.1.start_frame", DELETE), "both start_frame"),
    "clip-level span mismatch": (mutate("videos.1.annotations.0.start_frame", 1), "both start_frame"),
    "unknown clip key": (mutate("videos.1.annotations.0.clip_key", "nope"), "unknown clip_key"),
    "string frame": (mutate("videos.1.clips.0.end_frame", "100"), "integer"),
}


@pytest.mark.parametrize("name", INVALID)
def test_invalid_file_stores_nothing(review_db, name):
    breaker, message = INVALID[name]
    data = breaker(copy.deepcopy(synthetic()))
    before = snapshot(review_db)
    with pytest.raises(DataError, match=message):
        run(review_db, data)
    assert snapshot(review_db) == before and list_import_runs(review_db) == []


def test_flat_parameters_are_accepted_and_optional(review_db):
    data = synthetic()
    data["pipeline"]["parameters"] = {"gap_seconds": 2.0, "device": "cpu", "activity": True,
                                      "note": None}
    assert run(review_db, data).counts.inserted == 7
    assert "parameters" not in synthetic()["pipeline"]  # older files stay valid


def test_clip_level_span_must_match_clip(review_db):
    data = synthetic()
    data["videos"][1]["annotations"][0].update(start_frame=1, end_frame=2)
    with pytest.raises(DataError, match="a-two.*clip-level annotation span"):
        run(review_db, data)


def test_whole_video_and_single_frame_spans(review_db):
    data = synthetic()
    data["videos"][0]["clips"].append({"key": "whole", "start_frame": 0, "end_frame": 2397})
    run(review_db, data)
    spans = {(c.start_frame, c.end_frame) for c in list_clips(review_db, video_id=1)}
    assert {(0, 2397), (240, 240)} <= spans


# --- Scale (SC-001) ----------------------------------------------------------------------------

def test_large_synthetic_import_is_fast_and_idempotent(review_db):
    review_db.execute("INSERT INTO Video (video_id, title, filename, file_path, duration_seconds,"
                      " fps) VALUES (3, 'three', 'three.mp4', 'data/videos/three.mp4', 600, 24)")
    videos = []
    for filename, frames in (("one.mp4", 2398), ("two.mp4", 1200), ("three.mp4", 14400)):
        clips, annotations = [], []
        for i in range(80):
            start = i * (frames // 80)
            end = start + frames // 80 - 1
            key = f"{filename}:c{i}"
            members = [f"Person_000{1 + (i + k) % 3}" for k in range(1 + i % 3)]
            clips.append({"key": key, "start_frame": start, "end_frame": end, "participants": members,
                          "priority": {"score": i / 10, "method": "synthetic@1"}})
            annotations.append({"key": f"{key}:act", "clip_key": key, "confidence": 0.5,
                                "label": {"name": "Singing", "category": "activity"}})
            for person in members:
                for label in ("Visible Positive Affect", "Sustained Participation"):
                    annotations.append({"key": f"{key}:{person}:{label}", "clip_key": key,
                                        "person_id": person, "start_frame": start, "end_frame": end,
                                        "confidence": 0.6,
                                        "label": {"name": label, "category": "observation"}})
        videos.append({"filename": filename, "clips": clips, "annotations": annotations})
    data = {"format": "tpa-review-import/1", "pipeline": {"name": "synthetic-load", "version": "1"},
            "videos": videos}
    started = time.perf_counter()
    counts = run(review_db, data).counts
    elapsed = time.perf_counter() - started
    assert counts.clips_inserted == 240 and counts.inserted >= 1000
    assert elapsed < 5, elapsed
    again = run(review_db, data).counts
    assert (again.inserted, again.updated) == (0, 0)
    started = time.perf_counter()
    list_clips(review_db, order="priority")
    list_clips(review_db, person_id="Person_0001")
    assert time.perf_counter() - started < 1


# --- CLI -----------------------------------------------------------------------------------------

def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def seeded_db(tmp_path) -> Path:
    db = tmp_path / "cli.sqlite"
    initialize_database(db)
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO Video (video_id, title, filename, file_path,"
                           " duration_seconds, fps) VALUES (1, 'one', 'one.mp4', 'x/one.mp4', 100, 23.976)")
        connection.execute("INSERT INTO Video (video_id, title, filename, file_path,"
                           " duration_seconds, fps) VALUES (2, 'two', 'two.mp4', 'x/two.mp4', 50, 24)")
        connection.executemany("INSERT INTO Person VALUES (?)",
                               [("Person_0001",), ("Person_0002",), ("Person_0003",)])
    return db


def test_cli_imports_and_reports_counts(tmp_path):
    db = seeded_db(tmp_path)
    source = tmp_path / "out.json"
    source.write_text(json.dumps(synthetic()))
    first = cli("--input", str(source), "--db", str(db))
    assert first.returncode == 0, first.stderr
    assert "inserted: 7" in first.stdout and "clips_inserted: 3" in first.stdout
    second = cli("--input", str(source), "--db", str(db))
    assert "inserted: 0" in second.stdout and "unchanged: 7" in second.stdout


def test_cli_failure_stores_nothing_and_has_no_traceback(tmp_path):
    db = seeded_db(tmp_path)
    source = tmp_path / "bad.json"
    bad = synthetic()
    bad["videos"][1]["annotations"][0]["label"]["name"] = "Juggling"
    source.write_text(json.dumps(bad))
    result = cli("--input", str(source), "--db", str(db))
    assert result.returncode == 1 and "Juggling" in result.stderr
    assert "Traceback" not in result.stderr
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Annotation").fetchone() == (0,)
    source.write_text("{not json")
    assert cli("--input", str(source), "--db", str(db)).returncode == 1
    assert cli("--input", str(tmp_path / "missing.json"), "--db", str(db)).returncode == 1
