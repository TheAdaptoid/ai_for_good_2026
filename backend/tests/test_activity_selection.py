import sqlite3

import pytest


def test_distinct_frames_include_low_count_people_and_smallest_anchor(video):
    from activity_pipeline.selection import select_frame_jobs
    with sqlite3.connect(video.db_path) as c:
        c.execute("INSERT INTO Person VALUES('extra')")
        c.execute("INSERT INTO FaceDetection VALUES(99,'extra','frame/string/0000',0,0,5,5,0.8)")
        c.execute("INSERT INTO Frame VALUES('empty',1,49,2.1)")
        jobs = select_frame_jobs(c)
        assert len(jobs) == 4
        assert jobs[0].frame_number == 0
        assert jobs[0].anchor_detection_id == 1
        assert len({j.frame_id for j in jobs}) == 4
        assert select_frame_jobs(c, video_ids=(999,)) == []


def test_seeded_membership_is_stable_and_sorted():
    from activity_pipeline.config import FrameJob
    from activity_pipeline.selection import sample_frame_jobs
    jobs = [FrameJob(f"f{i}", 1, i, float(i), i + 1) for i in range(6)]
    selected = sample_frame_jobs(jobs, sample_size=3, seed=42)
    assert [j.frame_id for j in selected] == ["f0", "f4", "f5"]
    assert sample_frame_jobs(jobs, sample_size=None) == jobs
    assert sample_frame_jobs([], sample_size=100) == []
    with pytest.raises(ValueError):
        sample_frame_jobs(jobs, sample_size=7)
    with pytest.raises(ValueError):
        sample_frame_jobs(jobs, sample_size=0)
