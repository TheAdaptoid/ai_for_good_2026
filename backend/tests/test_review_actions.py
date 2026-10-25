import pytest

from analysis_db.contracts import UNSET, AnnotationChanges, DataError
from analysis_db.review import accept, create_annotation, defer, edit, get_history, reject
from analysis_db.storage import connect_database

SINGING, DANCING, ACTING, SPOKEN = 1, 2, 3, 4
SUSTAINED = 10
REVIEWER = "r-1"


def event_count(connection, annotation_id):
    return connection.execute(
        "SELECT COUNT(*) FROM ReviewEvent WHERE annotation_id = ?", (annotation_id,)).fetchone()[0]


def snapshot(connection):
    return (connection.execute("SELECT * FROM Annotation ORDER BY 1").fetchall(),
            connection.execute("SELECT * FROM ReviewEvent ORDER BY 1").fetchall())


# --- Accept / Reject / Defer -------------------------------------------------------------

@pytest.mark.parametrize("action, status", [(accept, "ACCEPTED"), (reject, "REJECTED"),
                                            (defer, "DEFERRED")])
def test_status_only_actions_from_unreviewed(review_db, insert_ai_annotation, action, status):
    annotation_id = insert_ai_annotation(review_db)
    annotation, event = action(review_db, annotation_id, reviewer_id=REVIEWER, note="n")
    assert (annotation.label_id, annotation.start_frame, annotation.end_frame) == (SINGING, 100, 200)
    assert annotation.source == "AI" and annotation.review_status == status
    assert annotation.confidence == 0.6
    assert event.action == status and event.reviewer_id == REVIEWER and event.note == "n"
    assert (event.prev_status, event.new_status) == ("UNREVIEWED", status)
    assert (event.prev_source, event.new_source) == ("AI", "AI")
    assert event.prev_label_id == event.new_label_id == SINGING
    assert event.prev_confidence == event.new_confidence == 0.6
    assert event_count(review_db, annotation_id) == 1


