from contextlib import closing
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
import sqlite3

import av
import numpy as np
import pytest

from analysis_db.storage import initialize_database
from video_retrieval import DetectionInfo, VideoRetriever
import video_retrieval.retrieval as retrieval


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


def encode_video(path, frames, *, codec="ffv1"):
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream(codec, rate=24)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "bgr0" if codec == "ffv1" else "yuv444p"
        if codec == "libx264":
            stream.options = {"bf": "3", "crf": "18", "preset": "medium"}
        for image in frames:
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
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


@pytest.fixture
def video_factory(tmp_path):
    def make(count=48, *, codec="ffv1"):
        directory = tmp_path / f"video-{count}-{codec}"
        directory.mkdir()
        path = directory / "synthetic.mkv"
        frames = patterned_frames(count)
        encode_video(path, frames, codec=codec)
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


@pytest.mark.parametrize("index", [0, 1, 24, 47])
def test_frame_is_exact_zero_based_original_rgb(video, index):
    image = VideoRetriever(video.db_path).get_frame(1, index)
    assert image.shape == (48, 64, 3)
    assert image.dtype == np.uint8
    np.testing.assert_array_equal(image, video.frames[index])


@pytest.mark.parametrize("index", [-1, 48, 1000])
def test_invalid_frame_index_raises_value_error(video, index):
    with pytest.raises(ValueError):
        VideoRetriever(video.db_path).get_frame(1, index)


def test_missing_video_record_raises_lookup_error(video):
    with pytest.raises(LookupError):
        VideoRetriever(video.db_path).get_frame(999, 0)


@pytest.mark.parametrize("method", ["get_face", "get_clip", "get_detection_info"])
def test_missing_detection_raises_lookup_error(video, method):
    with pytest.raises(LookupError):
        getattr(VideoRetriever(video.db_path), method)(999)


@pytest.mark.parametrize("method", ["get_frame", "get_face", "get_clip"])
def test_missing_original_video_raises_file_not_found(video, method):
    detection_id = video.detection(24)
    video.video_path.unlink()
    retriever = VideoRetriever(video.db_path)
    arguments = (1, 24) if method == "get_frame" else (detection_id,)
    with pytest.raises(FileNotFoundError):
        getattr(retriever, method)(*arguments)


@pytest.mark.parametrize("bbox,expected_slice", [
    ((8.0, 6.0, 36.0, 30.0), (slice(6, 30), slice(8, 36))),
    ((8.8, 6.2, 35.1, 29.3), (slice(6, 30), slice(8, 36))),
    ((-8.5, -6.5, 70.2, 54.3), (slice(0, 48), slice(0, 64))),
    ((-8.5, 6.2, 12.1, 54.3), (slice(6, 48), slice(0, 13))),
])
def test_face_uses_floor_ceil_clamped_unresized_pixels(video, bbox, expected_slice):
    detection_id = video.detection(24, bbox)
    retriever = VideoRetriever(video.db_path)
    source = retriever.get_frame(1, 24)
    crop = retriever.get_face(detection_id)
    assert crop.dtype == np.uint8
    np.testing.assert_array_equal(crop, source[expected_slice])
    np.testing.assert_array_equal(crop, video.frames[24][expected_slice])


@pytest.mark.parametrize("bbox", [
    (-20.0, 5.0, -1.0, 20.0),
    (65.0, 5.0, 80.0, 20.0),
    (5.0, -20.0, 20.0, -1.0),
    (5.0, 49.0, 20.0, 60.0),
])
def test_wholly_offscreen_bbox_raises_instead_of_returning_empty_crop(video, bbox):
    with pytest.raises(ValueError):
        VideoRetriever(video.db_path).get_face(video.detection(24, bbox))


@pytest.mark.parametrize("center", [0, 5, 24, 47])
def test_all_32_clip_slots_have_correct_order_and_edge_padding(video, center):
    clip = VideoRetriever(video.db_path).get_clip(video.detection(center))
    assert clip.shape == (32, 48, 64, 3)
    assert clip.dtype == np.uint8
    for slot in range(32):
        source_index = min(max(center - 16 + slot, 0), 47)
        np.testing.assert_array_equal(
            clip[slot], video.frames[source_index], err_msg=f"slot {slot}"
        )


@pytest.mark.parametrize("count,center", [(1, 0), (7, 0), (7, 3), (7, 6)])
def test_short_video_pads_each_slot_from_actual_decoded_bounds(video_factory, count, center):
    video = video_factory(count)
    clip = VideoRetriever(video.db_path).get_clip(video.detection(center))
    assert clip.shape == (32, 48, 64, 3)
    assert clip.dtype == np.uint8
    for slot in range(32):
        index = min(max(center - 16 + slot, 0), count - 1)
        np.testing.assert_array_equal(clip[slot], video.frames[index])


@pytest.mark.parametrize("method", ["get_face", "get_clip"])
def test_detection_beyond_eof_cannot_be_hidden_by_edge_padding(video, method):
    detection_id = video.detection(48)
    with pytest.raises(ValueError):
        getattr(VideoRetriever(video.db_path), method)(detection_id)


