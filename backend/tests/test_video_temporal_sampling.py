from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
import sqlite3

import av
import numpy as np
import pytest

import video_retrieval.retrieval as retrieval
from conftest import set_source_time
from video_retrieval import TemporalClip, VideoRetriever


VFR_TIMES = tuple((pts, Fraction(1, 1000)) for pts in (2000, 2250, 2750, 3250))


def decoded_relative_times(path):
    with av.open(str(path)) as container:
        times = [frame.pts * frame.time_base for frame in container.decode(video=0)]
    origin = times[0]
    return [time - origin for time in times]


def nearest_index(target, times):
    """Independent oracle: nearest frame, earlier index wins exact ties."""
    return min(
        range(len(times)),
        key=lambda index: (abs(times[index] - target), index),
    )


@pytest.mark.parametrize("center, expected, padding", [
    (24, (12, 18, 24, 30, 36), (0, 0)),
    (0, (0, 0, 0, 6, 12), (2, 0)),
    (36, (24, 30, 36, 42, 47), (0, 1)),
])
def test_exact_temporal_samples(video, center, expected, padding):
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(center), interval_seconds=1.0, sample_count=5,
    )
    assert result.source_frame_indices == expected
    assert (result.left_padding_count, result.right_padding_count) == padding
    assert result.unique_frame_count == len(set(expected))
    np.testing.assert_array_equal(
        result.frames, np.stack([video.frames[i] for i in expected]),
    )


@pytest.fixture
def vfr_video(video_factory):
    video = video_factory(4, frame_timestamps=VFR_TIMES)
    relative = decoded_relative_times(video.video_path)
    assert [float(time) for time in relative] == [0.0, 0.25, 0.75, 1.25]
    set_source_time(video, 2, 0.75)
    return video


def test_sampling_brackets_variable_frame_rate_timestamps(vfr_video):
    detection_id = vfr_video.detection(2)
    result = VideoRetriever(vfr_video.db_path).get_temporal_clip(
        detection_id, interval_seconds=2.0, sample_count=9,
    )
    assert result.source_frame_indices == (0, 0, 1, 1, 2, 2, 3, 3, 3)
    assert result.target_timestamps_seconds == (
        -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75,
    )
    assert result.source_timestamps_seconds == (
        0.0, 0.0, 0.25, 0.25, 0.75, 0.75, 1.25, 1.25, 1.25,
    )
    assert result.requested_start_seconds == -0.25
    assert result.requested_end_seconds == 1.75
    assert result.reference_timestamp_seconds == 0.75
    assert (result.left_padding_count, result.right_padding_count) == (1, 2)
    assert result.unique_frame_count == 4
    np.testing.assert_array_equal(
        result.frames,
        np.stack([vfr_video.frames[index]
                  for index in (0, 0, 1, 1, 2, 2, 3, 3, 3)]),
    )


def test_stored_center_drives_window_while_reference_is_decoded(video_factory):
    video = video_factory(4, frame_timestamps=VFR_TIMES)
    set_source_time(video, 2, 0.5)
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(2), interval_seconds=2.0, sample_count=9,
    )
    assert result.reference_timestamp_seconds == 0.75
    assert result.requested_start_seconds == -0.5
    assert result.requested_end_seconds == 1.5
    assert result.target_timestamps_seconds == (
        -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5,
    )
    assert result.source_frame_indices == (0, 0, 0, 1, 1, 2, 2, 3, 3)
    assert result.source_timestamps_seconds == (
        0.0, 0.0, 0.0, 0.25, 0.25, 0.75, 0.75, 1.25, 1.25,
    )
    assert (result.left_padding_count, result.right_padding_count) == (2, 1)


