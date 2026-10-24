from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
import sqlite3

import av
import numpy as np
import pytest

from analysis_db.contracts import DetectionRow
from analysis_db.storage import initialize_database


def patterned_frames(count):
    y, x = np.indices((48, 64))
    frames = []
    for index in range(count):
        image = np.empty((48, 64, 3), dtype=np.uint8)
        image[..., 0] = (index * 5 + x * 2) % 256
        image[..., 1] = (index * 3 + y * 3) % 256
        image[..., 2] = (index * 7 + x + y) % 256
        image[:12, :16] = (220, index * 4 % 256, 10)
        image[:12, 16:32] = (10, 220, index * 4 % 256)
        image[:12, 32:48] = (index * 4 % 256, 10, 220)
        frames.append(image)
    return frames


def encode_video(path, frames, *, codec="ffv1", frame_timestamps=None):
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream(codec, rate=24)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "bgr0" if codec == "ffv1" else "yuv444p"
        if codec == "libx264":
            stream.options = {"bf": "3", "crf": "18", "preset": "medium"}
        for index, image in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            if frame_timestamps is not None:
                pts, time_base = frame_timestamps[index]
                frame.pts = pts
                frame.time_base = time_base
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


@dataclass
class SyntheticVideo:
    db_path: Path
    video_path: Path
    frames: list
    video_id: int = 1

    def detection(self, frame_number, bbox=(8.0, 6.0, 36.0, 30.0)):
        with closing(sqlite3.connect(self.db_path)) as connection:
            frame_id = f"frame/string/{frame_number:04d}"
            connection.execute(
                "INSERT OR IGNORE INTO Frame VALUES (?, ?, ?, ?)",
                (frame_id, self.video_id, frame_number, frame_number / 24),
            )
            detection_id = connection.execute(
                "SELECT COALESCE(MAX(detection_id), 0) + 1 FROM FaceDetection"
            ).fetchone()[0]
            person_id = f"person/string/{detection_id:04d}"
            connection.execute("INSERT INTO Person VALUES (?)", (person_id,))
            connection.execute(
                "INSERT INTO FaceDetection"
                " (detection_id, person_id, frame_id, x1, y1, x2, y2, det_score)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (detection_id, person_id, frame_id, *bbox, 0.95),
            )
            connection.commit()
        return detection_id


def set_source_time(video, frame_number, source_time_seconds):
    with closing(sqlite3.connect(video.db_path)) as connection:
        connection.execute(
            "UPDATE Frame SET source_time_seconds = ? WHERE frame_id = ?",
            (source_time_seconds, f"frame/string/{frame_number:04d}"),
        )
        connection.commit()


@pytest.fixture
def video_factory(tmp_path):
    def make(count=48, *, codec="ffv1", frame_timestamps=None, label=None):
        name = label or f"video-{count}-{codec}"
        directory = tmp_path / name
        directory.mkdir()
        path = directory / "synthetic.mkv"
        frames = patterned_frames(count)
        encode_video(path, frames, codec=codec, frame_timestamps=frame_timestamps)
        db_path = directory / "analysis.sqlite"
        initialize_database(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "INSERT INTO Video"
                " (video_id, title, filename, file_path, fps, width, height)"
                " VALUES (1, 'synthetic', ?, ?, 24, 64, 48)",
                (path.name, str(path)),
            )
            connection.commit()
        result = SyntheticVideo(db_path, path, frames)
        for center in sorted({0, min(5, count - 1), count // 2, count - 1}):
            result.detection(center)
        return result

    return make


@pytest.fixture
def video(video_factory):
    return video_factory()


@pytest.fixture
def make_row():
    base = DetectionRow(2, "Clip", "clip.mp4", 0, "frame-0", "person-1",
                        0.0, 1.0, 2.0, 10.0, 20.0, 0.9)
    return lambda **changes: replace(base, **changes)
