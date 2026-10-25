import pytest

from analysis_db.annotations import import_machine_output, list_annotations, list_clips
from analysis_db.contracts import AnnotationChanges, AnnotationInput, ClipInput
from analysis_db.review import accept, edit


def ids(annotations):
    return [annotation.annotation_id for annotation in annotations]


def test_multi_label_moment_is_one_set_of_records(review_db, insert_ai_annotation):
    labels = (1, 8, 10)  # Singing, Solo Performance, Sustained Participation
    created = [insert_ai_annotation(review_db, label_id=label, start_frame=500, end_frame=800)
               for label in labels]
    by_video = list_annotations(review_db, video_id=1)
    by_person = list_annotations(review_db, person_id="Person_0001")
    assert ids(by_video) == ids(by_person) == created
    assert {a.label_name for a in by_video} == {"Singing", "Solo Performance",
                                                 "Sustained Participation"}


def test_same_label_overlapping_spans_are_allowed(review_db, insert_ai_annotation):
    first = insert_ai_annotation(review_db, start_frame=100, end_frame=300)
    second = insert_ai_annotation(review_db, start_frame=200, end_frame=400)
    assert ids(list_annotations(review_db, person_id="Person_0001")) == [first, second]


def test_shared_span_returned_for_each_participant(review_db, insert_ai_annotation):
    one = insert_ai_annotation(review_db, person_id="Person_0001", label_id=7)
    two = insert_ai_annotation(review_db, person_id="Person_0002", label_id=7)
    assert ids(list_annotations(review_db, person_id="Person_0001")) == [one]
    assert ids(list_annotations(review_db, person_id="Person_0002")) == [two]
    spans = {(a.start_frame, a.end_frame) for a in list_annotations(review_db, label_id=7)}
    assert spans == {(100, 200)}


def test_group_level_annotation(review_db, insert_ai_annotation):
    group = insert_ai_annotation(review_db, person_id=None, label_id=7)
    [annotation] = list_annotations(review_db, video_id=1)
    assert annotation.annotation_id == group and annotation.person_id is None


def test_category_filter_separates_activities_and_observations(review_db, insert_ai_annotation):
    activity = insert_ai_annotation(review_db, label_id=1)
    observation = insert_ai_annotation(review_db, label_id=16)
    assert ids(list_annotations(review_db, category="activity")) == [activity]
    assert ids(list_annotations(review_db, category="observation")) == [observation]


def test_time_filter_returns_overlapping_spans(review_db, insert_ai_annotation):
    early = insert_ai_annotation(review_db, start_frame=0, end_frame=99)
    middle = insert_ai_annotation(review_db, start_frame=90, end_frame=210)
    late = insert_ai_annotation(review_db, start_frame=300, end_frame=400)
    assert ids(list_annotations(review_db, video_id=1, start_frame=100, end_frame=250)) == [middle]
    assert ids(list_annotations(review_db, video_id=1, end_frame=95)) == [early, middle]
    assert ids(list_annotations(review_db, video_id=1, start_frame=350)) == [late]


def test_seconds_derived_from_fps(review_db, insert_ai_annotation):
    insert_ai_annotation(review_db, start_frame=240, end_frame=480, video_id=2)
    [annotation] = list_annotations(review_db, video_id=2)
    assert (annotation.start_seconds, annotation.end_seconds) == (10.0, 20.0)
    review_db.execute("UPDATE Video SET fps = NULL WHERE video_id = 2")
    [annotation] = list_annotations(review_db, video_id=2)
    assert annotation.start_seconds is None and annotation.end_seconds is None


def test_ordered_by_video_then_start(review_db, insert_ai_annotation):
    c = insert_ai_annotation(review_db, video_id=2, start_frame=0, end_frame=10)
    b = insert_ai_annotation(review_db, video_id=1, start_frame=500, end_frame=600)
    a = insert_ai_annotation(review_db, video_id=1, start_frame=10, end_frame=20)
    assert ids(list_annotations(review_db)) == [a, b, c]


def test_source_and_status_filters(review_db, insert_ai_annotation):
    ai = insert_ai_annotation(review_db)
    human = insert_ai_annotation(review_db, source="HUMAN", review_status="EDITED",
                                 confidence=None, import_key=None)
    assert ids(list_annotations(review_db, source="AI")) == [ai]
    assert ids(list_annotations(review_db, review_status="EDITED")) == [human]


def test_rejected_excluded_by_default(review_db, insert_ai_annotation):
    kept = insert_ai_annotation(review_db)
    rejected = insert_ai_annotation(review_db, review_status="REJECTED")
    assert ids(list_annotations(review_db)) == [kept]
    assert ids(list_annotations(review_db, include_rejected=True)) == [kept, rejected]
    assert ids(list_annotations(review_db, review_status="REJECTED")) == [rejected]