def test_timestamp_origin_invariance(video_factory):
    video = video_factory(4, frame_timestamps=VFR_TIMES, label="vfr-base")
    shifted = video_factory(4, frame_timestamps=tuple(
        (pts + 5000, time_base) for pts, time_base in VFR_TIMES
    ), label="vfr-shifted")
    set_source_time(video, 2, 0.75)
    set_source_time(shifted, 2, 0.75)
    base = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(2), interval_seconds=2.0, sample_count=9,
    )
    moved = VideoRetriever(shifted.db_path).get_temporal_clip(
        shifted.detection(2), interval_seconds=2.0, sample_count=9,
    )
    assert moved.source_frame_indices == base.source_frame_indices
    assert moved.target_timestamps_seconds == base.target_timestamps_seconds
    assert moved.source_timestamps_seconds == base.source_timestamps_seconds
    assert moved.reference_timestamp_seconds == base.reference_timestamp_seconds
    np.testing.assert_array_equal(moved.frames, base.frames)


def test_default_sample_count_is_32(video):
    times = decoded_relative_times(video.video_path)
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(24), interval_seconds=1.0,
    )
    targets = [Fraction(1, 2) + Fraction(k, 31) for k in range(32)]
    expected = tuple(
        nearest_index(Fraction(target), times) for target in targets
    )
    assert result.source_frame_indices == expected
    assert result.frames.shape == (32, 48, 64, 3)
    assert result.frames.dtype == np.uint8
    assert (result.left_padding_count, result.right_padding_count) == (0, 0)
    assert result.reference_timestamp_seconds == 1.0
    assert result.target_timestamps_seconds[0] == 0.5
    assert result.target_timestamps_seconds[-1] == 1.5
    np.testing.assert_array_equal(
        result.frames, np.stack([video.frames[index] for index in expected]),
    )


def test_single_sample_selects_center_keeps_interval_bounds(video):
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(24), interval_seconds=1.0, sample_count=1,
    )
    assert result.source_frame_indices == (24,)
    assert result.target_timestamps_seconds == (1.0,)
    assert result.requested_start_seconds == 0.5
    assert result.requested_end_seconds == 1.5
    assert (result.left_padding_count, result.right_padding_count) == (0, 0)
    assert result.unique_frame_count == 1
    np.testing.assert_array_equal(result.frames[0], video.frames[24])


def test_numpy_integer_sample_count_is_accepted(video):
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(0), interval_seconds=1.0, sample_count=np.int64(3),
    )
    assert result.source_frame_indices == (0, 0, 12)
    assert result.unique_frame_count == 2
    assert type(result.source_frame_indices[0]) is int


def test_one_frame_video_pads_everything_from_the_single_frame(video_factory):
    video = video_factory(1)
    retriever = VideoRetriever(video.db_path)
    result = retriever.get_temporal_clip(
        video.detection(0), interval_seconds=1.0, sample_count=5,
    )
    assert result.source_frame_indices == (0, 0, 0, 0, 0)
    assert (result.left_padding_count, result.right_padding_count) == (2, 2)
    single = retriever.get_temporal_clip(
        video.detection(0), interval_seconds=1.0, sample_count=1,
    )
    assert single.source_frame_indices == (0,)
    assert single.requested_start_seconds == -0.5
    assert single.requested_end_seconds == 0.5
    np.testing.assert_array_equal(result.frames, np.stack(video.frames * 5))


def test_long_padded_window_matches_nearest_frame_oracle(video_factory):
    video = video_factory(7)
    times = decoded_relative_times(video.video_path)
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(3), interval_seconds=2.0, sample_count=32,
    )
    targets = [Fraction(-7, 8) + Fraction(k * 2, 31) for k in range(32)]
    expected = tuple(
        nearest_index(Fraction(target), times) for target in targets
    )
    assert result.source_frame_indices == expected
    assert (result.left_padding_count, result.right_padding_count) == (
        sum(1 for target in targets if target < 0),
        sum(1 for target in targets if target > Fraction(times[-1])),
    )
    assert result.frames.shape == (32, 48, 64, 3)
    np.testing.assert_array_equal(
        result.frames, np.stack([video.frames[index] for index in expected]),
    )


@pytest.mark.parametrize("count", [True, False, 2.5, 5.0, 0, -3, "5", None])
def test_invalid_sample_count_is_rejected(video, count):
    with pytest.raises(ValueError):
        VideoRetriever(video.db_path).get_temporal_clip(
            1, interval_seconds=1.0, sample_count=count,
        )


