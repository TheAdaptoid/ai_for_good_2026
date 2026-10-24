"""Explicit acquisition of the pinned X-CLIP checkpoint for offline use.

Run from the backend directory: ``uv run --locked python -m
activity_classification.download_model [--cache-dir PATH]``. Importing this
module downloads nothing and changes no environment settings; ``main``
switches the runtime into online acquisition mode only on invocation.
"""

import argparse
from pathlib import Path

from activity_classification.runtime import (
    DEFAULT_CACHE_DIR,
    MODEL_ID,
    MODEL_REVISION,
    configure_runtime,
)

ALLOW_PATTERNS = ["*.json", "merges.txt", "model.safetensors"]


def main(argv: list[str] | None = None) -> None:
    """Download the pinned checkpoint assets, with tracking disabled."""
    parser = argparse.ArgumentParser(
        prog="python -m activity_classification.download_model",
        description=(
            "Download the pinned X-CLIP checkpoint assets into the backend cache "
            "for fully offline inference."
        ),
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=None,
        help=(
            "Hub cache directory for the checkpoint (default: "
            f"{DEFAULT_CACHE_DIR}, derived from the backend package location)."
        ),
    )
    args = parser.parse_args(argv)
    cache_dir = DEFAULT_CACHE_DIR if args.cache_dir is None else args.cache_dir

    # Acquisition is online only for this explicit invocation; telemetry stays off.
    configure_runtime(offline=False, cache_dir=cache_dir)

    from huggingface_hub import snapshot_download

    snapshot = snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=cache_dir,
        allow_patterns=ALLOW_PATTERNS,
    )
    print(f"Pinned revision: {MODEL_REVISION}")
    print(f"Snapshot: {snapshot}")


if __name__ == "__main__":
    main()
