#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/data/uv-cache"
mkdir -p "$UV_CACHE_DIR" models/checkpoints models/loras data/references data/jobs
uv sync --no-dev
mkdir -p data/workflows data/reference data/outputs
if [[ ! -f .env ]]; then cp .env.example .env; fi
echo "Installed. Edit .env if needed. Start: bash scripts/run.sh"
echo "LAN URL: http://192.168.0.100:9898"