@pytest.mark.parametrize("interval", [
    True, False, 0.0, -1.0, float("nan"), float("inf"), float("-inf"),
])
def test_invalid_interval_seconds_is_rejected(video, interval):
    with pytest.raises(ValueError):
        VideoRetriever(video.db_path).get_temporal_clip(
            1, interval_seconds=interval, sample_count=5,
        )


@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), float("-inf"), -0.5,
])
def test_invalid_stored_center_is_rejected(video, monkeypatch, value):
    retriever = VideoRetriever(video.db_path)
    broken = replace(
        retriever.get_detection_info(1), source_time_seconds=value,
    )
    monkeypatch.setattr(retriever, "get_detection_info", lambda _id: broken)
    with pytest.raises(ValueError):
        retriever.get_temporal_clip(1, interval_seconds=1.0, sample_count=5)


@pytest.mark.parametrize("frame_number", [48, 60])
def test_reference_beyond_eof_raises_value_error(video, frame_number):
    with pytest.raises(ValueError):
        VideoRetriever(video.db_path).get_temporal_clip(
            video.detection(frame_number), interval_seconds=1.0,
        )


def test_missing_detection_raises_lookup_error(video):
    with pytest.raises(LookupError):
        VideoRetriever(video.db_path).get_temporal_clip(999, interval_seconds=1.0)


def test_missing_original_video_raises_file_not_found(video):
    video.video_path.unlink()
    with pytest.raises(FileNotFoundError):
        VideoRetriever(video.db_path).get_temporal_clip(
            1, interval_seconds=1.0,
        )


def test_corrupt_original_becomes_runtime_error(video):
    video.video_path.write_bytes(b"synthetic invalid video container")
    with pytest.raises(RuntimeError):
        VideoRetriever(video.db_path).get_temporal_clip(1, interval_seconds=1.0)


class ProxyFrame:
    def __init__(self, pts, time_base, conversions):
        self.pts = pts
        self.time_base = time_base
        self._conversions = conversions

    def to_ndarray(self, format="rgb24"):
        self._conversions.append(self)
        return np.full((2, 2, 3), 200, dtype=np.uint8)


class ProxyContainer:
    def __init__(self, frames):
        self._frames = frames

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def decode(self, video=0):
        yield from self._frames


def install_proxy(monkeypatch, frames):
    container = ProxyContainer(frames)
    monkeypatch.setattr(retrieval.av, "open", lambda *args, **kwargs: container)
    return container


@pytest.mark.parametrize("scenario", [
    "missing_pts", "missing_time_base", "zero_time_base",
    "negative_time_base", "duplicate", "decreasing",
])
def test_invalid_timestamps_raise_value_error(video, monkeypatch, scenario):
    conversions = []
    time_base = Fraction(1, 1000)
    if scenario == "missing_pts":
        frames = [ProxyFrame(None, time_base, conversions)]
    elif scenario == "missing_time_base":
        frames = [ProxyFrame(0, None, conversions)]
    elif scenario == "zero_time_base":
        frames = [ProxyFrame(0, Fraction(0), conversions)]
    elif scenario == "negative_time_base":
        frames = [ProxyFrame(0, Fraction(-1, 1000), conversions)]
    elif scenario == "duplicate":
        frames = [ProxyFrame(100, time_base, conversions),
                  ProxyFrame(100, time_base, conversions)]
    else:
        frames = [ProxyFrame(100, time_base, conversions),
                  ProxyFrame(50, time_base, conversions)]
    install_proxy(monkeypatch, frames)
    with pytest.raises(ValueError):
        VideoRetriever(video.db_path).get_temporal_clip(1, interval_seconds=1.0)
    if scenario in {"missing_pts", "missing_time_base",
                    "zero_time_base", "negative_time_base"}:
        assert not conversions


