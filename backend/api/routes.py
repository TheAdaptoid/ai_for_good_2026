"""Thin HTTP layer over analysis_db. Every route here requires a signed-in staff account."""

import io
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response

from analysis_db import catalog, corrections, exports, review, stored_analysis
from analysis_db.annotations import fetch_annotation, get_clip, list_annotations, list_clips
from analysis_db.contracts import (
    UNSET, DataError, Annotation, AnnotationChanges, ImportRun, Label, LabelCategory, ParticipantDetail,
    ParticipantSummary, ReviewClip, ReviewEvent, ReviewStatus, Source, VideoParticipant,
    VideoSummary,
)
from analysis_db.labels import list_labels
from analysis_db.pipeline_import import list_import_runs
from analysis_db.stored_analysis import ActivityCount, PersonClip, StoredClipSummary, VideoProgress
from api.auth import Db, Staff, current_staff
from video_retrieval.thumbnail import frame_jpeg
from api.schemas import ClipEditRequest, CreateAnnotationRequest, EditRequest, NoteRequest, ReviewResult

router = APIRouter(prefix="/api", dependencies=[Depends(current_staff)])
Format = Annotated[Literal["csv", "json"], Query()]


# --- Videos and participants -------------------------------------------------------------

@router.get("/videos", tags=["videos"])
def videos(connection: Db) -> list[VideoSummary]:
    return catalog.list_videos(connection)


@router.get("/videos/{video_id}", tags=["videos"])
def video(video_id: int, connection: Db) -> VideoSummary:
    return catalog.get_video(connection, video_id)


@router.get("/videos/{video_id}/participants", tags=["videos"])
def video_participants(video_id: int, connection: Db) -> list[VideoParticipant]:
    return catalog.video_participants(connection, video_id)


@router.get("/videos/{video_id}/stream", tags=["videos"], response_class=FileResponse)
def stream(video_id: int, request: Request, connection: Db) -> FileResponse:
    # FileResponse answers Range requests with 206, which browsers need for seeking.
    response = FileResponse(catalog.video_file(connection, video_id, request.app.state.video_dir),
                            media_type="video/mp4")
    response.chunk_size = 1024 * 1024  # Fewer threadpool reads for local video transfers.
    return response


@router.get("/participants", tags=["participants"])
def participants(connection: Db) -> list[ParticipantSummary]:
    return catalog.list_participants(connection)


@router.get("/participants/{person_id}", tags=["participants"])
def participant(person_id: str, connection: Db) -> ParticipantDetail:
    return catalog.get_participant(connection, person_id)


# --- Annotations and review --------------------------------------------------------------

@router.get("/annotations", tags=["annotations"])
def annotations(connection: Db, video_id: int | None = None, start_frame: int | None = None,
                end_frame: int | None = None, person_id: str | None = None,
                label_id: int | None = None, category: LabelCategory | None = None,
                source: Source | None = None, review_status: ReviewStatus | None = None,
                clip_id: int | None = None, include_rejected: bool = False) -> list[Annotation]:
    return list_annotations(
        connection, video_id=video_id, start_frame=start_frame, end_frame=end_frame,
        person_id=person_id, label_id=label_id, category=category, source=source,
        review_status=review_status, clip_id=clip_id, include_rejected=include_rejected)


@router.get("/annotations/{annotation_id}", tags=["annotations"])
def annotation(annotation_id: int, connection: Db) -> Annotation:
    return fetch_annotation(connection, annotation_id)


@router.get("/annotations/{annotation_id}/history", tags=["annotations"])
def history(annotation_id: int, connection: Db) -> list[ReviewEvent]:
    fetch_annotation(connection, annotation_id)  # 404 rather than an empty history
    return review.get_history(connection, annotation_id)


@router.post("/annotations", tags=["review"], status_code=201)
def create(body: CreateAnnotationRequest, account: Staff, connection: Db) -> ReviewResult:
    return ReviewResult(*review.create_annotation(
        connection, video_id=body.video_id, label_id=body.label_id,
        start_frame=body.start_frame, end_frame=body.end_frame, person_id=body.person_id,
        clip_id=body.clip_id, note=body.note, reviewer_id=account.username))


@router.post("/annotations/{annotation_id}/accept", tags=["review"])
def accept(annotation_id: int, body: NoteRequest, account: Staff, connection: Db) -> ReviewResult:
    return ReviewResult(*review.accept(connection, annotation_id, reviewer_id=account.username,
                                       note=body.note))


@router.post("/annotations/{annotation_id}/reject", tags=["review"])
def reject(annotation_id: int, body: NoteRequest, account: Staff, connection: Db) -> ReviewResult:
    return ReviewResult(*review.reject(connection, annotation_id, reviewer_id=account.username,
                                       note=body.note))


@router.post("/annotations/{annotation_id}/defer", tags=["review"])
def defer(annotation_id: int, body: NoteRequest, account: Staff, connection: Db) -> ReviewResult:
    return ReviewResult(*review.defer(connection, annotation_id, reviewer_id=account.username,
                                      note=body.note))


@router.post("/annotations/{annotation_id}/edit", tags=["review"])
def edit(annotation_id: int, body: EditRequest, account: Staff, connection: Db) -> ReviewResult:
    changes = AnnotationChanges(
        label_id=body.label_id, start_frame=body.start_frame, end_frame=body.end_frame,
        person_id=body.person_id if "person_id" in body.model_fields_set else UNSET)
    return ReviewResult(*review.edit(connection, annotation_id, changes,
                                     reviewer_id=account.username, note=body.note))


