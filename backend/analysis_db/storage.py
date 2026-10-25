import sqlite3
from pathlib import Path

from analysis_db.contracts import (
    DataError, DetectionRow, REVIEW_TABLES, STAFF_TABLES, TABLES, VideoMetadata,
)
from analysis_db.paths import SCHEMA_PATH


def connect_database(path: Path, *, must_exist: bool = False,
                     read_only: bool = False) -> sqlite3.Connection:
    """Open a connection with foreign keys ON and explicit transaction control.

    ``must_exist=True`` uses a ``mode=rw`` URI so a missing file raises instead
    of being created. ``read_only=True`` uses ``mode=ro`` and rejects writes;
    it also requires an existing database.
    """
    resolved = Path(path).resolve()
    if must_exist or read_only:
        mode = "ro" if read_only else "rw"
        uri = resolved.as_uri() + f"?mode={mode}"
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        connection = sqlite3.connect(resolved, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
        connection.close()
        raise DataError(f"cannot enable foreign key enforcement for {resolved}")
    return connection


def initialize_database(path: Path) -> dict[str, int]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_database(path)
    try:
        try:
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        except sqlite3.Error:
            connection.rollback()
            raise
        return table_counts(connection)
    finally:
        connection.close()


def assert_schema(connection: sqlite3.Connection,
                  tables: tuple[str, ...] = TABLES) -> None:
    present = {
        name for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing = [table for table in tables if table not in present]
    if missing:
        raise DataError(
            "database is missing tables [" + ", ".join(missing) + "]; "
            "call initialize_database() before ingesting")


def ensure_video(connection: sqlite3.Connection, row: DetectionRow, file_path: str,
                 metadata: VideoMetadata) -> tuple[int, bool]:
    metadata_values = (metadata.created_at, metadata.duration_seconds,
                       metadata.fps, metadata.width, metadata.height)
    existing = connection.execute(
        "SELECT video_id, title, filename, file_path, created_at,"
        " duration_seconds, fps, width, height FROM Video"
        " WHERE filename = ? OR file_path = ?",
        (row.video_filename, file_path),
    ).fetchone()
    if existing is not None:
        expected = (row.video_title, row.video_filename, file_path, *metadata_values)
        stored = existing[1:]
        if stored != expected:
            fields = [name for name, got, wanted in zip(
                ("title", "filename", "file_path", "created_at", "duration_seconds",
                 "fps", "width", "height"), stored, expected) if got != wanted]
            raise DataError(
                f"conflicting Video for {row.video_filename!r}:"
                f" mismatched {', '.join(fields)}")
        return existing[0], False
    cursor = connection.execute(
        "INSERT INTO Video (title, filename, file_path, created_at,"
        " duration_seconds, fps, width, height) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (row.video_title, row.video_filename, file_path, *metadata_values),
    )
    return cursor.lastrowid, True


def ensure_person(connection: sqlite3.Connection, person_id: str) -> bool:
    existing = connection.execute(
        "SELECT 1 FROM Person WHERE person_id = ?", (person_id,),
    ).fetchone()
    if existing is not None:
        return False
    connection.execute("INSERT INTO Person (person_id) VALUES (?)", (person_id,))
    return True


def ensure_frame(connection: sqlite3.Connection, row: DetectionRow,
                 video_id: int) -> bool:
    existing = connection.execute(
        "SELECT frame_id, video_id, frame_number, source_time_seconds FROM Frame"
        " WHERE frame_id = ? OR (video_id = ? AND frame_number = ?)",
        (row.frame_id, video_id, row.frame_number),
    ).fetchall()
    if existing:
        if len(existing) > 1:
            raise DataError(
                f"conflicting Frame: {row.frame_id!r} and (video {video_id},"
                f" frame {row.frame_number}) identify two different rows")
        frame_id, stored_video, stored_number, stored_time = existing[0]
        mismatches = []
        if frame_id != row.frame_id:
            mismatches.append("frame_id")
        if stored_video != video_id:
            mismatches.append("video_id")
        if stored_number != row.frame_number:
            mismatches.append("frame_number")
        if stored_time != row.source_time_seconds:
            mismatches.append("source_time_seconds")
        if mismatches:
            raise DataError(
                f"conflicting Frame for {row.frame_id!r}:"
                f" mismatched {', '.join(mismatches)}")
        return False
    connection.execute(
        "INSERT INTO Frame (frame_id, video_id, frame_number, source_time_seconds)"
        " VALUES (?, ?, ?, ?)",
        (row.frame_id, video_id, row.frame_number, row.source_time_seconds),
    )
    return True


def ensure_detection(connection: sqlite3.Connection,
                     row: DetectionRow) -> tuple[int, bool]:
    expected = (row.x1, row.y1, row.x2, row.y2, row.det_score)
    existing = connection.execute(
        "SELECT detection_id, x1, y1, x2, y2, det_score FROM FaceDetection"
        " WHERE frame_id = ? AND person_id = ?",
        (row.frame_id, row.person_id),
    ).fetchone()
    if existing is not None:
        if existing[1:] != expected:
            raise DataError(
                f"conflicting FaceDetection for {row.frame_id!r},"
                f" {row.person_id!r}")
        return existing[0], False
    cursor = connection.execute(
        "INSERT INTO FaceDetection (person_id, frame_id, x1, y1, x2, y2, det_score)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row.person_id, row.frame_id, *expected),
    )
    return cursor.lastrowid, True


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        cursor = connection.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cursor.fetchone()[0]
    return counts


def review_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in REVIEW_TABLES}


def staff_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in STAFF_TABLES}
