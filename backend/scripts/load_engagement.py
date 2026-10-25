import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.engagement_table import replace_engagement  # noqa: E402
from analysis_db.paths import DEFAULT_DB  # noqa: E402
from analysis_db.storage import connect_database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomically replace the Engagement table with the face-expression"
                    " notebook's per-detection scores (detection_id, positive/neutral/negative).")
    parser.add_argument("--input", required=True, type=Path,
                        help="face_expression_observations_from_videos.csv")
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
        result = replace_engagement(connection, args.input)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}; database unchanged", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(f"Replaced Engagement in {args.db}")
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
