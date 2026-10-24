import sqlite3
from collections.abc import Iterable
from pathlib import Path

from analysis_db.contracts import (
    CsvImportError,
    DataError,
    DetectionRow,
    FileResult,
    VideoMetadata,
    zero_counts,
)
from analysis_db.csv_input import iter_rows
from analysis_db.paths import REPOSITORY_ROOT, repository_relative
from analysis_db.storage import (
    assert_schema,
    ensure_detection,
    ensure_frame,
    ensure_person,
    ensure_video,
)
from analysis_db.video_metadata import probe_video, resolve_video


def ingest_file(connection: sqlite3.Connection, source: Path, video_dir: Path, *,
                repository_root: Path,
                metadata_cache: dict[Path, VideoMetadata]) -> FileResult:
    source = Path(source)
    result = FileResult(source)
    current_line = None
    if connection.in_transaction:
        raise DataError("ingestion requires an idle database connection")
    started = False
    try:
        connection.execute("BEGIN")
        started = True
        seen_videos: dict[str, tuple[str, str, VideoMetadata, int]] = {}
        seen_persons: set[str] = set()
        seen_frames: dict[str, tuple[int, int, float]] = {}
        seen_detections: dict[tuple[str, str], tuple[float, float, float, float, float]] = {}

        def count_entity(table: str, inserted: bool) -> None:
            (result.inserted if inserted else result.skipped)[table] += 1

        def store_row(row: DetectionRow) -> None:
            if row.video_filename not in seen_videos:
                path = resolve_video(row.video_filename, video_dir)
                stored_path = repository_relative(path, root=repository_root)
                if path not in metadata_cache:
                    metadata_cache[path] = probe_video(path)
                metadata = metadata_cache[path]
                video_id, inserted = ensure_video(connection, row, stored_path, metadata)
                count_entity("Video", inserted)
                seen_videos[row.video_filename] = (row.video_title, stored_path,
                                                   metadata, video_id)
            else:
                title, stored_path, metadata, video_id = seen_videos[row.video_filename]
                if row.video_title != title:
                    raise DataError(
                        f"conflicting Video.title for {row.video_filename!r}")

            if row.person_id not in seen_persons:
                count_entity("Person", ensure_person(connection, row.person_id))
                seen_persons.add(row.person_id)

            frame_signature = (video_id, row.frame_number, row.source_time_seconds)
            if row.frame_id in seen_frames:
                if seen_frames[row.frame_id] != frame_signature:
                    raise DataError(f"conflicting Frame for {row.frame_id!r}")
            else:
                count_entity("Frame", ensure_frame(connection, row, video_id))
                seen_frames[row.frame_id] = frame_signature

            key = (row.frame_id, row.person_id)
            signature = (row.x1, row.y1, row.x2, row.y2, row.det_score)
            if key in seen_detections:
                if seen_detections[key] != signature:
                    raise DataError(f"conflicting FaceDetection for {key!r}")
                count_entity("FaceDetection", False)
            else:
                detection_id, inserted = ensure_detection(connection, row)
                count_entity("FaceDetection", inserted)
                seen_detections[key] = signature

        for row in iter_rows(source):
            result.rows_read += 1
            current_line = row.line_number
            store_row(row)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise DataError("foreign key validation failed")
        connection.commit()
        result.committed = True
    except (CsvImportError, DataError, sqlite3.Error, OSError) as exc:
        if started:
            connection.rollback()
        if isinstance(exc, CsvImportError):
            # iter_rows validates before yielding: its invalid data row was not
            # counted by the loop. Header errors have line 1 and add no data row.
            if exc.line_number is not None and exc.line_number > 1:
                result.rows_read += 1
            result.error = exc
        else:
            result.error = CsvImportError(source, current_line, str(exc))
        result.rejected_rows = result.rows_read
        result.inserted = zero_counts()
        result.skipped = zero_counts()
    finally:
        if started and connection.in_transaction:
            connection.rollback()
    return result


def ingest_files(connection: sqlite3.Connection, sources: Iterable[Path],
                 video_dir: Path, *,
                 repository_root: Path = REPOSITORY_ROOT) -> list[FileResult]:
    if connection.in_transaction:
        raise DataError("ingestion requires an idle database connection")
    assert_schema(connection)
    repository_relative(video_dir, root=repository_root)
    cache: dict[Path, VideoMetadata] = {}
    return [ingest_file(connection, source, video_dir,
                        repository_root=repository_root, metadata_cache=cache)
            for source in sources]
