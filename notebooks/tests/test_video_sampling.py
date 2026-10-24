import importlib
import os
import weakref

import cv2
import numpy as np
import pytest


def module():
    return importlib.import_module("activity_recognition")


@pytest.mark.parametrize("size,shape", [((96, 64), (64, 96, 3)), ((64, 96), (96, 64, 3))])
def test_uniform_rgb_sampling_preserves_native_shape(make_video, size, shape):
    sampled = module().sample_video(make_video(size=size))

    assert len(sampled.frames) == 32
    assert sampled.indices == np.linspace(0, 59, 32, dtype=np.int64).tolist()
    assert sampled.fps == pytest.approx(30.0)
    assert sampled.frame_count == 60
    assert sampled.duration_seconds == pytest.approx(2.0)
    assert (sampled.width, sampled.height) == size
    for frame in sampled.frames:
        assert frame.shape == shape
        assert frame.dtype == np.uint8
        assert frame[..., 0].min() > 240
        assert frame[..., 2].max() < 15


def test_short_clip_repeats_chronological_samples(make_video):
    sampled = module().sample_video(make_video(frames=3))

    assert len(sampled.frames) == 32
    assert sampled.indices == np.linspace(0, 2, 32, dtype=np.int64).tolist()
    assert sorted(set(sampled.indices)) == [0, 1, 2]
    assert sampled.frame_count == 3
    assert sampled.duration_seconds == pytest.approx(0.1)


def test_custom_count_and_string_path(make_video):
    sampled = module().sample_video(str(make_video()), num_frames=5)

    assert sampled.indices == [0, 14, 29, 44, 59]
    assert len(sampled.frames) == 5


def install_capture(
    monkeypatch,
    *,
    metadata=None,
    seek_mode="normal",
    fail_read_on=None,
    read_error=False,
    rotate=False,
    opened=True,
):
    """Disturb backend capabilities while retaining genuine local video decoding."""
    real_capture = cv2.VideoCapture
    captures = []

    class Capture:
        def __init__(self, path):
            self.inner = real_capture(path)
            self.number = len(captures)
            self.read_indices = []
            self.raw_refs = []
            self.peak_raw_frames = 0
            self.released = False
            self.orientation_enabled = False
            captures.append(self)

        def isOpened(self):
            return opened and self.inner.isOpened()

        def get(self, prop):
            if metadata is not None and prop in metadata:
                return metadata[prop]
            return self.inner.get(prop)

        def set(self, prop, value):
            if prop == getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None):
                self.orientation_enabled = bool(value)
                return True
            if prop == cv2.CAP_PROP_POS_FRAMES:
                if seek_mode == "reject":
                    return False
                if seek_mode == "raise":
                    raise cv2.error("Indexed seeking is unsupported")
                if seek_mode == "ignore":
                    return True
            return self.inner.set(prop, value)

        def read(self):
            index = int(self.inner.get(cv2.CAP_PROP_POS_FRAMES))
            if read_error:
                raise cv2.error("Decoder failed")
            if fail_read_on == (self.number, index):
                return False, None
            ok, frame = self.inner.read()
            if ok:
                self.read_indices.append(index)
                # Embed the real decoded position to detect incorrect seek results.
                frame[0, 0, 1] = index % 256
                if rotate and self.orientation_enabled:
                    frame = np.rot90(frame).copy()
                self.raw_refs.append(weakref.ref(frame))
                self.peak_raw_frames = max(
                    self.peak_raw_frames,
                    sum(ref() is not None for ref in self.raw_refs),
                )
            return ok, frame

        def release(self):
            self.released = True
            self.inner.release()

    monkeypatch.setattr(module().cv2, "VideoCapture", Capture)
    return captures


def assert_sample_positions(sampled):
    assert [int(frame[0, 0, 1]) for frame in sampled.frames] == [
        index % 256 for index in sampled.indices
    ]


@pytest.mark.parametrize("count", [0, -1, 1.5, "32", True, False, None, np.nan, np.inf])
def test_rejects_non_positive_integer_counts_before_open(make_video, monkeypatch, count):
    path = make_video()
    ar = module()
    monkeypatch.setattr(ar.cv2, "VideoCapture", lambda *_: pytest.fail("opened invalid input"))

    with pytest.raises(ValueError, match="positive integer"):
        ar.sample_video(path, num_frames=count)


