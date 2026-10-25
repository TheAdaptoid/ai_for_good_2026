import argparse
import hashlib
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.paths import WORKING_DB  # noqa: E402
from analysis_db.pipeline_import import FORMAT, import_file, parse_import_file  # noqa: E402
from analysis_db.storage import connect_database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Import a pipeline output file ({FORMAT}). The whole file is stored or"
                    " nothing is; reviewed annotations and their clips are never changed, and"
                    " nothing is deleted.")
    parser.add_argument("--input", required=True, type=Path, help="pipeline output JSON")
    parser.add_argument("--db", type=Path, default=WORKING_DB,
                        help="existing database file (default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = args.input.read_bytes()
        parsed = parse_import_file(data.decode("utf-8"))
        connection = connect_database(args.db, must_exist=True)
    except (DataError, OSError, UnicodeDecodeError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        run = import_file(connection, parsed, source_name=args.input.name,
                          sha256=hashlib.sha256(data).hexdigest())
    except (DataError, LookupError, sqlite3.Error) as exc:
        print(f"error: nothing imported: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(f"Imported {args.input.name} as run {run.run_id}"
          f" ({run.pipeline_name} {run.pipeline_version})")
    for name, value in asdict(run.counts).items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
