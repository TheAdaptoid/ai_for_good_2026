"""Import pipeline output files (format ``tpa-review-import/1``) through the Spec 001 protected
upsert. A whole file is validated and stored in one transaction, or not at all, and each
successful import appends an ImportRun audit row.
"""

import json
import sqlite3
from dataclasses import asdict, fields
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from analysis_db.annotations import _clip_is_protected, _import_video, _now
from analysis_db.contracts import (
    IMPORT_TABLES, REVIEW_TABLES, AnnotationInput, ClipInput, DataError, ImportResult, ImportRun,
    LabelCategory, ModelRef,
)
from analysis_db.storage import assert_schema

FORMAT = "tpa-review-import/1"
Text = Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, pattern=r"\S")]
Frame = Annotated[int, Field(ge=0, strict=True)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelEntry(_Model):
    name: Text
    revision: str | None = None


class PipelineInfo(_Model):
    name: Text
    version: Text
    generated_at: datetime | None = None
    models: tuple[ModelEntry, ...] = ()
    # Run configuration (flat scalars). Kept in the file, which ImportRun.input_sha256 identifies.
    parameters: dict[str, str | int | float | bool | None] = {}


class PriorityEntry(_Model):
    """Review priority: an unbounded ranking heuristic, never a confidence or probability."""
    score: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    method: Text


class ClipEntry(_Model):
    key: Text
    start_frame: Frame
    end_frame: Frame
    participants: tuple[Text, ...] = ()
    priority: PriorityEntry | None = None

    @model_validator(mode="after")
    def _check(self) -> "ClipEntry":
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        if len(set(self.participants)) != len(self.participants):
            raise ValueError("participants must not repeat")
        return self


class LabelRef(_Model):
    name: Text
    category: LabelCategory


class AnnotationEntry(_Model):
    key: Text
    label: LabelRef
    start_frame: Frame | None = None
    end_frame: Frame | None = None
    person_id: Text | None = None
    clip_key: Text | None = None
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def _check(self) -> "AnnotationEntry":
        if (self.start_frame is None) != (self.end_frame is None):
            raise ValueError("give both start_frame and end_frame, or neither")
        if self.start_frame is None and (self.clip_key is None or self.person_id is not None):
            raise ValueError("a span is required unless this is a clip-level annotation"
                             " (clip_key given, no person_id)")
        if self.start_frame is not None and self.end_frame < self.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        return self


class VideoEntry(_Model):
    filename: Text
    clips: tuple[ClipEntry, ...] = ()
    annotations: tuple[AnnotationEntry, ...] = ()


class ImportFile(_Model):
    format: Literal["tpa-review-import/1"]
    pipeline: PipelineInfo
    videos: tuple[VideoEntry, ...]

    @model_validator(mode="after")
    def _unique(self) -> "ImportFile":
        filenames = [video.filename for video in self.videos]
        if len(set(filenames)) != len(filenames):
            raise ValueError("each video filename may appear only once")
        for kind, keys in (("clip", [c.key for v in self.videos for c in v.clips]),
                           ("annotation", [a.key for v in self.videos for a in v.annotations])):
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            if duplicates:
                raise ValueError(f"duplicate {kind} keys: {', '.join(duplicates[:5])}")
        return self

    def to_json(self) -> str:
        """Byte-stable serialization (sorted keys), so identical inputs give identical files."""
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def parse_import_file(text: str) -> ImportFile:
    try:
        return ImportFile.model_validate_json(text)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'file'}: {error['msg']}"
            for error in exc.errors()[:10])
        raise DataError(f"invalid import file ({FORMAT}): {problems}") from exc


