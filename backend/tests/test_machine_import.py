import pytest

from analysis_db.annotations import import_machine_output, list_annotations, list_clips
from analysis_db.contracts import AnnotationChanges, AnnotationInput, ClipInput, DataError
from analysis_db.review import accept, create_annotation, defer, edit, reject

REVIEWER = "r-1"


def ai(key, label_id=1, start=100, end=200, confidence=0.6, person="Person_0001", clip=None):
    return AnnotationInput(key, label_id, start, end, confidence, person, clip)


def rows(connection, table):
    return connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


# --- US7: protected annotation import -----------------------------------------------------

def test_first_import_inserts_ai_unreviewed(review_db):
    result = import_machine_output(review_db, 1, [], [ai("k1"), ai("k2", label_id=16)])
    assert (result.inserted, result.updated, result.skipped_protected) == (2, 0, 0)
    annotations = list_annotations(review_db)
    assert {(a.source, a.review_status) for a in annotations} == {("AI", "UNREVIEWED")}


def test_identical_reimport_creates_no_duplicates(review_db):
    import_machine_output(review_db, 1, [], [ai("k1")])
    result = import_machine_output(review_db, 1, [], [ai("k1")])
    assert (result.inserted, result.updated) == (0, 0)
    assert len(list_annotations(review_db)) == 1


def test_changed_unreviewed_annotation_updated_in_place(review_db):
    import_machine_output(review_db, 1, [], [ai("k1")])
    [before] = list_annotations(review_db)
    result = import_machine_output(review_db, 1, [], [ai("k1", label_id=2, confidence=0.9)])
    [after] = list_annotations(review_db)
    assert result.updated == 1
    assert after.annotation_id == before.annotation_id
    assert (after.label_id, after.confidence) == (2, 0.9)
    assert (after.source, after.review_status) == ("AI", "UNREVIEWED")


@pytest.mark.parametrize("review", [
    lambda c, i: accept(c, i, reviewer_id=REVIEWER),
    lambda c, i: edit(c, i, AnnotationChanges(label_id=3), reviewer_id=REVIEWER),
    lambda c, i: reject(c, i, reviewer_id=REVIEWER),
    lambda c, i: defer(c, i, reviewer_id=REVIEWER),
])
def test_reviewed_annotations_are_protected(review_db, review):
    import_machine_output(review_db, 1, [], [ai("k1")])
    [annotation] = list_annotations(review_db, include_rejected=True)
    review(review_db, annotation.annotation_id)
    before = rows(review_db, "Annotation"), rows(review_db, "ReviewEvent")
    result = import_machine_output(review_db, 1, [], [ai("k1", label_id=2, confidence=0.99)])
    assert result.skipped_protected == 1 and result.updated == 0
    assert (rows(review_db, "Annotation"), rows(review_db, "ReviewEvent")) == before


def test_human_created_annotations_untouched(review_db):
    created, _ = create_annotation(review_db, video_id=1, label_id=1, start_frame=100,
                                   end_frame=200, reviewer_id=REVIEWER)
    before = rows(review_db, "Annotation")
    import_machine_output(review_db, 1, [], [ai("k1")])
    assert rows(review_db, "Annotation")[0] == before[0]


def test_missing_from_later_import_is_kept(review_db):
    import_machine_output(review_db, 1, [], [ai("k1"), ai("k2")])
    import_machine_output(review_db, 1, [], [ai("k1")])
    assert len(list_annotations(review_db)) == 2


@pytest.mark.parametrize("bad", [
    ai("k2", label_id=6),                 # deactivated below
    ai("k2", start=300, end=200),         # reversed span
    ai("k2", end=5000),                   # beyond video
    ai(""),                               # missing import key
    ai("k2", person="Person_9999"),       # unknown participant
])
def test_invalid_input_rolls_back_whole_import(review_db, bad):
    review_db.execute("UPDATE Label SET is_active = 0 WHERE label_id = 6")
    with pytest.raises(DataError):
        import_machine_output(review_db, 1, [], [ai("k1"), bad])
    assert rows(review_db, "Annotation") == []


def test_duplicate_keys_in_one_import_rejected(review_db):
    with pytest.raises(DataError):
        import_machine_output(review_db, 1, [], [ai("k1"), ai("k1")])


# --- US8: review clips --------------------------------------------------------------------