def test_accepts_numpy_integer_count(make_video):
    sampled = module().sample_video(make_video(), num_frames=np.int64(1))

    assert sampled.indices == [0]
    assert len(sampled.frames) == 1


@pytest.mark.parametrize(
    "path",
    ["https://example.com/a.mp4", "rtsp://host/video", "file:///tmp/a.avi", "s3://bucket/a.mp4", "data:video/mp4,abc"],
)
def test_rejects_uri_schemes_before_open(monkeypatch, path):
    ar = module()
    monkeypatch.setattr(ar.cv2, "VideoCapture", lambda *_: pytest.fail("opened URI"))

    with pytest.raises(ValueError, match="local"):
        ar.sample_video(path)


def test_rejects_missing_path_before_open(tmp_path, monkeypatch):
    ar = module()
    monkeypatch.setattr(ar.cv2, "VideoCapture", lambda *_: pytest.fail("opened missing path"))

    with pytest.raises(FileNotFoundError):
        ar.sample_video(tmp_path / "missing.avi")


def test_rejects_directory_before_open(tmp_path, monkeypatch):
    ar = module()
    monkeypatch.setattr(ar.cv2, "VideoCapture", lambda *_: pytest.fail("opened directory"))

    with pytest.raises(ValueError, match="regular file"):
        ar.sample_video(tmp_path)


def test_rejects_unreadable_file_before_open(make_video, monkeypatch):
    path = make_video()
    path.chmod(0)
    try:
        if os.access(path, os.R_OK):
            pytest.skip("Process can read files regardless of permission bits")
        ar = module()
        monkeypatch.setattr(ar.cv2, "VideoCapture", lambda *_: pytest.fail("opened unreadable file"))
        with pytest.raises(PermissionError):
            ar.sample_video(path)
    finally:
        path.chmod(0o600)


def test_rejects_nonvideo_and_releases_capture(tmp_path, monkeypatch):
    path = tmp_path / "not-video.txt"
    path.write_text("This is not a video.")
    captures = install_capture(monkeypatch)

    with pytest.raises(ValueError, match="[Oo]pen|[Vv]ideo"):
        module().sample_video(path)

    assert captures and all(c.released for c in captures)


@pytest.mark.parametrize("suffix", [".png", ".avi"])
def test_rejects_still_image_even_when_named_like_video(tmp_path, suffix):
    path = tmp_path / f"still{suffix}"
    ok, encoded = cv2.imencode(".png", np.zeros((64, 96, 3), dtype=np.uint8))
    assert ok
    path.write_bytes(encoded.tobytes())

    with pytest.raises(ValueError, match="video|image"):
        module().sample_video(path)


def test_valid_metadata_uses_only_unique_indexed_reads(make_video, monkeypatch):
    path = make_video()
    captures = install_capture(monkeypatch)

    sampled = module().sample_video(path)

    assert_sample_positions(sampled)
    assert len(captures) == 1
    assert captures[0].read_indices == np.linspace(0, 59, 32, dtype=np.int64).tolist()
    assert captures[0].released


@pytest.mark.parametrize("fps", [0.0, -1.0, np.nan, np.inf])
def test_rejects_unusable_fps_and_releases_capture(make_video, monkeypatch, fps):
    path = make_video()
    captures = install_capture(monkeypatch, metadata={cv2.CAP_PROP_FPS: fps})

    with pytest.raises(ValueError, match="FPS"):
        module().sample_video(path)

    assert captures and all(c.released for c in captures)


def test_rejects_empty_stream_and_releases_captures(make_video, monkeypatch):
    path = make_video(frames=0)
    captures = install_capture(monkeypatch)

    with pytest.raises(ValueError, match="[Ee]mpty|no frames"):
        module().sample_video(path)

    assert captures and all(c.released for c in captures)


def test_cannot_open_capture_is_released(make_video, monkeypatch):
    path = make_video()
    captures = install_capture(monkeypatch, opened=False)

    with pytest.raises(ValueError, match="[Oo]pen"):
        module().sample_video(path)

    assert captures and all(c.released for c in captures)


@pytest.mark.parametrize("count", [0.0, -1.0, np.nan, np.inf, 2.5])
def test_unknown_or_invalid_count_uses_sequential_fallback(make_video, monkeypatch, count):
    path = make_video()
    captures = install_capture(monkeypatch, metadata={cv2.CAP_PROP_FRAME_COUNT: count})

    sampled = module().sample_video(path)

    assert sampled.frame_count == 60
    assert sampled.indices == np.linspace(0, 59, 32, dtype=np.int64).tolist()
    assert sampled.duration_seconds == pytest.approx(2.0)
    assert_sample_positions(sampled)
    assert len(captures) >= 3
    assert all(c.released for c in captures)


