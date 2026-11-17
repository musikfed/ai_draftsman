#!/usr/bin/env bash
# Independent RTX 3060 CUDA image worker. Nothing is installed system-wide.
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/data/uv-cache"
export HF_HOME="$PWD/data/huggingface"
mkdir -p "$UV_CACHE_DIR" "$HF_HOME" models/checkpoints models/loras data/references data/jobs
VENV="$PWD/runtime/gpu-venv"

echo "GPU runtime only; Ubuntu driver and existing Ollama are NOT modified."
echo "All packages remain under: $VENV"
uv venv --python 3.12 "$VENV"
uv pip install --python "$VENV/bin/python" \
  torch==2.6.0 torchvision==0.21.0 \
  --index-url https://download.pytorch.org/whl/cu124
uv pip install --python "$VENV/bin/python" \
  "diffusers==0.35.2" "transformers==4.49.0" \
  "accelerate==1.6.0" "peft>=0.17,<0.19" \
  "huggingface-hub>=0.34,<1" "safetensors>=0.5,<1" \
  "Pillow>=11,<13"

"$VENV/bin/python" - <<'PY'
import torch, diffusers, transformers
print("Torch:", torch.__version__, "CUDA build:", torch.version.cuda)
print("Diffusers:", diffusers.__version__, "Transformers:", transformers.__version__)
print("CUDA available:", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("CUDA unavailable; no inference attempted.")
print("GPU:", torch.cuda.get_device_name(0))
PY

echo "Ready for independent image jobs. Open the Flask UI and generate an approved slide."
