from fractions import Fraction

import numpy as np
import pytest

from video_retrieval import VideoRetriever


@pytest.mark.parametrize("codec", ["ffv1", "libx264"])
@pytest.mark.parametrize("center", [0, 24, 47])
def test_indexed_samples_match_reference(video_factory, codec, center):
    from video_retrieval.indexed import IndexedTemporalSampler
    video = video_factory(codec=codec)
    detection = video.detection(center)
    sampler = IndexedTemporalSampler(video.video_path)
    expected = VideoRetriever(video.db_path).get_temporal_clip(detection, 2.0)
    actual = sampler.sample(reference_frame_number=center, center_seconds=center / 24,
                            interval_seconds=2.0)
    assert np.array_equal(actual.frames, expected.frames)
    for key in expected.__dataclass_fields__:
        if key != "frames":
            assert getattr(actual, key) == getattr(expected, key)


def test_nonzero_vfr_pts_and_failed_seek_recover_exact_samples(video_factory, monkeypatch):
    from video_retrieval.indexed import IndexedTemporalSampler
    from conftest import set_source_time
    stamps = [(120 + i * i + i, Fraction(1, 24)) for i in range(12)]
    video = video_factory(12, frame_timestamps=stamps)
    set_source_time(video, 5, 1.25)
    detection = video.detection(5)
    sampler = IndexedTemporalSampler(video.video_path)
    original = sampler._decode_selected
    def late(indices, *, seek):
        return {} if seek else original(indices, seek=False)
    monkeypatch.setattr(sampler, "_decode_selected", late)
    actual = sampler.sample(reference_frame_number=5, center_seconds=1.25, interval_seconds=3.0)
    expected = VideoRetriever(video.db_path).get_temporal_clip(detection, 3.0)
    assert np.array_equal(actual.frames, expected.frames)
    assert actual.source_frame_indices == expected.source_frame_indices
    assert sampler.fallback_count == 1
    with pytest.raises(ValueError, match="beyond"):
        sampler.sample(reference_frame_number=999, center_seconds=1)