def test_unknown_filter_value_rejected(review_db):
    with pytest.raises(ValueError):
        list_annotations(review_db, category="mood")


# --- Review clips (US8) ------------------------------------------------------------------


def load_clips(connection):
    import_machine_output(connection, 1, [
        ClipInput("v1-late", 1000, 1200, ("Person_0001",), 0.4, "m@1"),
        ClipInput("v1-early", 0, 400, ("Person_0001", "Person_0002"), 2.07, "m@1"),
        ClipInput("v1-unscored", 500, 600, ()),
    ], [AnnotationInput("act", 7, 0, 400, 0.5, None, "v1-early")])
    import_machine_output(connection, 2, [
        ClipInput("v2", 0, 100, ("Person_0003",), 1.1, "m@1"),
    ], [])


def test_clips_in_time_order(review_db):
    load_clips(review_db)
    clips = list_clips(review_db)
    assert [(c.video_id, c.start_frame) for c in clips] == [(1, 0), (1, 500), (1, 1000), (2, 0)]
    assert [c.start_frame for c in list_clips(review_db, video_id=1)] == [0, 500, 1000]


def test_clips_by_priority_unscored_last(review_db):
    load_clips(review_db)
    assert [c.priority_score for c in list_clips(review_db, order="priority")] == [
        2.07, 1.1, 0.4, None]


def test_clips_by_participant(review_db):
    load_clips(review_db)
    clips = list_clips(review_db, person_id="Person_0001")
    assert [c.start_frame for c in clips] == [0, 1000]
    assert clips[0].person_ids == ("Person_0001", "Person_0002")
    assert clips[0].start_seconds == 0.0


def test_clip_annotation_review_leaves_clip_unchanged(review_db):
    load_clips(review_db)
    [clip_level] = list_annotations(review_db, clip_id=list_clips(review_db)[0].clip_id)
    before = review_db.execute("SELECT * FROM ReviewClip ORDER BY 1").fetchall(), \
        review_db.execute("SELECT * FROM ReviewClipParticipant ORDER BY 1, 2").fetchall()
    accept(review_db, clip_level.annotation_id, reviewer_id="r-1")
    edit(review_db, clip_level.annotation_id,
         AnnotationChanges(start_frame=50, person_id="Person_0002"), reviewer_id="r-1")
    after = review_db.execute("SELECT * FROM ReviewClip ORDER BY 1").fetchall(), \
        review_db.execute("SELECT * FROM ReviewClipParticipant ORDER BY 1, 2").fetchall()
    assert after == before
    [edited] = list_annotations(review_db, clip_id=clip_level.clip_id)
    assert (edited.start_frame, edited.person_id) == (50, "Person_0002")


def test_unknown_order_rejected(review_db):
    with pytest.raises(ValueError):
        list_clips(review_db, order="random")


def test_query_speed_at_dataset_scale(review_db):
    """SC-005 / SC-008: about 50k annotations and 5k clips stay interactive (< 1 s)."""
    import time
    persons = [f"Person_{n:04d}" for n in range(4, 101)]
    review_db.executemany("INSERT INTO Person (person_id) VALUES (?)", [(p,) for p in persons])
    review_db.execute("BEGIN")
    review_db.executemany(
        "INSERT INTO ReviewClip (clip_id, video_id, start_frame, end_frame, priority_score,"
        " priority_method, created_at) VALUES (?, 1, ?, ?, ?, 'm@1', 'now')",
        [(n, n % 2000, n % 2000 + 10, (n * 37 % 500) / 100) for n in range(1, 5001)])
    review_db.executemany(
        "INSERT INTO ReviewClipParticipant (clip_id, person_id) VALUES (?, ?)",
        [(n, persons[n % len(persons)]) for n in range(1, 5001)])
    review_db.executemany(
        "INSERT INTO Annotation (video_id, clip_id, person_id, label_id, start_frame,"
        " end_frame, confidence, source, review_status, created_at, updated_at)"
        " VALUES (1, ?, ?, ?, ?, ?, 0.5, 'AI', 'UNREVIEWED', 'now', 'now')",
        [(n % 5000 + 1, persons[n % len(persons)], n % 18 + 1, n % 2300, n % 2300 + 20)
         for n in range(50_000)])
    review_db.commit()
    for query in (lambda: list_annotations(review_db, video_id=1, start_frame=1000,
                                           end_frame=1100),
                  lambda: list_annotations(review_db, person_id="Person_0050"),
                  lambda: list_clips(review_db, order="priority"),
                  lambda: list_clips(review_db, person_id="Person_0050")):
        started = time.perf_counter()
        assert query()
        assert time.perf_counter() - started < 1.0