# --- Clips, labels, exports --------------------------------------------------------------

@router.get("/person-clips", tags=["clips"])
def person_clips(connection: Db, video_id: int | None = None, person_id: str | None = None,
                 review_status: Literal["UNREVIEWED", "ACCEPTED", "EDITED", "DEFERRED"] | None = None,
                 search: Annotated[str | None, Query(max_length=200)] = None,
                 limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
                 offset: Annotated[int, Query(ge=0)] = 0) -> list[PersonClip]:
    return stored_analysis.list_person_clips(connection, video_id=video_id, person_id=person_id,
                                           review_status=review_status, search=search, limit=limit, offset=offset)


@router.get("/processing", tags=["videos"])
def processing(connection: Db) -> list[VideoProgress]:
    return stored_analysis.processing_progress(connection)


@router.get("/activity-counts", tags=["clips"])
def activity_counts(connection: Db) -> list[ActivityCount]:
    return stored_analysis.activity_counts(connection)


@router.get("/person-clips/status-counts", tags=["clips"])
def person_clip_status_counts(connection: Db, search: Annotated[str | None, Query(max_length=200)] = None) -> dict[str, int]:
    return stored_analysis.person_clip_status_counts(connection, search=search)


@router.get("/person-clips/{clip_id}", tags=["clips"])
def person_clip(clip_id: int, connection: Db) -> PersonClip:
    return stored_analysis.get_person_clip(connection, clip_id)


@router.get("/person-clips/{clip_id}/thumbnail", tags=["clips"], response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}}})
def person_clip_thumbnail(clip_id: int, request: Request, connection: Db) -> Response:
    clip = stored_analysis.get_person_clip(connection, clip_id)
    path = catalog.video_file(connection, clip.video_id, request.app.state.video_dir)
    # no-store keeps participant frames out of the browser's disk cache.
    return Response(frame_jpeg(path, clip.start_seconds), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.get("/person-clips/{clip_id}/summary", tags=["clips"])
def person_clip_summary(clip_id: int, connection: Db) -> StoredClipSummary:
    return stored_analysis.person_clip_summary(connection, clip_id)


@router.post("/person-clips/{clip_id}/accept", tags=["review"])
def accept_person_clip(clip_id: int, account: Staff, connection: Db) -> PersonClip:
    corrections.review_clip(connection, clip_id, "ACCEPT", reviewer_id=account.username)
    return stored_analysis.get_person_clip(connection, clip_id)


@router.post("/person-clips/{clip_id}/defer", tags=["review"])
def defer_person_clip(clip_id: int, account: Staff, connection: Db) -> PersonClip:
    corrections.review_clip(connection, clip_id, "DEFER", reviewer_id=account.username)
    return stored_analysis.get_person_clip(connection, clip_id)


@router.post("/person-clips/{clip_id}/edit", tags=["review"])
def edit_person_clip(clip_id: int, body: ClipEditRequest, account: Staff, connection: Db) -> PersonClip:
    scores = None
    if body.positive_score is not None and body.neutral_score is not None and body.negative_score is not None:
        scores = (body.positive_score, body.neutral_score, body.negative_score)
    elif {body.positive_score, body.neutral_score, body.negative_score} != {None}:
        raise DataError("Give all three visible-affect scores, or none")
    corrections.review_clip(connection, clip_id, "EDIT", reviewer_id=account.username,
                            activity_label=body.activity_label, scores=scores,
                            create_activity_label=body.create_activity_label)
    return stored_analysis.get_person_clip(connection, clip_id)


@router.get("/exports/database/{dataset}", tags=["exports"])
def database_export(dataset: Literal["clips", "activity", "engagement", "activity-history", "engagement-history",
                                     "clip-review-history"],
                    connection: Db, format: Format) -> Response:
    out = io.StringIO()
    stored_analysis.export_database(connection, dataset, out, format)
    return _attachment(out.getvalue(), dataset, format)


@router.get("/clips", tags=["clips"])
def clips(connection: Db, video_id: int | None = None, person_id: str | None = None,
          order: Literal["time", "priority"] = "time",
          limit: Annotated[int | None, Query(ge=1, le=1000)] = None) -> list[ReviewClip]:
    return list_clips(connection, video_id=video_id, person_id=person_id, order=order,
                      limit=limit)


@router.get("/clips/{clip_id}", tags=["clips"])
def clip(clip_id: int, connection: Db) -> ReviewClip:
    return get_clip(connection, clip_id)


@router.get("/imports", tags=["imports"])
def imports(connection: Db) -> list[ImportRun]:
    """Successful pipeline-output imports, newest first."""
    return list_import_runs(connection)


@router.get("/labels", tags=["labels"])
def labels(connection: Db, category: LabelCategory | None = None,
           include_inactive: bool = False) -> list[Label]:
    return list_labels(connection, category=category, include_inactive=include_inactive)


def _attachment(text: str, name: str, fmt: str) -> Response:
    return Response(text, media_type="text/csv" if fmt == "csv" else "application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


@router.get("/exports/annotations", tags=["exports"])
def export_annotations(connection: Db, format: Format,
                       include_rejected: bool = False) -> Response:
    out = io.StringIO()
    exports.export_annotations(connection, out, format, include_rejected=include_rejected)
    return _attachment(out.getvalue(), "annotations", format)


@router.get("/exports/history", tags=["exports"])
def export_history(connection: Db, format: Format) -> Response:
    out = io.StringIO()
    exports.export_history(connection, out, format)
    return _attachment(out.getvalue(), "review-history", format)
