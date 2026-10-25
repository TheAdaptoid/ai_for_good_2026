import pytest

from analysis_db.annotations import list_annotations
from analysis_db.contracts import DataError
from analysis_db.labels import create_label, list_labels, set_label_active, update_label


def test_create_label(review_db):
    label = create_label(review_db, "Shares Original Song", "observation", "Performs own song")
    assert label.label_id == 19 and label.is_active
    assert label.category == "observation" and label.description == "Performs own song"
    assert label in list_labels(review_db, category="observation")


def test_duplicate_name_within_category_rejected(review_db):
    with pytest.raises(DataError):
        create_label(review_db, "singing", "activity")
    assert create_label(review_db, "Singing", "observation").category == "observation"


@pytest.mark.parametrize("name, category", [("  ", "activity"), ("Mood", "emotion")])
def test_invalid_label_rejected(review_db, name, category):
    with pytest.raises(DataError):
        create_label(review_db, name, category)


def test_rename_follows_annotations(review_db, insert_ai_annotation):
    insert_ai_annotation(review_db, label_id=1)
    update_label(review_db, 1, name="Vocal Performance", description="Singing or rapping")
    [annotation] = list_annotations(review_db)
    assert annotation.label_id == 1 and annotation.label_name == "Vocal Performance"


def test_deactivate_hides_label_but_keeps_annotations(review_db, insert_ai_annotation):
    insert_ai_annotation(review_db, label_id=6)
    label = set_label_active(review_db, 6, False)
    assert not label.is_active
    assert 6 not in [l.label_id for l in list_labels(review_db)]
    assert 6 in [l.label_id for l in list_labels(review_db, include_inactive=True)]
    assert list_annotations(review_db)[0].label_name == "Rehearsal"
    assert set_label_active(review_db, 6, True).is_active


def test_unknown_label(review_db):
    with pytest.raises(LookupError):
        update_label(review_db, 999, name="x")
    with pytest.raises(LookupError):
        set_label_active(review_db, 999, False)


def test_no_delete_function():
    import analysis_db.labels as labels
    assert not any(name.startswith("delete") for name in dir(labels))
