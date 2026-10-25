import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.paths import DEFAULT_DB, DEFAULT_VIDEO_DIR  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the local TPA review service.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default: %(default)s; anything else exposes the"
                             " service beyond this machine)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("TPA_DB", DEFAULT_DB)),
                        help="working database (default: $TPA_DB or %(default)s)")
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR,
                        help="only files inside this directory are served"
                             " (default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error(f"database {args.db} does not exist; omit --db to use {DEFAULT_DB}")
    import uvicorn

    from api.app import create_app

    uvicorn.run(create_app(args.db, args.video_dir), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