def clip(key="c1", start=0, end=479, persons=("Person_0001", "Person_0002"), score=2.07,
         method="positive-weighted@1"):
    return ClipInput(key, start, end, persons, score, method)


def test_clip_import_with_participants_and_annotations(review_db):
    result = import_machine_output(
        review_db, 1, [clip(), clip("c2", 480, 959, (), None, None)],
        [ai("a1", label_id=7, start=0, end=479, person=None, clip="c1"),
         ai("a2", label_id=16, start=10, end=300, clip="c1")])
    assert (result.clips_inserted, result.inserted) == (2, 2)
    first, second = list_clips(review_db)
    assert first.person_ids == ("Person_0001", "Person_0002")
    assert (first.priority_score, first.priority_method) == (2.07, "positive-weighted@1")
    assert second.person_ids == () and second.priority_score is None
    assert {a.clip_id for a in list_annotations(review_db)} == {first.clip_id}


def test_clip_level_span_must_match_clip(review_db):
    with pytest.raises(DataError, match="span"):
        import_machine_output(review_db, 1, [clip()],
                              [ai("a1", start=0, end=400, person=None, clip="c1")])
    assert rows(review_db, "ReviewClip") == []


def test_clip_must_be_in_same_video(review_db):
    import_machine_output(review_db, 2, [clip("other", 0, 100)], [])
    with pytest.raises(DataError, match="video"):
        import_machine_output(review_db, 1, [], [ai("a1", clip="other")])


def test_unknown_clip_key_rejected(review_db):
    with pytest.raises(DataError):
        import_machine_output(review_db, 1, [], [ai("a1", clip="nope")])


def test_unprotected_clip_updated_in_place(review_db):
    import_machine_output(review_db, 1, [clip()], [ai("a1", label_id=16, clip="c1")])
    [before] = list_clips(review_db)
    result = import_machine_output(review_db, 1, [clip(score=0.5, persons=("Person_0003",))], [])
    [after] = list_clips(review_db)
    assert result.clips_updated == 1
    assert after.clip_id == before.clip_id
    assert (after.priority_score, after.person_ids) == (0.5, ("Person_0003",))


def test_clip_with_protected_annotation_untouched(review_db):
    import_machine_output(review_db, 1, [clip()],
                          [ai("a1", label_id=7, start=0, end=479, person=None, clip="c1")])
    [annotation] = list_annotations(review_db)
    accept(review_db, annotation.annotation_id, reviewer_id=REVIEWER)
    before = rows(review_db, "ReviewClip"), rows(review_db, "ReviewClipParticipant")
    result = import_machine_output(review_db, 1, [clip(start=0, end=999, score=9.0,
                                                       persons=("Person_0003",))], [])
    assert result.clips_skipped_protected == 1 and result.clips_updated == 0
    assert (rows(review_db, "ReviewClip"), rows(review_db, "ReviewClipParticipant")) == before


def test_clip_missing_from_later_import_is_kept(review_db):
    import_machine_output(review_db, 1, [clip(), clip("c2", 480, 959)],
                          [ai("a2", label_id=16, start=500, end=600, clip="c2")])
    import_machine_output(review_db, 1, [clip()], [])
    assert len(list_clips(review_db)) == 2
    assert len(list_annotations(review_db)) == 1


def test_create_annotation_rejects_clip_from_other_video(review_db):
    import_machine_output(review_db, 2, [clip("other", 0, 100)], [])
    [other] = list_clips(review_db, video_id=2)
    with pytest.raises(DataError, match="video"):
        create_annotation(review_db, video_id=1, label_id=1, start_frame=0, end_frame=100,
                          person_id="Person_0001", clip_id=other.clip_id, reviewer_id=REVIEWER)
    assert rows(review_db, "Annotation") == []


# --- Convergence: import accounting (T052, T053) ------------------------------------------

@pytest.mark.parametrize("review", [
    lambda c, i: accept(c, i, reviewer_id=REVIEWER),
    lambda c, i: reject(c, i, reviewer_id=REVIEWER),
    lambda c, i: defer(c, i, reviewer_id=REVIEWER),
])
def test_identical_reimport_of_reviewed_annotation_counts_protected(review_db, review):
    import_machine_output(review_db, 1, [], [ai("k1")])
    [annotation] = list_annotations(review_db)
    review(review_db, annotation.annotation_id)
    before = rows(review_db, "Annotation")
    result = import_machine_output(review_db, 1, [], [ai("k1")])
    assert (result.inserted, result.updated, result.skipped_protected) == (0, 0, 1)
    assert rows(review_db, "Annotation") == before


