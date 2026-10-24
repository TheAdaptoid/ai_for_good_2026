"""Explicit acquisition of the pinned X-CLIP checkpoint for offline use."""

import os
from pathlib import Path


MODEL_ID = "microsoft/xclip-base-patch16-zero-shot"
MODEL_REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"
PROJECT_DIR = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_DIR / ".cache" / "huggingface" / "hub"


def main() -> None:
    """Enable acquisition only when explicitly invoked, with tracking disabled."""
    os.environ.update({
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "HF_HUB_OFFLINE": "0",
        "TRANSFORMERS_OFFLINE": "0",
        "WANDB_DISABLED": "true",
        "WANDB_MODE": "disabled",
        "COMET_MODE": "DISABLED",
        "TOKENIZERS_PARALLELISM": "false",
        "HF_HOME": str(PROJECT_DIR / ".cache" / "huggingface"),
    })

    from huggingface_hub import snapshot_download

    snapshot = snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=CACHE_DIR,
        allow_patterns=["*.json", "merges.txt", "model.safetensors"],
    )
    print(f"Pinned revision: {MODEL_REVISION}")
    print(f"Snapshot: {snapshot}")


if __name__ == "__main__":
    main()
