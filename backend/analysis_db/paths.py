from pathlib import Path
from .contracts import DataError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPOSITORY_ROOT / "data" / "analysis.sqlite"
DEFAULT_VIDEO_DIR = REPOSITORY_ROOT / "data" / "videos"
SCHEMA_PATH = REPOSITORY_ROOT / "backend" / "db" / "schema.sql"


def repository_relative(path: Path, *, root: Path = REPOSITORY_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DataError(f"video path must be inside repository: {path}") from exc
