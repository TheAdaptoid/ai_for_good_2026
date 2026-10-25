"""Request bodies. Unknown fields are refused, so clients cannot supply a reviewer_id."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from analysis_db.contracts import Annotation, ReviewEvent


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Body):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1000)


class NoteRequest(_Body):
    note: str | None = Field(default=None, max_length=5000)


class ClipEditRequest(_Body):
    """Omitted values stay unchanged; at least one must be given."""
    activity_label: str | None = Field(default=None, min_length=1, max_length=200)
    positive_score: float | None = Field(default=None, ge=0, le=1)
    neutral_score: float | None = Field(default=None, ge=0, le=1)
    negative_score: float | None = Field(default=None, ge=0, le=1)
    create_activity_label: bool = False  # add activity_label as a new active activity label


class CreateAnnotationRequest(NoteRequest):
    video_id: int
    label_id: int
    start_frame: int
    end_frame: int
    person_id: str | None = None
    clip_id: int | None = None


class EditRequest(NoteRequest):
    """Omitted fields stay unchanged; ``person_id: null`` clears the participant."""
    label_id: int | None = None
    start_frame: int | None = None
    end_frame: int | None = None
    person_id: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    annotation: Annotation
    event: ReviewEvent