def test_metadata_preserves_string_ids_and_returns_frozen_typed_values(video):
    detection_id = video.detection(24, (8.8, 6.2, 35.1, 29.3))
    info = VideoRetriever(video.db_path).get_detection_info(detection_id)
    assert isinstance(info, DetectionInfo)
    assert info == DetectionInfo(
        detection_id=detection_id,
        person_id=f"person/string/{detection_id:04d}",
        video_id=1,
        frame_id="frame/string/0024",
        frame_number=24,
        source_time_seconds=1.0,
        bbox=(8.8, 6.2, 35.1, 29.3),
    )
    for value in (info.detection_id, info.video_id, info.frame_number):
        assert type(value) is int
    assert type(info.person_id) is str
    assert type(info.frame_id) is str
    assert type(info.source_time_seconds) is float
    assert type(info.bbox) is tuple
    assert all(type(value) is float for value in info.bbox)
    with pytest.raises(FrozenInstanceError):
        info.frame_number = 0


def test_explicit_relative_database_path_resolves_against_cwd(video, monkeypatch):
    monkeypatch.chdir(video.db_path.parent)
    retriever = VideoRetriever(Path("analysis.sqlite"))
    assert retriever.db_path == video.db_path.resolve()
    np.testing.assert_array_equal(retriever.get_frame(1, 0), video.frames[0])


def test_repository_relative_original_path_uses_repository_root(video, monkeypatch):
    monkeypatch.setattr(retrieval, "REPOSITORY_ROOT", video.video_path.parent)
    with closing(sqlite3.connect(video.db_path)) as connection:
        connection.execute("UPDATE Video SET file_path = ?", (video.video_path.name,))
        connection.commit()
    np.testing.assert_array_equal(
        VideoRetriever(str(video.db_path)).get_frame(1, 24), video.frames[24]
    )


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "not-created.sqlite"
    with pytest.raises((sqlite3.OperationalError, FileNotFoundError)):
        VideoRetriever(missing)
    assert not missing.exists()


def test_every_database_connection_is_read_only_and_closed(video, monkeypatch):
    real_connect = retrieval.connect_database
    opened = []

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO Person VALUES ('should-not-be-written')")
        return connection

    monkeypatch.setattr(retrieval, "connect_database", connect)
    retriever = VideoRetriever(video.db_path)
    retriever.get_frame(1, 0)
    retriever.get_detection_info(1)
    retriever.get_face(1)
    retriever.get_clip(1)
    with pytest.raises(LookupError):
        retriever.get_detection_info(999)
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


@pytest.mark.parametrize("method", ["get_frame", "get_face", "get_clip"])
def test_corrupt_original_becomes_runtime_error(video, method):
    video.video_path.write_bytes(b"synthetic invalid video container")
    arguments = (1, 0) if method == "get_frame" else (1,)
    with pytest.raises(RuntimeError):
        getattr(VideoRetriever(video.db_path), method)(*arguments)


@pytest.mark.parametrize("scenario", ["clip", "frame", "beyond_eof", "decode_failure"])
def test_decoder_is_opened_once_and_closed_even_when_retrieval_fails(video, monkeypatch, scenario):
    real_open = av.open
    opened = []

    class TrackedContainer:
        def __init__(self, container):
            self.container = container
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *exception):
            self.close()

        def __getattr__(self, name):
            return getattr(self.container, name)

        def close(self):
            self.container.close()
            self.closed = True

        def decode(self, *args, **kwargs):
            for index, frame in enumerate(self.container.decode(*args, **kwargs)):
                if scenario == "decode_failure" and index == 2:
                    raise av.error.InvalidDataError(1094995529, "synthetic decode failure")
                yield frame

    def tracked_open(*args, **kwargs):
        container = TrackedContainer(real_open(*args, **kwargs))
        opened.append(container)
        return container

    monkeypatch.setattr(retrieval.av, "open", tracked_open)
    retriever = VideoRetriever(video.db_path)
    if scenario == "clip":
        clip = retriever.get_clip(1)
        np.testing.assert_array_equal(clip[16], video.frames[0])
    elif scenario == "frame":
        np.testing.assert_array_equal(retriever.get_frame(1, 24), video.frames[24])
    else:
        error = ValueError if scenario == "beyond_eof" else RuntimeError
        with pytest.raises(error):
            retriever.get_frame(1, 100 if scenario == "beyond_eof" else 24)
    assert len(opened) == 1
    assert opened[0].closed


def test_h264_b_frames_follow_presentation_order(video_factory):
    try:
        av.codec.Codec("libx264", "w")
    except (av.error.FFmpegError, av.codec.codec.UnknownCodecError):
        pytest.skip("PyAV build does not provide the libx264 encoder")
    video = video_factory(codec="libx264")
    with av.open(str(video.video_path)) as container:
        decoded = list(container.decode(video=0))
        assert any(frame.pict_type == av.video.frame.PictureType.B for frame in decoded)
        expected = [frame.to_ndarray(format="rgb24") for frame in decoded]
    assert len(expected) == 48
    sources = np.stack(video.frames).astype(np.int16)

    def assert_source_identity(image, index):
        # Compression may change pixels, but the intended original pattern must
        # remain strictly closer than every other frame, including both neighbors.
        distances = np.abs(sources - image.astype(np.int16)).mean(axis=(1, 2, 3))
        nearest = int(np.argmin(distances))
        assert nearest == index, f"source frame {index} matched frame {nearest}"
        assert distances[index] < np.min(np.delete(distances, index)), (
            f"source frame {index} did not have a unique nearest-pattern match"
        )

    retriever = VideoRetriever(video.db_path)
    for index in range(48):
        image = retriever.get_frame(1, index)
        np.testing.assert_array_equal(image, expected[index])
        assert_source_identity(image, index)
    clip = retriever.get_clip(video.detection(24))
    for slot in range(32):
        np.testing.assert_array_equal(clip[slot], expected[8 + slot])
        assert_source_identity(clip[slot], 8 + slot)
