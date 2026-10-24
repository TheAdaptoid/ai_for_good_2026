import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.csv_input import discover_inputs  # noqa: E402
from analysis_db.ingestion import ingest_files  # noqa: E402
from analysis_db.paths import DEFAULT_DB, DEFAULT_VIDEO_DIR  # noqa: E402
from analysis_db.storage import connect_database, table_counts  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest CSV/TSV detection files into the six-table analysis"
                    " database with per-file transactional rollback.")
    parser.add_argument("--input", required=True, type=Path,
                        help="CSV/TSV file or directory of CSV/TSV files")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="existing database file (default: %(default)s);"
                             " run scripts/init_db.py first")
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR,
                        help="directory containing referenced video files"
                             " (default: %(default)s)")
    return parser


def report_result(result) -> None:
    name = result.source.name
    if result.committed:
        print(f"{name}: committed; rows={result.rows_read}"
              f" inserted={result.inserted['FaceDetection']}"
              f" skipped={result.skipped['FaceDetection']}"
              f" rejected={result.rejected_rows}")
        for table, count in result.inserted.items():
            print(f"  {table}: inserted={count} skipped={result.skipped[table]}")
    else:
        print(f"{name}: rolled back; rows_read={result.rows_read}"
              f" rejected={result.rejected_rows}; stopped at first error")
    error = result.error
    if error is not None:
        print(str(error), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selected, ignored = discover_inputs(args.input)
    except (DataError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for entry in ignored:
        print(f"ignored (not CSV/TSV): {entry.name}")
    try:
        connection = connect_database(args.db, must_exist=True)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    failures = 0
    try:
        try:
            results = ingest_files(connection, selected, args.video_dir)
        except (DataError, OSError, sqlite3.Error) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for result in results:
            if not result.committed:
                failures += 1
            report_result(result)
        counts = table_counts(connection)
        print("Table counts:")
        for table, count in counts.items():
            print(f"  {table}: {count}")
    finally:
        connection.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
