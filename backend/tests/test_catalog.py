import pytest

from analysis_db import catalog
from analysis_db.contracts import PresenceInterval


def add_detections(connection, video_id, person_id, times):
    for moment in times:
        frame_number = round(moment * 24)
        frame_id = f"V{video_id}_F{frame_number}"
        connection.execute("INSERT OR IGNORE INTO Frame VALUES (?, ?, ?, ?)",
                           (frame_id, video_id, frame_number, moment))
        connection.execute(
            "INSERT INTO FaceDetection (person_id, frame_id, x1, y1, x2, y2, det_score)"
            " VALUES (?, ?, 0, 0, 1, 1, 0.9)", (person_id, frame_id))


@pytest.fixture
def seeded(review_db, insert_ai_annotation):
    add_detections(review_db, 1, "Person_0001", [1.0, 1.5, 3.0, 10.0])
    add_detections(review_db, 1, "Person_0002", [0.5])
    add_detections(review_db, 2, "Person_0001", [4.0, 5.0])
    insert_ai_annotation(review_db)
    insert_ai_annotation(review_db, review_status="REJECTED")
    return review_db


def test_list_videos_counts_with_zeros(seeded):
    one, two = catalog.list_videos(seeded)
    assert (one.participant_count, one.detection_count, one.frame_count) == (2, 5, 2398)
    assert one.annotation_counts == {"UNREVIEWED": 1, "ACCEPTED": 0, "EDITED": 0,
                                     "REJECTED": 1, "DEFERRED": 0}
    assert one.clip_count == 0
    assert (two.participant_count, two.detection_count) == (1, 2)
    assert set(two.annotation_counts.values()) == {0}


def test_get_video_unknown(seeded):
    with pytest.raises(LookupError):
        catalog.get_video(seeded, 99)


def test_presence_merges_gaps_up_to_tolerance(seeded):
    first, second = catalog.video_participants(seeded, 1)
    assert first.person_id == "Person_0002"  # ordered by first appearance
    assert first.intervals == (PresenceInterval(0.5, 0.5, 1),)  # single detection
    assert (second.first_seconds, second.last_seconds, second.detection_count) == (1.0, 10.0, 4)
    # 1.5 -> 3.0 is a 1.5 s gap (merged); 3.0 -> 10.0 exceeds 2 s (split).
    assert second.intervals == (PresenceInterval(1.0, 3.0, 3), PresenceInterval(10.0, 10.0, 1))


def test_presence_unknown_video(seeded):
    with pytest.raises(LookupError):
        catalog.video_participants(seeded, 99)


def test_participants_and_detail(seeded):
    summaries = {p.person_id: p for p in catalog.list_participants(seeded)}
    assert (summaries["Person_0001"].video_count, summaries["Person_0001"].detection_count) == (2, 6)
    assert (summaries["Person_0003"].video_count, summaries["Person_0003"].detection_count) == (0, 0)
    detail = catalog.get_participant(seeded, "Person_0001")
    assert [(v.video_id, v.first_seconds, v.last_seconds, v.detection_count)
            for v in detail.videos] == [(1, 1.0, 10.0, 4), (2, 4.0, 5.0, 2)]
    with pytest.raises(LookupError):
        catalog.get_participant(seeded, "Person_9999")


def test_video_file_confined_to_directory(review_db, tmp_path):
    inside = tmp_path / "videos" / "a.mp4"
    inside.parent.mkdir()
    inside.write_bytes(b"x")
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"x")
    review_db.execute("UPDATE Video SET file_path = ? WHERE video_id = 1", (str(inside),))
    review_db.execute("UPDATE Video SET file_path = ? WHERE video_id = 2",
                      (str(inside.parent / ".." / "secret.mp4"),))
    assert catalog.video_file(review_db, 1, inside.parent) == inside.resolve()
    with pytest.raises(LookupError):
        catalog.video_file(review_db, 2, inside.parent)
    inside.unlink()
    with pytest.raises(LookupError):
        catalog.video_file(review_db, 1, inside.parent)
