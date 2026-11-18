#!/usr/bin/env bash
# Start Flask without silently installing packages or loading GPU models.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

export UV_CACHE_DIR="$ROOT/data/uv-cache"
export HF_HOME="$ROOT/data/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export TORCH_HOME="$ROOT/data/torch"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    echo "ERROR: studio environment missing. Run: bash scripts/install.sh" >&2
    exit 1
fi

exec uv run --no-sync --no-dev python app.py
