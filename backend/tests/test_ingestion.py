import csv
import sqlite3
from unittest.mock import Mock

import pytest

from analysis_db.contracts import TABLES, DataError, VideoMetadata
from analysis_db.csv_input import discover_inputs
from analysis_db.ingestion import ingest_files
from analysis_db.storage import connect_database, initialize_database, table_counts


def write_rows(path, rows):
    headers = ["video_title", "video_filename", "frame_number", "frame_id", "person_id",
               "source_time_seconds", "face_bbox_x1", "face_bbox_y1", "face_bbox_x2",
               "face_bbox_y2", "det_score"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "video_title": row.video_title, "video_filename": row.video_filename,
                "frame_number": row.frame_number, "frame_id": row.frame_id,
                "person_id": row.person_id, "source_time_seconds": row.source_time_seconds,
                "face_bbox_x1": row.x1, "face_bbox_y1": row.y1,
                "face_bbox_x2": row.x2, "face_bbox_y2": row.y2, "det_score": row.det_score,
            })


def connect_tmp_db(tmp_path):
    db = tmp_path / "analysis.sqlite"
    initialize_database(db)
    return connect_database(db, must_exist=True)


def test_import_then_reimport_and_late_conflict(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "data" / "videos"
    videos.mkdir(parents=True)
    (videos / "clip.mp4").touch()
    good, bad = tmp_path / "good.csv", tmp_path / "bad.csv"
    write_rows(good, [make_row(), make_row(frame_number=1, frame_id="frame-1", source_time_seconds=0.04)])
    write_rows(bad, [make_row(person_id="new-person"), make_row(x2=999.0)])
    probe = Mock(return_value=VideoMetadata(duration_seconds=1.0, fps=24.0, width=64, height=64))
    monkeypatch.setattr("analysis_db.ingestion.probe_video", probe)
    db = tmp_path / "analysis.sqlite"
    initialize_database(db)
    con = connect_database(db, must_exist=True)
    try:
        first, repeat, rejected = ingest_files(con, [good, good, bad], videos, repository_root=tmp_path)
        assert first.committed and first.inserted["FaceDetection"] == 2
        assert repeat.committed and repeat.inserted["FaceDetection"] == 0
        assert repeat.skipped["FaceDetection"] == 2
        assert not rejected.committed and rejected.error.line_number == 3
        assert rejected.inserted == dict.fromkeys(TABLES, 0)
        assert rejected.rejected_rows == 2
        assert table_counts(con) == {"Video": 1, "Frame": 2, "Person": 1,
                                     "FaceDetection": 2, "Activity": 0, "Engagement": 0}
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert probe.call_count == 1
    finally:
        con.close()


def test_identical_duplicate_row_is_skipped(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "data" / "videos"
    videos.mkdir(parents=True)
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(), make_row()])
    probe = Mock(return_value=VideoMetadata(fps=24.0))
    monkeypatch.setattr("analysis_db.ingestion.probe_video", probe)
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert result.committed
        assert result.inserted == {"Video": 1, "Frame": 1, "Person": 1,
                                   "FaceDetection": 1, "Activity": 0, "Engagement": 0}
        assert result.skipped == {"Video": 0, "Frame": 0, "Person": 0,
                                  "FaceDetection": 1, "Activity": 0, "Engagement": 0}
        assert table_counts(con)["FaceDetection"] == 1
        video_path = con.execute("SELECT file_path FROM Video").fetchone()[0]
        assert video_path == "data/videos/clip.mp4"
        assert (tmp_path / video_path).is_file()
    finally:
        con.close()


