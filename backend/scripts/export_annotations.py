import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.exports import export_annotations, export_history  # noqa: E402
from analysis_db.paths import DEFAULT_DB  # noqa: E402
from analysis_db.storage import connect_database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export current annotations (rejected ones excluded by default),"
                    " or the review history with --history, as CSV or JSON.")
    parser.add_argument("--format", required=True, choices=("csv", "json"))
    parser.add_argument("--output", required=True, type=Path, help="file to write")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="existing database file (default: %(default)s)")
    parser.add_argument("--include-rejected", action="store_true",
                        help="also export REJECTED annotations")
    parser.add_argument("--history", action="store_true",
                        help="export the append-only review history instead of annotations")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        connection = connect_database(args.db, must_exist=True)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    # Write beside the destination, then rename, so a failed export never leaves a partial file.
    temporary = None
    try:
        handle, temporary = tempfile.mkstemp(dir=args.output.parent,
                                             prefix=f".{args.output.name}.", suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            if args.history:
                export_history(connection, out, args.format)
            else:
                export_annotations(connection, out, args.format,
                                   include_rejected=args.include_rejected)
        os.replace(temporary, args.output)
        temporary = None
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
