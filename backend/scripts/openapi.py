"""Print the service's OpenAPI schema (the frontend's type source) without touching real data."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.paths import DEFAULT_VIDEO_DIR  # noqa: E402
from analysis_db.storage import initialize_database  # noqa: E402
from api.app import create_app  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "schema.sqlite"
        initialize_database(db_path)
        schema = create_app(db_path, DEFAULT_VIDEO_DIR).openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
