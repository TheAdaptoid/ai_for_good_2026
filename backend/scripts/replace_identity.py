import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.identity_tables import replace_identity_tables  # noqa: E402
from analysis_db.paths import DEFAULT_DB  # noqa: E402
from analysis_db.storage import connect_database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomically replace Frame, Person, and FaceDetection with an identity"
                    " run's schema-shaped CSVs; clears Activity and Engagement, keeps Video.")
    parser.add_argument("--tables", required=True, type=Path,
                        help="directory containing VIDEO.csv, FRAME.csv, PERSON.csv,"
                             " FACE_DETECTION.csv")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="existing database file (default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        connection = connect_database(args.db, must_exist=True)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        counts = replace_identity_tables(connection, args.tables)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}; database unchanged", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(f"Replaced identity tables in {args.db}")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