def test_decode_failure_is_wrapped_with_context(video, monkeypatch):
    real_open = av.open

    class FailingContainer:
        def __init__(self, container):
            self._container = container

        def __enter__(self):
            return self

        def __exit__(self, *exception):
            self._container.close()
            return False

        def decode(self, *args, **kwargs):
            for index, frame in enumerate(self._container.decode(*args, **kwargs)):
                if index == 2:
                    raise av.error.InvalidDataError(
                        1094995529, "synthetic decode failure",
                    )
                yield frame

    def failing_open(*args, **kwargs):
        return FailingContainer(real_open(*args, **kwargs))

    monkeypatch.setattr(retrieval.av, "open", failing_open)
    with pytest.raises(RuntimeError, match="synthetic decode failure"):
        VideoRetriever(video.db_path).get_temporal_clip(
            video.detection(24), interval_seconds=1.0, sample_count=5,
        )


class TrackedFrame:
    def __init__(self, frame, conversions):
        self._frame = frame
        self._conversions = conversions

    @property
    def pts(self):
        return self._frame.pts

    @property
    def time_base(self):
        return self._frame.time_base

    def to_ndarray(self, format="rgb24"):
        self._conversions.append(self._frame)
        return self._frame.to_ndarray(format=format)


class TrackedContainer:
    def __init__(self, container, scenario):
        self._container = container
        self._scenario = scenario
        self.closed = False
        self.conversions = []

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
        return False

    def close(self):
        self._container.close()
        self.closed = True

    def decode(self, *args, **kwargs):
        for index, frame in enumerate(self._container.decode(*args, **kwargs)):
            if self._scenario == "decode_failure" and index == 2:
                raise av.error.InvalidDataError(
                    1094995529, "synthetic decode failure",
                )
            yield TrackedFrame(frame, self.conversions)


def install_tracker(monkeypatch, tracked, scenario):
    real_open = av.open

    def tracked_open(*args, **kwargs):
        container = TrackedContainer(real_open(*args, **kwargs), scenario)
        tracked.append(container)
        return container

    monkeypatch.setattr(retrieval.av, "open", tracked_open)


@pytest.mark.parametrize("scenario", ["success", "decode_failure", "beyond_eof"])
def test_temporal_opens_and_closes_exactly_one_container(video, monkeypatch, scenario):
    tracked = []
    install_tracker(monkeypatch, tracked, scenario)
    retriever = VideoRetriever(video.db_path)
    detection_id = video.detection(24 if scenario != "beyond_eof" else 48)
    if scenario == "success":
        retriever.get_temporal_clip(detection_id, interval_seconds=1.0)
    else:
        with pytest.raises(RuntimeError if scenario == "decode_failure" else ValueError):
            retriever.get_temporal_clip(detection_id, interval_seconds=1.0)
    assert len(tracked) == 1
    assert tracked[0].closed


def test_temporal_converts_only_chosen_frames(video, monkeypatch):
    tracked = []
    install_tracker(monkeypatch, tracked, "success")
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(24), interval_seconds=1.0, sample_count=5,
    )
    assert result.source_frame_indices == (12, 18, 24, 30, 36)
    assert len(tracked) == 1
    assert tracked[0].closed
    assert len(tracked[0].conversions) == 5
    converted = {frame.pts for frame in tracked[0].conversions}
    assert converted == {500, 750, 1000, 1250, 1500}


def test_temporal_clip_contract_fields(video):
    result = VideoRetriever(video.db_path).get_temporal_clip(
        video.detection(24), interval_seconds=1.0, sample_count=5,
    )
    assert isinstance(result, TemporalClip)
    assert isinstance(result.frames, np.ndarray)
    assert type(result.source_frame_indices) is tuple
    assert type(result.source_timestamps_seconds) is tuple
    assert type(result.target_timestamps_seconds) is tuple
    assert isinstance(result.requested_start_seconds, float)
    assert isinstance(result.requested_end_seconds, float)
    assert isinstance(result.reference_timestamp_seconds, float)
    assert type(result.left_padding_count) is int
    assert type(result.right_padding_count) is int
    with pytest.raises(FrozenInstanceError):
        result.frames = None


def test_video_retrieval_exports_temporal_clip():
    import video_retrieval

    assert video_retrieval.TemporalClip is TemporalClip