def test_conflicting_duplicate_in_empty_db_rolls_back_everything(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(), make_row(x2=99.0)])
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert not result.committed
        assert result.error is not None and result.error.line_number == 3
        assert "conflicting FaceDetection" in result.error.reason
        assert result.rejected_rows == 2
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_two_persons_in_one_frame(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(person_id="person-1"), make_row(person_id="person-2"),
                        make_row(person_id="person-1")])
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert result.committed
        assert result.inserted["Person"] == 2
        assert result.inserted["Frame"] == 1
        assert result.inserted["FaceDetection"] == 2
        assert result.skipped["FaceDetection"] == 1
        assert table_counts(con) == {"Video": 1, "Frame": 1, "Person": 2,
                                     "FaceDetection": 2, "Activity": 0, "Engagement": 0}
    finally:
        con.close()


def test_same_person_across_videos(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    (videos / "other.mp4").touch()
    one, two = tmp_path / "one.csv", tmp_path / "two.csv"
    write_rows(one, [make_row(frame_id="frame-0")])
    write_rows(two, [make_row(frame_id="frame-1", video_title="Other",
                              video_filename="other.mp4", source_time_seconds=1.0)])
    probe = Mock(return_value=VideoMetadata(fps=24.0))
    monkeypatch.setattr("analysis_db.ingestion.probe_video", probe)
    con = connect_tmp_db(tmp_path)
    try:
        first, second = ingest_files(con, [one, two], videos, repository_root=tmp_path)
        assert first.committed and second.committed
        assert first.inserted["Person"] == 1
        assert second.inserted["Person"] == 0
        assert second.inserted["Video"] == 1
        assert table_counts(con)["Person"] == 1
        assert table_counts(con)["Video"] == 2
        paths = {row[0] for row in con.execute("SELECT file_path FROM Video")}
        assert paths == {"videos/clip.mp4", "videos/other.mp4"}
        assert probe.call_count == 2
    finally:
        con.close()


def test_frame_id_conflicting_signature_rolls_back(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(), make_row(frame_number=1, source_time_seconds=0.5)])
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert not result.committed
        assert result.error.line_number == 3
        assert "conflicting Frame" in result.error.reason
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_alternate_frame_number_collision_rolls_back(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(), make_row(frame_id="frame-1")])
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert not result.committed
        assert result.error.line_number == 3
        assert "conflicting Frame" in result.error.reason
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_title_conflict_within_one_file_rolls_back(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(), make_row(video_title="Renamed", frame_id="frame-1",
                                             source_time_seconds=0.5)])
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert not result.committed
        assert "conflicting Video.title" in result.error.reason
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_metadata_conflict_on_existing_video_across_files(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    one, two = tmp_path / "one.csv", tmp_path / "two.csv"
    write_rows(one, [make_row()])
    write_rows(two, [make_row()])
    probe = Mock(side_effect=[VideoMetadata(fps=24.0), VideoMetadata(fps=30.0)])
    monkeypatch.setattr("analysis_db.ingestion.probe_video", probe)
    con = connect_tmp_db(tmp_path)
    try:
        first = ingest_files(con, [one], videos, repository_root=tmp_path)[0]
        assert first.committed
        second = ingest_files(con, [two], videos, repository_root=tmp_path)[0]
        assert not second.committed
        assert second.error.line_number == 2
        assert "mismatched fps" in second.error.reason
        assert table_counts(con) == {"Video": 1, "Frame": 1, "Person": 1,
                                     "FaceDetection": 1, "Activity": 0, "Engagement": 0}
    finally:
        con.close()


def test_later_missing_video_rolls_back_new_video_writes(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(), make_row(video_filename="ghost.mp4", video_title="Ghost",
                                             frame_id="frame-1", source_time_seconds=1.0)])
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert not result.committed
        assert result.error.line_number == 3
        assert "video file does not exist" in result.error.reason
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        con.close()


