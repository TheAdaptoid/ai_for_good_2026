import json
import sqlite3

import pytest

from analysis_db.clips import generate_clips
from analysis_db.corrections import correct_activity, correct_engagement


def activity(c, frame_id, start, end, label):
    return c.execute(
        "INSERT INTO Activity(frame_id,window_start_seconds,window_end_seconds,sample_count,"
        "activity_label,score,result_json,sampling_json,config_json,config_hash,input_hash)"
        " VALUES(?,?,?,32,?,0.8,'{}','{}','{}','c','i')",
        (frame_id, start, end, label)).lastrowid


def engagement(c, frame_id, person_id, scores):
    return c.execute(
        "INSERT INTO Engagement(detection_id,positive_score,neutral_score,negative_score)"
        " SELECT detection_id,?,?,? FROM FaceDetection WHERE frame_id=? AND person_id=?",
        (*scores, frame_id, person_id)).lastrowid


def test_activity_uses_overlap_weight_not_center_timestamp(person_timeline):
    from analysis_db.clip_analytics import get_clip_summary
    c = person_timeline([{"A"}] * 5 + [{"A", "B"}] * 10)
    clips = generate_clips(c, 1)
    # Clip two is [5,15); both activity centers lie outside this interval.
    activity(c, "f0", 0, 10, "discussion")  # 5 seconds of overlap
    activity(c, "f1", 12.5, 30, "writing")  # 2.5 seconds of overlap
    activity(c, "f2", -10, 5, "excluded")  # touching boundary only
    activity(c, "f3", 15, 20, "excluded")
    result = get_clip_summary(c, clips[1], include_details=True)
    assert result["person_ids"] == ["A", "B"]
    assert result["activity"]["dominant_label"] == "discussion"
    assert result["activity"]["distribution"] == pytest.approx({"discussion": 2/3, "writing": 1/3})
    assert [row["overlap_seconds"] for row in result["activity"]["records"]] == [5, 2.5]
    assert [row["frame_id"] for row in result["activity"]["records"]] == ["f0", "f1"]
    assert json.loads(json.dumps(result))["clip_id"] == clips[1]


def test_activity_ties_and_same_video_filter(person_timeline):
    from analysis_db.clip_analytics import get_clip_summary
    c = person_timeline([{"A"}] * 5)
    clip_id, = generate_clips(c, 1)
    activity(c, "f0", 0, 5, "writing")
    activity(c, "f1", 0, 5, "discussion")
    c.execute("INSERT INTO Video(video_id,title,filename,file_path) VALUES(2,'other','o','o')")
    c.execute("INSERT INTO Frame VALUES('other',2,0,0)")
    activity(c, "other", 0, 100, "other")
    result = get_clip_summary(c, clip_id)["activity"]
    assert result == {"dominant_label": "discussion", "distribution": {"discussion": 0.5, "writing": 0.5}}


def test_missing_observations_and_details_are_optional(person_timeline):
    from analysis_db.clip_analytics import get_clip_summary
    c = person_timeline([{"A", "B"}] * 5)
    clip_id, = generate_clips(c, 1)
    result = get_clip_summary(c, clip_id)
    assert result["activity"] == {"dominant_label": None, "distribution": {}}
    assert result["engagement"] == {"positive": None, "neutral": None, "negative": None, "observation_count": 0}
    assert result["engagement_by_person"]["A"] == result["engagement"]
    assert result["engagement_by_person"]["B"] == result["engagement"]
    assert "records" not in result["activity"]


def test_engagement_group_is_observation_weighted_and_filters_members(person_timeline):
    from analysis_db.clip_analytics import get_clip_summary
    c = person_timeline([{"A", "B", "C"}] * 5 + [{"A", "B", "C", "D"}] * 4)
    clip_id, = generate_clips(c, 1)
    engagement(c, "f0", "A", (0.6, 0.3, 0.1))
    engagement(c, "f1", "A", (0.8, 0.1, 0.1))
    engagement(c, "f0", "B", (0.2, 0.5, 0.3))
    engagement(c, "f5", "D", (1, 0, 0))  # unconfirmed member
    result = get_clip_summary(c, clip_id)
    assert result["engagement"] == pytest.approx({"positive": 1.6/3, "neutral": 0.3, "negative": 0.5/3, "observation_count": 3})
    assert result["engagement_by_person"]["A"] == pytest.approx({"positive": 0.7, "neutral": 0.2, "negative": 0.1, "observation_count": 2})
    assert result["engagement_by_person"]["B"]["observation_count"] == 1
    assert result["engagement_by_person"]["C"]["positive"] is None
    assert "D" not in result["engagement_by_person"]


def test_engagement_half_open_clip_boundaries(person_timeline):
    from analysis_db.clip_analytics import get_clip_summary
    c = person_timeline([{"A"}] * 5 + [{"A", "B"}] * 5)
    first, second = generate_clips(c, 1)
    engagement(c, "f4", "A", (0.9, 0.1, 0))
    engagement(c, "f5", "A", (0.1, 0.9, 0))
    assert get_clip_summary(c, first)["engagement"]["positive"] == 0.9
    assert get_clip_summary(c, second)["engagement"]["positive"] == 0.1


def test_corrections_change_aggregates_without_changing_clips(person_timeline):
    from analysis_db.clip_analytics import get_clip_info, get_clip_summary
    c = person_timeline([{"A"}] * 5)
    clip_id, = generate_clips(c, 1)
    aid = activity(c, "f0", 0, 5, "discussion")
    eid = engagement(c, "f0", "A", (0.2, 0.3, 0.5))
    before = get_clip_info(c, clip_id)
    correct_activity(c, aid, "writing")
    correct_engagement(c, eid, 0.6, 0.3, 0.1)
    assert get_clip_info(c, clip_id) == before
    result = get_clip_summary(c, clip_id)
    assert result["activity"]["distribution"] == {"writing": 1}
    assert result["engagement"]["positive"] == 0.6
    assert generate_clips(c, 1) == (clip_id,)


def test_missing_clip_and_caller_transaction(person_timeline):
    from analysis_db.clip_analytics import get_clip_info, get_clip_summary
    c = person_timeline([{"A"}] * 5)
    clip_id, = generate_clips(c, 1)
    for function in (get_clip_info, get_clip_summary):
        with pytest.raises(LookupError):
            function(c, 99)
    assert not c.in_transaction
    c.execute("BEGIN")
    activity(c, "f0", 0, 5, "writing")
    assert get_clip_summary(c, clip_id)["activity"]["dominant_label"] == "writing"
    assert c.in_transaction
    c.rollback()
    assert get_clip_summary(c, clip_id)["activity"]["dominant_label"] is None
