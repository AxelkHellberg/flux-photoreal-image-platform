from __future__ import annotations

import os
from pathlib import Path

# RunPod has been unreliable with hf-xet-based snapshot reconstruction for this model.
# Set the environment before importing huggingface_hub so the library never enables xet.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

from huggingface_hub import snapshot_download


def main() -> int:
    hf_token = os.environ.get("HF_TOKEN")
    model_id = os.environ.get("FLUX_MODEL_ID", "black-forest-labs/FLUX.1-Krea-dev")
    model_cache_dir = os.environ.get("MODEL_CACHE_DIR")

    if not hf_token:
        raise SystemExit(
            "HF_TOKEN is required to download black-forest-labs/FLUX.1-Krea-dev. "
            "Accept the model terms and configure HF_TOKEN first."
        )
    if not model_cache_dir:
        raise SystemExit("MODEL_CACHE_DIR is required")

    local_dir = Path(model_cache_dir).expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    snapshot_download(
        repo_id=model_id,
        local_dir=str(local_dir),
        token=hf_token,
        max_workers=4,
    )
    print(f"downloaded model to {local_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
