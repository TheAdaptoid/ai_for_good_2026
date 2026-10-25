import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.paths import DEFAULT_DB  # noqa: E402
from analysis_db.storage import (  # noqa: E402
    connect_database, initialize_database, review_table_counts, staff_table_counts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the analysis database and add review, audit, and clip tables."
                    " Initialization is idempotent and preserves existing data.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="database file to initialize (default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        counts = initialize_database(args.db)
        connection = connect_database(args.db, must_exist=True)
        try:
            counts |= review_table_counts(connection) | staff_table_counts(connection)
        finally:
            connection.close()
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Initialized {args.db}")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
