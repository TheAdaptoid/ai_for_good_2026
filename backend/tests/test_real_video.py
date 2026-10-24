import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from analysis_db.paths import REPOSITORY_ROOT
from analysis_db.storage import connect_database, table_counts

BACKEND = Path(__file__).resolve().parents[1]
HEADER = ["video_title", "video_filename", "frame_number", "frame_id", "person_id",
          "source_time_seconds", "face_bbox_x1", "face_bbox_y1", "face_bbox_x2",
          "face_bbox_y2", "det_score"]

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available")


def test_real_video_ingestion_and_repeat(tmp_path):
    with tempfile.TemporaryDirectory(prefix="analysis_db_real_video_",
                                     dir=REPOSITORY_ROOT) as root_name:
        root = Path(root_name)
        video_dir = root / "data" / "videos"
        video_dir.mkdir(parents=True)
        video_path = video_dir / "clip.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x48:r=24",
             "-t", "1", "-an", "-c:v", "mpeg4", str(video_path)],
            check=True, capture_output=True, timeout=30)

        source = root / "detections.csv"
        with source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADER)
            writer.writerow(["Clip", "clip.mp4", 0, "frame-0", "person-1",
                             0.0, 1.0, 1.0, 10.0, 20.0, 0.9])
            writer.writerow(["Clip", "clip.mp4", 1, "frame-1", "person-2",
                             1 / 24, 2.0, 2.0, 8.0, 16.0, 0.8])

        db = root / "analysis.sqlite"
        init_command = [sys.executable, str(BACKEND / "scripts" / "init_db.py"),
                        "--db", str(db)]
        ingest_command = [sys.executable, str(BACKEND / "scripts" / "ingest.py"),
                          "--input", str(source), "--db", str(db),
                          "--video-dir", str(video_dir)]
        initialized = subprocess.run(init_command, cwd=tmp_path,
                                     capture_output=True, text=True)
        assert initialized.returncode == 0, initialized.stderr
        first = subprocess.run(ingest_command, cwd=tmp_path,
                               capture_output=True, text=True)
        assert first.returncode == 0, (first.stdout, first.stderr)
        assert "detections.csv: committed; rows=2 inserted=2 skipped=0 rejected=0" \
            in first.stdout
        connection = connect_database(db, must_exist=True)
        try:
            original_ids = connection.execute(
                "SELECT detection_id FROM FaceDetection ORDER BY detection_id"
            ).fetchall()
        finally:
            connection.close()

        repeat = subprocess.run(ingest_command, cwd=tmp_path,
                                capture_output=True, text=True)
        assert repeat.returncode == 0, (repeat.stdout, repeat.stderr)
        assert "rows=2 inserted=0 skipped=2 rejected=0" in repeat.stdout

        connection = connect_database(db, must_exist=True)
        try:
            assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
            assert table_counts(connection) == {
                "Video": 1, "Frame": 2, "Person": 2, "FaceDetection": 2,
                "Activity": 0, "Engagement": 0}
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            stored_ids = connection.execute(
                "SELECT detection_id FROM FaceDetection ORDER BY detection_id"
            ).fetchall()
            assert stored_ids == original_ids
            video = connection.execute(
                "SELECT title, filename, file_path, duration_seconds, fps,"
                " width, height FROM Video").fetchone()
            assert video[0] == "Clip" and video[1] == "clip.mp4"
            assert video[4] == pytest.approx(24.0, rel=0.02)
            assert video[5] == 64 and video[6] == 48
            assert video[3] == pytest.approx(1.0, rel=0.25)
            assert (REPOSITORY_ROOT / video[2]).resolve() == video_path.resolve()
            frames = connection.execute(
                "SELECT frame_id, frame_number, source_time_seconds FROM Frame"
                " ORDER BY frame_number").fetchall()
            assert [frame[0] for frame in frames] == ["frame-0", "frame-1"]
            assert [frame[1] for frame in frames] == [0, 1]
            assert frames[0][2] == 0.0
            bbox, score = connection.execute(
                "SELECT x1, det_score FROM FaceDetection WHERE person_id='person-1'"
            ).fetchone()
            assert bbox == 1.0 and score == pytest.approx(0.9)
        finally:
            connection.close()

        extracted = [p.suffix.lower() for p in root.rglob("*") if p.is_file()]
        assert not any(suffix in {".png", ".jpg", ".jpeg", ".bmp"} for suffix in extracted)