def test_accept_after_edit_keeps_human(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    edit(review_db, annotation_id, AnnotationChanges(label_id=SPOKEN), reviewer_id=REVIEWER)
    annotation, _ = accept(review_db, annotation_id, reviewer_id=REVIEWER)
    assert annotation.source == "HUMAN" and annotation.review_status == "ACCEPTED"


# --- Edit --------------------------------------------------------------------------------

def test_label_edit(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    annotation, event = edit(review_db, annotation_id, AnnotationChanges(label_id=SPOKEN),
                             reviewer_id=REVIEWER)
    assert annotation.label_name == "Spoken Performance"
    assert annotation.source == "HUMAN" and annotation.review_status == "EDITED"
    assert annotation.confidence is None
    assert event.action == "EDITED"
    assert (event.prev_label_id, event.new_label_id) == (SINGING, SPOKEN)
    assert (event.prev_confidence, event.new_confidence) == (0.6, None)


@pytest.mark.parametrize("changes", [
    AnnotationChanges(start_frame=150),
    AnnotationChanges(end_frame=250),
    AnnotationChanges(person_id="Person_0002"),
    AnnotationChanges(person_id=None),
])
def test_span_or_person_edit(review_db, insert_ai_annotation, changes):
    annotation_id = insert_ai_annotation(review_db)
    annotation, event = edit(review_db, annotation_id, changes, reviewer_id=REVIEWER)
    assert annotation.source == "HUMAN" and annotation.review_status == "EDITED"
    assert event.action == "EDITED"
    assert (event.prev_person_id, event.prev_start_frame, event.prev_end_frame) == (
        "Person_0001", 100, 200)
    assert (event.new_person_id, event.new_start_frame, event.new_end_frame) == (
        annotation.person_id, annotation.start_frame, annotation.end_frame)


def test_noop_edit_becomes_accept(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    same = AnnotationChanges(label_id=SINGING, start_frame=100, end_frame=200,
                             person_id="Person_0001")
    annotation, event = edit(review_db, annotation_id, same, reviewer_id=REVIEWER)
    assert annotation.source == "AI" and annotation.review_status == "ACCEPTED"
    assert annotation.confidence == 0.6 and event.action == "ACCEPTED"


def test_editing_rejected_annotation_makes_it_visible(review_db, insert_ai_annotation):
    from analysis_db.annotations import list_annotations
    annotation_id = insert_ai_annotation(review_db)
    reject(review_db, annotation_id, reviewer_id=REVIEWER)
    assert list_annotations(review_db) == []
    annotation, _ = edit(review_db, annotation_id, AnnotationChanges(label_id=DANCING),
                         reviewer_id=REVIEWER)
    assert annotation.review_status == "EDITED"
    assert [a.annotation_id for a in list_annotations(review_db)] == [annotation_id]


# --- Full transition matrix (SC-003, FR-014) ---------------------------------------------

STARTING_STATES = {
    "AI/UNREVIEWED": [],
    "AI/ACCEPTED": [accept],
    "AI/REJECTED": [reject],
    "AI/DEFERRED": [defer],
    "HUMAN/EDITED": ["edit"],
    "HUMAN/ACCEPTED": ["edit", accept],
    "HUMAN/REJECTED": ["edit", reject],
    "HUMAN/DEFERRED": ["edit", defer],
}
ACTIONS = ["accept", "edit_change", "edit_noop", "reject", "defer"]


def apply(connection, annotation_id, step):
    if step == "edit":
        return edit(connection, annotation_id, AnnotationChanges(label_id=DANCING),
                    reviewer_id=REVIEWER)
    return step(connection, annotation_id, reviewer_id=REVIEWER)


@pytest.mark.parametrize("state", STARTING_STATES)
@pytest.mark.parametrize("action", ACTIONS)
def test_transition_matrix(review_db, insert_ai_annotation, state, action):
    annotation_id = insert_ai_annotation(review_db)
    for step in STARTING_STATES[state]:
        apply(review_db, annotation_id, step)
    start_source, start_status = state.split("/")
    start_confidence = 0.6 if start_source == "AI" else None
    before = event_count(review_db, annotation_id)

    calls = {
        "accept": lambda: accept(review_db, annotation_id, reviewer_id=REVIEWER),
        "edit_change": lambda: edit(review_db, annotation_id, AnnotationChanges(label_id=ACTING),
                                    reviewer_id=REVIEWER),
        "edit_noop": lambda: edit(review_db, annotation_id, AnnotationChanges(),
                                  reviewer_id=REVIEWER),
        "reject": lambda: reject(review_db, annotation_id, reviewer_id=REVIEWER),
        "defer": lambda: defer(review_db, annotation_id, reviewer_id=REVIEWER),
    }
    annotation, event = calls[action]()
    expected = {
        "accept": (start_source, "ACCEPTED", start_confidence),
        "edit_change": ("HUMAN", "EDITED", None),
        "edit_noop": (start_source, "ACCEPTED", start_confidence),
        "reject": (start_source, "REJECTED", start_confidence),
        "defer": (start_source, "DEFERRED", start_confidence),
    }[action]
    assert (annotation.source, annotation.review_status, annotation.confidence) == expected
    assert annotation.review_status != "UNREVIEWED"
    assert (event.prev_source, event.prev_status) == (start_source, start_status)
    assert event_count(review_db, annotation_id) == before + 1


# --- Validation (FR-015: nothing changes on failure) -------------------------------------

@pytest.mark.parametrize("changes", [
    AnnotationChanges(label_id=SUSTAINED),           # cross-category
    AnnotationChanges(start_frame=300),              # reversed span
    AnnotationChanges(end_frame=2398),               # at video end (2398 frames)
    AnnotationChanges(person_id="Person_9999"),      # unknown participant
    AnnotationChanges(label_id=999),                 # unknown label
])
def test_invalid_edit_changes_nothing(review_db, insert_ai_annotation, changes):
    annotation_id = insert_ai_annotation(review_db)
    before = snapshot(review_db)
    with pytest.raises(DataError):
        edit(review_db, annotation_id, changes, reviewer_id=REVIEWER)
    assert snapshot(review_db) == before


def test_edit_to_deactivated_label_rejected(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    review_db.execute("UPDATE Label SET is_active = 0 WHERE label_id = ?", (DANCING,))
    before = snapshot(review_db)
    with pytest.raises(DataError, match="inactive"):
        edit(review_db, annotation_id, AnnotationChanges(label_id=DANCING), reviewer_id=REVIEWER)
    assert snapshot(review_db) == before


@pytest.mark.parametrize("changes", [AnnotationChanges(start_frame=120),
                                     AnnotationChanges(person_id="Person_0003")])
def test_span_or_person_edit_keeps_deactivated_label(review_db, insert_ai_annotation, changes):
    annotation_id = insert_ai_annotation(review_db)
    review_db.execute("UPDATE Label SET is_active = 0 WHERE label_id = ?", (SINGING,))
    annotation, _ = edit(review_db, annotation_id, changes, reviewer_id=REVIEWER)
    assert annotation.label_id == SINGING
    assert (annotation.source, annotation.review_status) == ("HUMAN", "EDITED")


@pytest.mark.parametrize("reviewer_id", ["", "   ", None])
def test_blank_reviewer_rejected(review_db, insert_ai_annotation, reviewer_id):
    annotation_id = insert_ai_annotation(review_db)
    before = snapshot(review_db)
    with pytest.raises(DataError):
        accept(review_db, annotation_id, reviewer_id=reviewer_id)
    assert snapshot(review_db) == before


def test_reviewer_id_is_opaque(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    _, event = accept(review_db, annotation_id, reviewer_id=" staff:42 ")
    assert event.reviewer_id == " staff:42 "


def test_unknown_annotation(review_db):
    with pytest.raises(LookupError):
        accept(review_db, 12345, reviewer_id=REVIEWER)


# --- Concurrency -------------------------------------------------------------------------

def test_second_reviewer_sees_first_result(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    db_path = review_db.execute("PRAGMA database_list").fetchone()[2]
    other = connect_database(db_path, must_exist=True)
    try:
        _, first = edit(review_db, annotation_id, AnnotationChanges(label_id=DANCING),
                        reviewer_id="r-1")
        _, second = reject(other, annotation_id, reviewer_id="r-2")
    finally:
        other.close()
    assert (second.prev_label_id, second.prev_source, second.prev_status) == (
        first.new_label_id, first.new_source, first.new_status)


def test_unset_sentinel_is_distinct_from_none():
    assert AnnotationChanges().person_id is UNSET


# --- History (US3) -----------------------------------------------------------------------

def test_history_reconstructs_original_ai_value(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    edit(review_db, annotation_id, AnnotationChanges(label_id=SPOKEN), reviewer_id="r-1")
    defer(review_db, annotation_id, reviewer_id="r-2", note="check with teacher")
    accept(review_db, annotation_id, reviewer_id="r-3")
    history = get_history(review_db, annotation_id)
    assert [e.action for e in history] == ["EDITED", "DEFERRED", "ACCEPTED"]
    assert [e.reviewer_id for e in history] == ["r-1", "r-2", "r-3"]
    assert (history[0].prev_label_id, history[0].prev_confidence) == (SINGING, 0.6)
    assert history[1].note == "check with teacher"
    for earlier, later in zip(history, history[1:]):
        assert earlier.event_id < later.event_id


def test_earlier_events_unchanged_by_later_reviews(review_db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(review_db)
    accept(review_db, annotation_id, reviewer_id=REVIEWER)
    [first] = get_history(review_db, annotation_id)
    reject(review_db, annotation_id, reviewer_id=REVIEWER)
    assert get_history(review_db, annotation_id)[0] == first


# --- Create (US6) ------------------------------------------------------------------------

def test_create_annotation(review_db):
    from analysis_db.annotations import list_annotations
    annotation, event = create_annotation(
        review_db, video_id=1, label_id=9, start_frame=1000, end_frame=1500,
        person_id="Person_0002", reviewer_id=REVIEWER, note="missed poem")
    assert (annotation.source, annotation.review_status) == ("HUMAN", "ACCEPTED")
    assert annotation.confidence is None
    assert review_db.execute("SELECT import_key FROM Annotation WHERE annotation_id = ?",
                             (annotation.annotation_id,)).fetchone() == (None,)
    assert event.action == "CREATED" and event.note == "missed poem"
    assert (event.prev_label_id, event.prev_start_frame, event.prev_end_frame,
            event.prev_person_id, event.prev_confidence, event.prev_source,
            event.prev_status) == (None,) * 7
    assert (event.new_label_id, event.new_source, event.new_status) == (9, "HUMAN", "ACCEPTED")
    assert [a.annotation_id for a in list_annotations(review_db, video_id=1)] == [
        annotation.annotation_id]
    assert [a.annotation_id for a in list_annotations(review_db, person_id="Person_0002")] == [
        annotation.annotation_id]


@pytest.mark.parametrize("overrides", [
    {"label_id": 6},                              # deactivated below
    {"start_frame": 500, "end_frame": 400},       # reversed
    {"end_frame": 2398},                          # at video end
    {"reviewer_id": "  "},
    {"person_id": "Person_9999"},
])
def test_invalid_create_stores_nothing(review_db, overrides):
    review_db.execute("UPDATE Label SET is_active = 0 WHERE label_id = 6")
    arguments = {"video_id": 1, "label_id": 1, "start_frame": 0, "end_frame": 10,
                 "reviewer_id": REVIEWER} | overrides
    with pytest.raises(DataError):
        create_annotation(review_db, **arguments)
    assert snapshot(review_db) == ([], [])


@pytest.mark.parametrize("step, expected", [
    ("edit", ("HUMAN", "EDITED")),
    (reject, ("HUMAN", "REJECTED")),
    (defer, ("HUMAN", "DEFERRED")),
])
def test_created_annotation_follows_normal_rules(review_db, step, expected):
    created, _ = create_annotation(review_db, video_id=1, label_id=1, start_frame=0,
                                   end_frame=10, reviewer_id=REVIEWER)
    annotation, _ = apply(review_db, created.annotation_id, step)
    assert (annotation.source, annotation.review_status) == expected
    assert len(get_history(review_db, created.annotation_id)) == 2
