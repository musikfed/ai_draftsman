"""Create ComfyUI model path configuration without overwriting existing settings."""
from pathlib import Path
import os
import sys

project = Path(__file__).resolve().parents[1]
comfy = Path(os.environ.get("COMFYUI_DIR", str(project / "runtime" / "ComfyUI"))).resolve()
if not (comfy / "main.py").is_file():
    sys.exit(f"ComfyUI not installed at {comfy}. Install it first; no changes made.")
target = comfy / "extra_model_paths.yaml"
if target.exists():
    sys.exit(f"{target} already exists; not overwriting. Add this manually:\n"
             f"ai_draftsman:\n  base_path: {project}\n"
             "  checkpoints: models/checkpoints\n  loras: models/loras\n")
value = (f"ai_draftsman:\n  base_path: {project}\n"
         "  checkpoints: models/checkpoints\n  loras: models/loras\n")
target.write_text(value, encoding="utf-8")
print(f"Created {target}. ComfyUI will see AI Draftsman model folders on next start.")
