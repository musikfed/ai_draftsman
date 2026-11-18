#!/usr/bin/env bash
# Start Flask without silently installing packages or loading GPU models.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd -P)"

# This project must be on the mounted 1 TB data disk, never on /.
if [[ "$ROOT" != /1tbdisk/* ]] || ! mountpoint -q /1tbdisk; then
    echo "ERROR: /1tbdisk must be mounted and AI Draftsman must live under it." >&2
    echo "Refusing to install or start on the almost-full system partition." >&2
    exit 1
fi

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# Explicitly pin all application caches, Python runtimes and temp files to /1tbdisk.
export UV_CACHE_DIR="$ROOT/data/uv-cache"
export UV_PYTHON_INSTALL_DIR="$ROOT/runtime/uv-python"
export HF_HOME="$ROOT/data/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_XET_CACHE="$HF_HOME/xet"
export TORCH_HOME="$ROOT/data/torch"
export XDG_CACHE_HOME="$ROOT/data/xdg-cache"
export TMPDIR="$ROOT/data/tmp"
mkdir -p "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR" "$HF_HUB_CACHE" \
         "$HF_XET_CACHE" "$TORCH_HOME" "$XDG_CACHE_HOME" "$TMPDIR"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    echo "ERROR: studio environment missing. Run: bash scripts/install.sh" >&2
    exit 1
fi

exec uv run --no-sync --no-dev python app.py