def test_invalid_numeric_late_row_rejected(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    source = tmp_path / "rows.csv"
    write_rows(source, [make_row(), make_row(det_score=2.0)])
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], videos, repository_root=tmp_path)[0]
        assert not result.committed
        assert result.error.line_number == 3
        assert "det_score must be between 0 and 1" in result.error.reason
        assert result.rejected_rows == 2
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_failure_then_success_referencing_same_video(tmp_path, monkeypatch, make_row):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "clip.mp4").touch()
    bad, good = tmp_path / "bad.csv", tmp_path / "good.csv"
    write_rows(bad, [make_row(person_id="p-bad"), make_row(det_score=-1.0)])
    write_rows(good, [make_row()])
    probe = Mock(return_value=VideoMetadata(fps=24.0))
    monkeypatch.setattr("analysis_db.ingestion.probe_video", probe)
    con = connect_tmp_db(tmp_path)
    try:
        rejected, committed = ingest_files(con, [bad, good], videos, repository_root=tmp_path)
        assert not rejected.committed
        assert committed.committed and committed.inserted["FaceDetection"] == 1
        rows = con.execute(
            "SELECT person_id, x1, x2, det_score FROM FaceDetection").fetchall()
        assert rows == [("person-1", 1.0, 10.0, 0.9)]
        assert table_counts(con) == {"Video": 1, "Frame": 1, "Person": 1,
                                     "FaceDetection": 1, "Activity": 0, "Engagement": 0}
    finally:
        con.close()


def test_ignored_image_paths_absent_from_persistence(tmp_path, monkeypatch, make_row):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    (video_dir / "clip.mp4").touch()
    csv_dir = tmp_path / "inputs"
    csv_dir.mkdir()
    write_rows(csv_dir / "notes.csv", [make_row()])
    (csv_dir / "frame.jpg").write_bytes(b"\xff\xd9")
    (csv_dir / "photo.png").write_bytes(b"\x89PNG")
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    selected, ignored = discover_inputs(csv_dir)
    assert selected == [csv_dir / "notes.csv"]
    assert ignored == [csv_dir / "frame.jpg", csv_dir / "photo.png"]
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, selected, video_dir, repository_root=tmp_path)[0]
        assert result.committed
        assert con.execute(
            "SELECT COUNT(*) FROM FaceDetection WHERE frame_id LIKE '%jpg%'"
            " OR frame_id LIKE '%png%'").fetchone()[0] == 0
    finally:
        con.close()


def test_header_only_file_commits_zero_counts(tmp_path, monkeypatch, make_row):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    source = tmp_path / "empty.csv"
    write_rows(source, [])
    probe = Mock()
    monkeypatch.setattr("analysis_db.ingestion.probe_video", probe)
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], video_dir, repository_root=tmp_path)[0]
        assert result.committed
        assert result.rows_read == 0
        assert result.error is None
        assert result.inserted == dict.fromkeys(TABLES, 0)
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
        assert probe.call_count == 0
    finally:
        con.close()


def test_incomplete_csv_leaves_fresh_db_empty(tmp_path, monkeypatch, make_row):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    source = tmp_path / "broken.csv"
    source.write_text("video_title,video_filename,frame_number\nClip,clip.mp4,0\n",
                      encoding="utf-8")
    monkeypatch.setattr("analysis_db.ingestion.probe_video",
                        Mock(return_value=VideoMetadata(fps=24.0)))
    con = connect_tmp_db(tmp_path)
    try:
        result = ingest_files(con, [source], video_dir, repository_root=tmp_path)[0]
        assert not result.committed
        assert result.error.line_number == 1
        assert "missing required header column(s)" in result.error.reason
        assert table_counts(con) == dict.fromkeys(TABLES, 0)
    finally:
        con.close()


def test_ingest_files_requires_idle_connection(tmp_path, monkeypatch, make_row):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    source = tmp_path / "rows.csv"
    source.write_text("video_title\nClip\n", encoding="utf-8")
    con = connect_tmp_db(tmp_path)
    try:
        con.execute("BEGIN")
        with pytest.raises(DataError):
            ingest_files(con, [source], video_dir, repository_root=tmp_path)
        con.rollback()
    finally:
        con.close()