@pytest.mark.parametrize("seek_mode", ["reject", "raise", "ignore"])
def test_unusable_seeking_uses_sequential_fallback(make_video, monkeypatch, seek_mode):
    path = make_video()
    captures = install_capture(monkeypatch, seek_mode=seek_mode)

    sampled = module().sample_video(path)

    assert sampled.frame_count == 60
    assert sampled.indices == np.linspace(0, 59, 32, dtype=np.int64).tolist()
    assert_sample_positions(sampled)
    assert len(captures) >= 3
    assert all(c.released for c in captures)


def test_indexed_read_failure_recounts_then_decodes(make_video, monkeypatch):
    path = make_video()
    captures = install_capture(monkeypatch, fail_read_on=(0, 59))

    sampled = module().sample_video(path)

    assert sampled.indices[-1] == 59
    assert_sample_positions(sampled)
    assert len(captures) >= 3
    assert all(c.released for c in captures)


@pytest.mark.parametrize("fallback", [False, True])
def test_short_clip_decodes_unique_samples_once(make_video, monkeypatch, fallback):
    path = make_video(frames=3)
    metadata = {cv2.CAP_PROP_FRAME_COUNT: 0.0} if fallback else None
    captures = install_capture(monkeypatch, metadata=metadata)
    real_convert = cv2.cvtColor
    converted = []

    def convert(frame, code):
        converted.append(int(frame[0, 0, 1]))
        return real_convert(frame, code)

    monkeypatch.setattr(module().cv2, "cvtColor", convert)
    sampled = module().sample_video(path)

    assert sampled.indices == np.linspace(0, 2, 32, dtype=np.int64).tolist()
    assert_sample_positions(sampled)
    assert captures[-1].read_indices == [0, 1, 2]
    assert converted == [0, 1, 2]
    assert all(c.released for c in captures)


def test_sequential_fallback_retains_only_requested_frames(make_video, monkeypatch):
    path = make_video(frames=600)
    captures = install_capture(monkeypatch, metadata={cv2.CAP_PROP_FRAME_COUNT: 0.0})
    real_convert = cv2.cvtColor
    converted_refs = []

    def convert(frame, code):
        result = real_convert(frame, code)
        converted_refs.append(weakref.ref(result))
        assert sum(ref() is not None for ref in converted_refs) <= 32
        return result

    monkeypatch.setattr(module().cv2, "cvtColor", convert)
    sampled = module().sample_video(path)

    assert sampled.frame_count == 600
    assert sampled.indices[0] == 0 and sampled.indices[-1] == 599
    assert_sample_positions(sampled)
    assert len(converted_refs) == 32
    assert all(c.peak_raw_frames <= 3 for c in captures)
    assert all(c.released for c in captures)


def test_unreproducible_range_fails_and_releases_captures(make_video, monkeypatch):
    path = make_video()
    captures = install_capture(
        monkeypatch,
        metadata={cv2.CAP_PROP_FRAME_COUNT: 0.0},
        fail_read_on=(2, 10),
    )

    with pytest.raises(ValueError, match="range|frame"):
        module().sample_video(path)

    assert len(captures) >= 3
    assert all(c.released for c in captures)


def test_decoder_library_error_has_context_cause_and_cleanup(make_video, monkeypatch):
    path = make_video()
    captures = install_capture(monkeypatch, read_error=True)

    with pytest.raises(ValueError, match="video|Video") as error:
        module().sample_video(path)

    assert isinstance(error.value.__cause__, cv2.error)
    assert str(path) in str(error.value)
    assert captures and all(c.released for c in captures)


def test_auto_orientation_uses_actual_decoded_dimensions(make_video, monkeypatch):
    if not hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
        pytest.skip("OpenCV does not expose orientation control")
    path = make_video()
    captures = install_capture(monkeypatch, rotate=True)

    sampled = module().sample_video(path)

    assert (sampled.width, sampled.height) == (64, 96)
    assert all(frame.shape == (96, 64, 3) for frame in sampled.frames)
    assert all(c.orientation_enabled and c.released for c in captures)
