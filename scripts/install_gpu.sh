#!/usr/bin/env bash
# Independent RTX 3060 CUDA image worker in a dedicated user-space environment.
# Does NOT touch system Python, NVIDIA driver, Ollama or disk mount permissions.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not found in PATH." >&2
    exit 1
fi

export UV_CACHE_DIR="$ROOT/data/uv-cache"
export HF_HOME="$ROOT/data/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export TORCH_HOME="$ROOT/data/torch"

mkdir -p "$UV_CACHE_DIR" "$HF_HUB_CACHE" "$TORCH_HOME" \
         "$ROOT/models/checkpoints" "$ROOT/models/loras" \
         "$ROOT/data/references" "$ROOT/data/jobs"

VENV="$ROOT/runtime/gpu-venv"
PY="$VENV/bin/python"

check_gpu() {
    "$PY" - <<'PY'
import torch, diffusers, transformers, accelerate
assert torch.cuda.is_available(), "CUDA unavailable"
print("GPU ready:", torch.cuda.get_device_name(0))
print("Torch:", torch.__version__, "| CUDA:", torch.version.cuda)
print("Diffusers:", diffusers.__version__, "| Transformers:", transformers.__version__)
PY
}

if [[ -x "$PY" ]] && check_gpu; then
    echo "GPU runtime already installed. Reusing: $VENV"
    echo "No model checkpoints were downloaded."
    exit 0
fi

echo "Installing independent GPU runtime into: $VENV"
echo "Driver, Ollama and other projects remain unchanged."
if [[ ! -x "$PY" ]]; then
    uv venv --python 3.12 "$VENV"
fi

uv pip install --python "$PY" \
    torch==2.6.0 torchvision==0.21.0 \
    --index-url https://download.pytorch.org/whl/cu124

uv pip install --python "$PY" \
    "diffusers==0.35.2" "transformers==4.49.0" \
    "accelerate==1.6.0" "peft>=0.17,<0.19" \
    "huggingface-hub>=0.34,<1" "safetensors>=0.5,<1" \
    "Pillow>=11,<13"

check_gpu
echo "GPU worker ready. Download a selected SDXL checkpoint only from the web UI."
