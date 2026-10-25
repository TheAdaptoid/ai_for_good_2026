import csv
import json
import sqlite3
from dataclasses import asdict
from enum import StrEnum
from typing import TextIO

from analysis_db.annotations import list_annotations
from analysis_db.contracts import REVIEW_TABLES
from analysis_db.review import _EVENT_COLUMNS, _event
from analysis_db.storage import assert_schema

ANNOTATION_COLUMNS = (
    "annotation_id", "video_id", "clip_id", "person_id", "label_id", "label_name",
    "label_category", "start_frame", "end_frame", "start_seconds", "end_seconds", "confidence",
    "source", "review_status", "updated_at",
)


def _write(records: list[dict], columns: tuple[str, ...], out: TextIO, fmt: str) -> None:
    if fmt == "json":
        json.dump(records, out, indent=2)
    elif fmt == "csv":
        writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: "" if v is None else v for k, v in r.items()} for r in records)
    else:
        raise ValueError(f"unsupported export format: {fmt!r}")


def export_annotations(connection: sqlite3.Connection, out: TextIO, fmt: str, *,
                       include_rejected: bool = False, **filters) -> None:
    """Write current annotations as CSV or JSON. No review-priority score (it belongs to clips)."""
    if fmt not in ("csv", "json"):
        raise ValueError(f"unsupported export format: {fmt!r}")
    records = []
    for annotation in list_annotations(connection, include_rejected=include_rejected, **filters):
        values = asdict(annotation)
        for key in ("start_seconds", "end_seconds"):
            if values[key] is not None:
                values[key] = round(values[key], 3)
        for key in ("label_category", "source", "review_status"):
            values[key] = str(values[key])
        records.append({column: values[column] for column in ANNOTATION_COLUMNS})
    _write(records, ANNOTATION_COLUMNS, out, fmt)


def export_history(connection: sqlite3.Connection, out: TextIO, fmt: str) -> None:
    """Write every review event, oldest first, as CSV or JSON."""
    if fmt not in ("csv", "json"):
        raise ValueError(f"unsupported export format: {fmt!r}")
    assert_schema(connection, tables=REVIEW_TABLES)
    rows = connection.execute(
        f"SELECT {', '.join(_EVENT_COLUMNS)} FROM ReviewEvent ORDER BY event_id").fetchall()
    records = [{k: str(v) if isinstance(v, StrEnum) else v
                for k, v in asdict(_event(row)).items()} for row in rows]
    _write(records, _EVENT_COLUMNS, out, fmt)