def _resolve(connection: sqlite3.Connection, parsed: ImportFile
             ) -> list[tuple[int, list[ClipInput], list[AnnotationInput]]]:
    videos = dict(connection.execute("SELECT filename, video_id FROM Video"))
    # Inactive labels resolve too: Spec 001 refuses them only for rows that are not protected.
    labels = {(category, name.casefold()): label_id for label_id, category, name in
              connection.execute("SELECT label_id, category, name FROM Label")}
    people = {person for (person,) in connection.execute("SELECT person_id FROM Person")}
    resolved = []
    for v, video in enumerate(parsed.videos):
        where = f"videos[{v}]"
        if video.filename not in videos:
            raise DataError(f"{where}: unknown video {video.filename!r}")
        spans = {}
        clips = []
        for c, clip in enumerate(video.clips):
            unknown = [p for p in clip.participants if p not in people]
            if unknown:
                raise DataError(f"{where}.clips[{c}]: unknown participants {unknown}")
            spans[clip.key] = (clip.start_frame, clip.end_frame)
            clips.append(ClipInput(
                clip.key, clip.start_frame, clip.end_frame, clip.participants,
                clip.priority.score if clip.priority else None,
                clip.priority.method if clip.priority else None))
        annotations = []
        for a, item in enumerate(video.annotations):
            here = f"{where}.annotations[{a}]"
            label_id = labels.get((item.label.category.value, item.label.name.casefold()))
            if label_id is None:
                raise DataError(f"{here}: unknown {item.label.category.value} label"
                                f" {item.label.name!r}")
            if item.person_id is not None and item.person_id not in people:
                raise DataError(f"{here}: unknown participant {item.person_id!r}")
            start, end = item.start_frame, item.end_frame
            if start is None:
                stored = connection.execute(
                    "SELECT clip_id, start_frame, end_frame FROM ReviewClip WHERE import_key = ?",
                    (item.clip_key,)).fetchone()
                # A protected clip keeps its stored span, so its clip-level annotations must too.
                if stored is not None and (item.clip_key not in spans
                                           or _clip_is_protected(connection, stored[0])):
                    span = stored[1:]
                else:
                    span = spans.get(item.clip_key)
                if span is None:
                    raise DataError(f"{here}: unknown clip_key {item.clip_key!r}")
                start, end = span
            annotations.append(AnnotationInput(item.key, label_id, start, end, item.confidence,
                                               item.person_id, item.clip_key))
        resolved.append((videos[video.filename], clips, annotations))
    return resolved


def _total(results: list[ImportResult]) -> ImportResult:
    return ImportResult(*(sum(getattr(r, f.name) for r in results) for f in fields(ImportResult)))


def import_file(connection: sqlite3.Connection, parsed: ImportFile, *, source_name: str,
                sha256: str) -> ImportRun:
    """Store every video of the file in one transaction and record the run; all or nothing."""
    if connection.in_transaction:
        raise DataError("import requires an idle database connection")
    assert_schema(connection, tables=REVIEW_TABLES + IMPORT_TABLES)
    connection.execute("BEGIN IMMEDIATE")
    try:
        now = _now()
        results = []
        for v, (video_id, clips, annotations) in enumerate(_resolve(connection, parsed)):
            try:
                results.append(_import_video(connection, video_id, clips, annotations, now))
            except (DataError, LookupError) as exc:
                raise DataError(f"videos[{v}] ({parsed.videos[v].filename}): {exc}") from exc
        counts = _total(results)
        info = parsed.pipeline
        run_id = connection.execute(
            "INSERT INTO ImportRun (pipeline_name, pipeline_version, models_json, generated_at,"
            " imported_at, source_name, input_sha256, counts_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (info.name, info.version, json.dumps([m.model_dump() for m in info.models]),
             info.generated_at.isoformat() if info.generated_at else None, now, source_name,
             sha256, json.dumps(asdict(counts)))).lastrowid
        connection.commit()
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise DataError(f"invalid machine output: {exc}") from exc
    except BaseException:
        connection.rollback()
        raise
    return list_import_runs(connection, run_id=run_id)[0]


def list_import_runs(connection: sqlite3.Connection, *, run_id: int | None = None) -> list[ImportRun]:
    """Successful imports, newest first."""
    assert_schema(connection, tables=IMPORT_TABLES)
    where, params = ("WHERE run_id = ?", (run_id,)) if run_id is not None else ("", ())
    rows = connection.execute(
        "SELECT run_id, pipeline_name, pipeline_version, models_json, generated_at, imported_at,"
        f" source_name, input_sha256, counts_json FROM ImportRun {where} ORDER BY run_id DESC",
        params).fetchall()
    return [ImportRun(run, name, version,
                      tuple(ModelRef(m["name"], m.get("revision")) for m in json.loads(models)),
                      generated, imported, source, sha, ImportResult(**json.loads(counts)))
            for run, name, version, models, generated, imported, source, sha, counts in rows]
