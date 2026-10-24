"""Backend-local runtime configuration and pinned-checkpoint constants."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
HF_HOME = BACKEND_DIR / ".cache" / "huggingface"
DEFAULT_CACHE_DIR = HF_HOME / "hub"
MODEL_ID = "microsoft/xclip-base-patch16-zero-shot"
MODEL_REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"
DEFAULT_PROMPT_TEMPLATE = "A video of people {activity}."
ACQUISITION_COMMAND = "uv run --locked python -m activity_classification.download_model"


def configure_runtime(*, offline: bool, cache_dir: Path) -> None:
    """Set offline and telemetry flags before lazy Hugging Face/Transformers imports.

    Callers pass either the backend hub cache or an explicit acquisition cache;
    the resulting HF_HOME derives from that choice, never from sibling caches.
    """
    cache_dir = Path(cache_dir)
    os.environ.update({
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "HF_HUB_OFFLINE": "1" if offline else "0",
        "TRANSFORMERS_OFFLINE": "1" if offline else "0",
        "WANDB_DISABLED": "true",
        "WANDB_MODE": "disabled",
        "COMET_MODE": "DISABLED",
        "TOKENIZERS_PARALLELISM": "false",
        "HF_HOME": str(cache_dir.parent),
        "HF_HUB_CACHE": str(cache_dir),
    })
