import csv
import re
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

from analysis_db.contracts import DataError
from analysis_db.csv_input import finite_number
from analysis_db.storage import assert_schema, table_counts

REQUIRED_COLUMNS = {
    "VIDEO": ("video_id", "filename"),
    "FRAME": ("frame_id", "video_id", "frame_number", "source_time_seconds"),
    "PERSON": ("person_id",),
    "FACE_DETECTION": ("detection_id", "person_id", "frame_id", "x1", "y1", "x2", "y2",
                       "det_score"),
}
# Children before parents so foreign keys hold after every statement. Video is kept.
CLEARED_TABLES = ("Activity", "Engagement", "FaceDetection", "Frame", "Person")


def _integer(values: Mapping[str, str], column: str) -> int:
    if not re.fullmatch(r"[0-9]+", values[column]):
        raise ValueError(f"{column} must be a nonnegative integer")
    return int(values[column])


def _text(values: Mapping[str, str], column: str) -> str:
    if not values[column].strip():
        raise ValueError(f"{column} must be nonempty")
    return values[column]


def read_table(path: Path, required: tuple[str, ...],
               parse: Callable[[Mapping[str, str]], tuple | None]) -> list[tuple]:
    """Parse every row of a CSV; rows for which parse returns None are skipped."""
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        missing = [c for c in required if c not in (reader.fieldnames or ())]
        if missing:
            raise DataError(f"{path}: missing required column(s): {', '.join(missing)}")
        rows = []
        try:
            for values in reader:
                row = parse(values)
                if row is not None:
                    rows.append(row)
        except (ValueError, KeyError, csv.Error) as exc:
            raise DataError(f"{path}:{reader.line_num}: {exc}") from exc
        return rows


def replace_identity_tables(connection: sqlite3.Connection,
                            directory: Path) -> dict[str, int]:
    """Replace Frame/Person/FaceDetection from schema-shaped CSVs; clear Activity/Engagement.

    Video rows are kept and matched by filename through VIDEO.csv. detection_id values are
    preserved because downstream handoffs join on them. All or nothing.
    """
    if connection.in_transaction:
        raise DataError("replacement requires an idle database connection")
    assert_schema(connection)
    stored = dict(connection.execute("SELECT filename, video_id FROM Video"))

    def video(values):
        filename = _text(values, "filename")
        if filename not in stored:
            raise ValueError(f"video {filename!r} is not in the Video table")
        return _integer(values, "video_id"), stored[filename]

    def table(name, parse):
        return read_table(Path(directory) / f"{name}.csv", REQUIRED_COLUMNS[name], parse)

    video_ids = dict(table("VIDEO", video))

    def frame(values):
        csv_video = _integer(values, "video_id")
        if csv_video not in video_ids:
            raise ValueError(f"video_id {csv_video} is not in VIDEO.csv")
        timestamp = finite_number(values, "source_time_seconds")
        return (_text(values, "frame_id"), video_ids[csv_video],
                _integer(values, "frame_number"), timestamp)

    def detection(values):
        return (_integer(values, "detection_id"), _text(values, "person_id"),
                _text(values, "frame_id"),
                *(finite_number(values, c) for c in ("x1", "y1", "x2", "y2", "det_score")))

    frames = table("FRAME", frame)
    persons = table("PERSON", lambda values: (_text(values, "person_id"),))
    detections = table("FACE_DETECTION", detection)

    connection.execute("BEGIN")
    try:
        for table in CLEARED_TABLES:
            connection.execute(f"DELETE FROM {table}")
        connection.executemany("INSERT INTO Person (person_id) VALUES (?)", persons)
        connection.executemany(
            "INSERT INTO Frame (frame_id, video_id, frame_number, source_time_seconds)"
            " VALUES (?, ?, ?, ?)", frames)
        connection.executemany(
            "INSERT INTO FaceDetection (detection_id, person_id, frame_id, x1, y1, x2, y2,"
            " det_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", detections)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise DataError("foreign key validation failed")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise DataError("database integrity check failed")
        counts = table_counts(connection)
        expected = {"Frame": len(frames), "Person": len(persons),
                    "FaceDetection": len(detections), "Activity": 0, "Engagement": 0}
        wrong = [t for t, n in expected.items() if counts[t] != n]
        if wrong:
            raise DataError(f"row counts differ from input for {', '.join(wrong)}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return counts
