from fractions import Fraction
from types import SimpleNamespace

import av
import numpy as np
import pytest

from analysis_db.clips import generate_clips
from analysis_db.storage import connect_database
from video_retrieval import VideoRetriever


def full_decode(path):
    with av.open(str(path)) as container:
        rows = [(index, Fraction(frame.pts) * frame.time_base, frame.to_ndarray(format="rgb24"))
                for index, frame in enumerate(container.decode(video=0))]
    origin = rows[0][1]
    return [(index, time - origin, image) for index, time, image in rows]


def set_duration(video, duration):
    c = connect_database(video.db_path)
    try:
        c.execute("UPDATE Video SET duration_seconds=?", (duration,))
    finally:
        c.close()


@pytest.mark.parametrize("start,end,indices", [
    (0, 0.125, (0, 1, 2)),
    (0.125, 0.25, (3, 4, 5)),
    (0, 0.5, tuple(range(12))),
    (0.4, 0.5, (10, 11)),
    # Stored REAL timestamps must match decoded timestamps at float precision.
    (0.083, 0.125, (2,)),
    (0, 0.083, (0, 1)),
])
def test_arbitrary_segments_use_exact_half_open_boundaries(video_factory, start, end, indices):
    video = video_factory(count=12)
    set_duration(video, 0.5)
    files_before = set(video.video_path.parent.iterdir())
    retriever = VideoRetriever(video.db_path)
    result = retriever.get_segment(1, start, end)
    assert result.source_frame_indices == indices
    assert (result.requested_start_seconds, result.requested_end_seconds) == (start, end)
    expected = [(index, time, image) for index, time, image in full_decode(video.video_path)
                if start <= float(time) < end]
    np.testing.assert_array_equal(result.frames, np.stack([image for _, _, image in expected]))
    assert result.source_timestamps_seconds == tuple(float(time) for _, time, _ in expected)
    assert result.frames.dtype == np.uint8
    assert set(video.video_path.parent.iterdir()) == files_before


def test_person_clip_resolves_video_membership_summary_and_segment(video_factory):
    video = video_factory(count=12)
    c = connect_database(video.db_path)
    try:
        c.execute("UPDATE Video SET duration_seconds=0.5")
        for index, time, _ in full_decode(video.video_path):
            c.execute("UPDATE Frame SET source_time_seconds=? WHERE frame_number=?", (float(time), index))
        # The synthetic fixture uses independent people at four analyzed frames.
        # A configurable one-frame threshold makes all four intervals confirmed.
        ids = generate_clips(c, 1, persistence_frames=1)
        expected_person = c.execute("SELECT person_id FROM FaceDetection WHERE frame_id='frame/string/0006'").fetchone()[0]
    finally:
        c.close()
    retriever = VideoRetriever(video.db_path)
    info = retriever.get_person_clip_info(ids[2])
    assert info.video_id == 1
    assert info.person_ids == (expected_person,)
    assert info.start_time_seconds == 6 / 24
    assert info.end_time_seconds == 0.458
    np.testing.assert_array_equal(retriever.get_person_clip(ids[2]).frames,
                                  retriever.get_segment(1, 0.25, 0.458).frames)
    assert retriever.get_person_clip(ids[0]).source_frame_indices == (0, 1, 2, 3, 4)
    assert retriever.get_person_clip(ids[-1]).source_frame_indices == (11,)
    summary = retriever.get_person_clip_summary(ids[2], include_details=True)
    assert summary["person_ids"] == [expected_person]
    assert summary["activity"]["records"] == []
    assert summary["engagement"]["observation_count"] == 0


def test_segment_normalizes_nonzero_pts_and_preserves_variable_frame_times(video_factory):
    # Use exact multiples of the fixture encoder's 1/24-second time base.
    timestamps = [(1000 + time, Fraction(1, 1000)) for time in (0, 250, 750, 1000, 1250, 1500)]
    video = video_factory(count=6, frame_timestamps=timestamps)
    set_duration(video, 2)
    assert [float(time) for _, time, _ in full_decode(video.video_path)] == [0, 0.25, 0.75, 1, 1.25, 1.5]
    result = VideoRetriever(video.db_path).get_segment(1, 0.5, 1.5)
    assert result.source_frame_indices == (2, 3, 4)
    assert result.source_timestamps_seconds == (0.75, 1, 1.25)
    np.testing.assert_array_equal(result.frames, np.stack(video.frames[2:5]))


@pytest.mark.parametrize("start,end", [
    (-1, 1), (0, 0), (1, 0), (0, 3), (float("nan"), 1),
    (0, float("inf")), (True, 1), ("0", 1), (None, 1),
])
def test_invalid_segment_boundaries(video, start, end):
    set_duration(video, 2)
    with pytest.raises(ValueError):
        VideoRetriever(video.db_path).get_segment(1, start, end)


def test_segment_with_no_frame_raises_instead_of_padding(video_factory):
    video = video_factory(count=12)
    set_duration(video, 0.5)
    with pytest.raises(ValueError, match="frames"):
        VideoRetriever(video.db_path).get_segment(1, 0.46, 0.49)


def test_missing_clip_video_and_original(video):
    set_duration(video, 2)
    retriever = VideoRetriever(video.db_path)
    with pytest.raises(LookupError):
        retriever.get_person_clip(999)
    with pytest.raises(LookupError):
        retriever.get_segment(999, 0, 1)
    video.video_path.unlink()
    with pytest.raises(FileNotFoundError):
        retriever.get_segment(1, 0, 1)


@pytest.mark.parametrize("pts", [(0, 1000, 500), (0, 1000, 1000), (0, 1000, None)])
def test_segment_rejects_invalid_pts_after_interval_end(video, monkeypatch, pts):
    import video_retrieval.retrieval as retrieval
    set_duration(video, 2)

    # Encoders reject corrupt PTS; inject only the decode stream to exercise
    # the real segment filtering and timestamp validation on invalid sources.
    class CorruptVideo:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def decode(self, **kwargs):
            for timestamp in pts:
                yield SimpleNamespace(pts=timestamp, time_base=Fraction(1, 1000),
                                      to_ndarray=lambda **kwargs: video.frames[0])

    monkeypatch.setattr(retrieval.av, "open", lambda path: CorruptVideo())
    with pytest.raises(ValueError, match="timestamps"):
        VideoRetriever(video.db_path).get_segment(1, 0, 0.75)
