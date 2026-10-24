import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.paths import DEFAULT_DB  # noqa: E402
from analysis_db.storage import initialize_database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create (or finish creating) the six-table analysis database."
                    " Creation is idempotent; an existing schema is left unchanged.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="database file to initialize (default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        counts = initialize_database(args.db)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Initialized {args.db}")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
