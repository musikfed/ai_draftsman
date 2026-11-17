"""Compatible SDXL checkpoints; downloads are explicit, selected, and on the data drive.

Other checkpoint families need a different pipeline and are deliberately not guessed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "checkpoints"

CHECKPOINTS = {
    "illustrious-xl-v2": {
        "title": "Illustrious XL v2.0 — манга / иллюстрации",
        "repo_id": "OnomaAIResearch/Illustrious-XL-v2.0",
        "filename": "Illustrious-XL-v2.0.safetensors",
        "family": "SDXL",
        "config": "stabilityai/stable-diffusion-xl-base-1.0",
        "license": "creativeml-openrail-m",
        "url": "https://huggingface.co/OnomaAIResearch/Illustrious-XL-v2.0",
    },
    "sdxl-base-1": {
        "title": "Stable Diffusion XL Base 1.0 — универсальная",
        "repo_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "filename": "sd_xl_base_1.0.safetensors",
        "family": "SDXL",
        "config": "stabilityai/stable-diffusion-xl-base-1.0",
        "license": "openrail++",
        "url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
    },
}
DEFAULT_CHECKPOINT = "illustrious-xl-v2"


def get_checkpoint(model_id: str):
    try:
        model = CHECKPOINTS[model_id]
    except KeyError:
        raise ValueError("Unknown image model; only validated SDXL checkpoints are supported") from None
    return MODEL_DIR / model["filename"], model


def list_checkpoints():
    return [
        {"id": k, **v, "installed": (MODEL_DIR / v["filename"]).is_file(),
         "path": str(MODEL_DIR / v["filename"])}
        for k, v in CHECKPOINTS.items()
    ]
