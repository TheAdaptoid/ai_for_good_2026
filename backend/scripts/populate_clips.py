"""Finalize immutable person clips after all detection imports have completed."""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.clips import generate_clips, populate_clips  # noqa: E402
from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.paths import DEFAULT_DB  # noqa: E402
from analysis_db.storage import connect_database  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--video-id", type=int)
    parser.add_argument("--persistence-frames", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        with closing(connect_database(args.db, must_exist=True)) as c:
            if args.video_id is None:
                results = populate_clips(c, persistence_frames=args.persistence_frames)
            else:
                results = {args.video_id: generate_clips(
                    c, args.video_id, persistence_frames=args.persistence_frames)}
        for video_id, ids in results.items():
            print(f"Video {video_id}: {len(ids)} finalized clips")
    except (DataError, ValueError, LookupError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
