"""Read-only discovery of local image checkpoints and LoRA files.

Explicit user action only. The scanner never downloads files or changes disks.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

IMAGE_EXTS = {".safetensors", ".ckpt", ".pt", ".pth", ".onnx"}
OMIT_DIRS = {
    "lost+found", ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".trash-1000", ".cache", "tmp", "temp", "logs",
}
MAX_DIRECTORIES = 35000
MAX_FILES = 350000
TIME_LIMIT_SECONDS = 15.0
RESULT_LIMIT = 160


def classify(path: Path) -> str:
    parts = {x.lower() for x in path.parts}
    name = path.name.lower()
    if {"lora", "loras", "lycoris"} & parts or "lora" in name:
        return "LoRA"
    if {"controlnet", "ipadapter", "ip_adapter", "adapters"} & parts:
        return "adapter"
    if {"vae", "vae_approx"} & parts:
        return "VAE"
    if {"clip", "text_encoders"} & parts:
        return "text encoder"
    if {"unet", "diffusion_models", "transformer"} & parts:
        return "diffusion model"
    if {"checkpoints", "stable_diffusion", "stable-diffusion"} & parts:
        return "checkpoint"
    if path.suffix.lower() == ".onnx":
        return "ONNX (unverified)"
    return "weights (unverified)"


def scan_models(roots: list[str]) -> dict:
    start = time.monotonic()
    found = []
    folders = files = 0
    truncated = False
    visited = []
    for root_str in roots:
        root = Path(root_str).expanduser().resolve()
        if not root.is_dir():
            continue
        visited.append(str(root))
        for current, dirs, filenames in os.walk(root, followlinks=False):
            folders += 1
            dirs[:] = [d for d in dirs if d.lower() not in OMIT_DIRS and not d.startswith(".")]
            if folders >= MAX_DIRECTORIES or files >= MAX_FILES or time.monotonic() - start > TIME_LIMIT_SECONDS:
                truncated = True
                break
            for name in filenames:
                files += 1
                if files >= MAX_FILES or time.monotonic() - start > TIME_LIMIT_SECONDS:
                    truncated = True
                    break
                path = Path(current) / name
                if path.suffix.lower() not in IMAGE_EXTS:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size < 4 * 1024 * 1024:
                    continue
                found.append({
                    "filename": path.name,
                    "path": str(path),
                    "size_mib": round(size / 1048576, 1),
                    "kind": classify(path),
                })
            if truncated:
                break
        if truncated:
            break
    # Larger weights on top; no model is assumed compatible based on extension alone.
    found.sort(key=lambda e: -e["size_mib"])
    return {
        "roots": visited, "models": found[:RESULT_LIMIT],
        "total_found": len(found), "truncated": truncated or len(found) > RESULT_LIMIT,
        "directories_checked": folders, "files_checked": files,
        "elapsed_seconds": round(time.monotonic() - start, 2),
        "note": "These are weight files, not proof of compatible image-generation models.",
    }


CATALOG = [
    {
        "name": "Illustrious XL v2.0",
        "family": "SDXL",
        "role": "anime/manga checkpoint; starting choice for character LoRA",
        "model_url": "https://huggingface.co/OnomaAIResearch/Illustrious-XL-v2.0",
        "license_note": "CreativeML Open RAIL; inspect exact checkpoint terms before monetizing",
        "download": "Choose the appropriate .safetensors file from official model Files page; place under ComfyUI/models/checkpoints",
    },
    {
        "name": "ComfyUI",
        "family": "inference backend",
        "role": "runs image checkpoints, ControlNet, LoRA and multi-reference workflows",
        "model_url": "https://github.com/Comfy-Org/ComfyUI",
        "license_note": "Check checkpoint and LoRA licenses individually",
        "download": "Install from the official repository, separate from Ollama",
    },
]