def test_identical_reimport_of_unreviewed_annotation_is_unchanged(review_db):
    import_machine_output(review_db, 1, [], [ai("k1")])
    result = import_machine_output(review_db, 1, [], [ai("k1")])
    assert (result.inserted, result.updated, result.skipped_protected) == (0, 0, 0)


def participant_rowids(connection):
    return connection.execute(
        "SELECT rowid, clip_id, person_id FROM ReviewClipParticipant ORDER BY 1").fetchall()


def test_identical_clip_reimport_is_a_noop(review_db):
    import_machine_output(review_db, 1, [clip()], [])
    before = rows(review_db, "ReviewClip"), participant_rowids(review_db)
    result = import_machine_output(review_db, 1, [clip(persons=("Person_0002", "Person_0001",
                                                                "Person_0001"))], [])
    assert (result.clips_inserted, result.clips_updated, result.clips_skipped_protected) == (
        0, 0, 0)
    assert (rows(review_db, "ReviewClip"), participant_rowids(review_db)) == before


@pytest.mark.parametrize("changed", [
    clip(score=0.5),
    clip(method="positive-weighted@2"),
    clip(end=500),
    clip(persons=("Person_0001",)),
    clip(persons=("Person_0001", "Person_0002", "Person_0003")),
])
def test_changed_clip_reimport_updates(review_db, changed):
    import_machine_output(review_db, 1, [clip()], [])
    result = import_machine_output(review_db, 1, [changed], [])
    assert result.clips_updated == 1
    [stored] = list_clips(review_db)
    assert (stored.end_frame, stored.priority_score, stored.priority_method,
            stored.person_ids) == (changed.end_frame, changed.priority_score,
                                   changed.priority_method, tuple(sorted(changed.person_ids)))


def test_identical_reimport_of_protected_clip_counts_protected(review_db):
    import_machine_output(review_db, 1, [clip()],
                          [ai("a1", label_id=7, start=0, end=479, person=None, clip="c1")])
    [annotation] = list_annotations(review_db)
    accept(review_db, annotation.annotation_id, reviewer_id=REVIEWER)
    before = rows(review_db, "ReviewClip"), participant_rowids(review_db)
    result = import_machine_output(review_db, 1, [clip()], [])
    assert (result.clips_updated, result.clips_skipped_protected) == (0, 1)
    assert (rows(review_db, "ReviewClip"), participant_rowids(review_db)) == before


# --- Convergence: protection wins over label validation (T057) ----------------------------

def test_reviewed_annotation_with_deactivated_label_is_skipped(review_db):
    import_machine_output(review_db, 1, [], [ai("k1", label_id=6)])
    [annotation] = list_annotations(review_db)
    accept(review_db, annotation.annotation_id, reviewer_id=REVIEWER)
    review_db.execute("UPDATE Label SET is_active = 0 WHERE label_id = 6")
    before = rows(review_db, "Annotation"), rows(review_db, "ReviewEvent")
    result = import_machine_output(review_db, 1, [], [ai("k1", label_id=6),
                                                      ai("k2", label_id=1, start=300, end=400)])
    assert (result.inserted, result.updated, result.skipped_protected) == (1, 0, 1)
    annotations = rows(review_db, "Annotation")
    assert annotations[0] == before[0][0]  # reviewed row byte-identical, still on label 6
    assert annotations[0][4] == 6
    assert rows(review_db, "ReviewEvent") == before[1]
    [new] = [a for a in list_annotations(review_db) if a.annotation_id != annotation.annotation_id]
    assert (new.label_id, new.source, new.review_status) == (1, "AI", "UNREVIEWED")


def test_inactive_label_still_blocked_for_update_eligible_rows(review_db):
    import_machine_output(review_db, 1, [], [ai("k1", label_id=1)])
    review_db.execute("UPDATE Label SET is_active = 0 WHERE label_id = 6")
    before = rows(review_db, "Annotation")
    with pytest.raises(DataError, match="inactive"):
        import_machine_output(review_db, 1, [], [ai("k1", label_id=6)])
    with pytest.raises(DataError, match="inactive"):
        import_machine_output(review_db, 1, [], [ai("k9", label_id=6)])
    assert rows(review_db, "Annotation") == before
