#!/usr/bin/env bash
# PEGINELAB AI Draftsman: user-space install under /1tbdisk.
# No sudo, no GPU driver changes, no Ollama changes, no checkpoint downloads.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd -P)"

# This project must be on the mounted 1 TB data disk, never on /.
if [[ "$ROOT" != /1tbdisk/* ]] || ! mountpoint -q /1tbdisk; then
    echo "ERROR: /1tbdisk must be mounted and AI Draftsman must live under it." >&2
    echo "Refusing to install or start on the almost-full system partition." >&2
    exit 1
fi

case "${1:-}" in
    "") INSTALL_GPU=0 ;;
    --gpu) INSTALL_GPU=1 ;;
    *) echo "Usage: bash scripts/install.sh [--gpu]" >&2; exit 2 ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not found in PATH. Install uv for this user first." >&2
    exit 1
fi
if [[ ! -w "$ROOT" ]]; then
    echo "ERROR: $ROOT is not writable by the current user. No permissions changed." >&2
    exit 1
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

mkdir -p "$UV_CACHE_DIR" "$HF_HUB_CACHE" "$TORCH_HOME" \
         "$ROOT/models/checkpoints" "$ROOT/models/loras" \
         "$ROOT/data/references" "$ROOT/data/jobs" \
         "$ROOT/data/workflows" "$ROOT/data/outputs"

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Created .env from .env.example; existing .env is never overwritten."
fi

echo "Installing the lightweight Flask studio in: $ROOT/.venv"
uv sync --python 3.12 --no-dev

if (( INSTALL_GPU )); then
    bash "$ROOT/scripts/install_gpu.sh"
else
    echo "GPU install skipped. To install it separately: bash scripts/install_gpu.sh"
fi

echo
echo "Installed: $ROOT"
echo "Start: bash scripts/run.sh"
echo "LAN URL: http://192.168.0.100:9898"
echo "Image models are NOT downloaded by this installer."
echo "Select and download SDXL checkpoints explicitly in the web UI."
