import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.activity_schema import migrate_activity
from analysis_db.contracts import DataError
from analysis_db.paths import DEFAULT_DB
from analysis_db.storage import connect_database


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migrate empty legacy Activity to frame-linked results.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB.with_name("analysis.local.sqlite"))
    args = parser.parse_args(argv)
    try:
        with closing(connect_database(args.db, must_exist=True)) as connection:
            changed = migrate_activity(connection)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("Activity migrated" if changed else "Activity already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
