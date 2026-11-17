"""Isolated image generator; run only for a user-requested job.

This module lives in the GPU virtual environment, never imports into Flask.
An individual subprocess exits after producing the requested variants,
which releases its CUDA context and VRAM.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def write_state(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def generate(spec: dict, state_path: Path) -> None:
    # Import CUDA dependencies only in this temporary worker, not Flask.
    import torch
    from PIL import Image, ImageOps
    from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable to torch. Verify the isolated cu124 PyTorch install.")

    checkpoint = (BASE / "models/checkpoints/Illustrious-XL-v2.0.safetensors").resolve()
    if not checkpoint.is_file():
        raise FileNotFoundError(f"Image checkpoint missing: {checkpoint}. Download it from the studio first.")

    mode = spec["mode"]
    cls = StableDiffusionXLImg2ImgPipeline if mode == "img2img" else StableDiffusionXLPipeline
    # The official SDXL pipeline configuration can be cached from Hugging Face
    # on first use. All caches live on the 1TB data disk.
    pipe = cls.from_single_file(
        str(checkpoint),
        config="stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()

    lora_name = spec.get("lora")
    if lora_name:
        lora_dir = (BASE / "models/loras").resolve()
        selected = (lora_dir / lora_name).resolve()
        if selected.parent != lora_dir or selected.suffix.lower() != ".safetensors" or not selected.is_file():
            raise ValueError("Invalid or missing local LoRA filename")
        pipe.load_lora_weights(str(selected), adapter_name="draftsman")
        pipe.set_adapters(["draftsman"], adapter_weights=[float(spec.get("lora_scale", 0.7))])

    init_image = None
    if mode == "img2img":
        image = Path(spec["reference"]).resolve()
        references = (BASE / "data/references").resolve()
        if image.parent != references or not image.is_file():
            raise ValueError("Only uploaded images from data/references are accepted")
        init_image = ImageOps.fit(Image.open(image).convert("RGB"),
                                  (int(spec["width"]), int(spec["height"])),
                                  Image.Resampling.LANCZOS)
    state = {"status": "running", "job_id": spec["job_id"],
             "started_at": time.time(), "completed": 0, "total": spec["variants"],
             "outputs": []}
    write_state(state_path, state)
    target = Path(spec["output_dir"]).resolve()
    target.mkdir(parents=True, exist_ok=True)

    for index in range(int(spec["variants"])):
        seed = int(spec["seed"]) + index
        common = {
            "prompt": spec["prompt"],
            "negative_prompt": spec.get("negative_prompt", ""),
            "guidance_scale": float(spec["cfg"]),
            "num_inference_steps": int(spec["steps"]),
            "generator": torch.Generator(device="cpu").manual_seed(seed),
        }
        if mode == "img2img":
            result = pipe(image=init_image, strength=float(spec["strength"]), **common)
        else:
            result = pipe(width=int(spec["width"]), height=int(spec["height"]), **common)
        image = result.images[0].convert("RGB")
        prefix = f'{int(spec["lesson"]):03d}_{int(spec["slide"]):02d}_v{index+1:02d}'
        master = target / (prefix + "_master.png")
        final = target / (prefix + ".png")
        image.save(master, format="PNG", optimize=True)

        # Do not crop speech bubbles or characters. Export exact 4:5 size.
        result_image = ImageOps.pad(image, (800,1000),
                                    method=Image.Resampling.LANCZOS,
                                    color=(13,20,33))
        indexed = result_image.quantize(colors=256,
                                        method=Image.Quantize.MEDIANCUT,
                                        dither=Image.Dither.NONE)
        indexed.save(final, format="PNG", optimize=True, compress_level=9)

        state["outputs"].append({"variant": index+1, "seed": seed,
                                 "png8": str(final), "master": str(master)})
        state["completed"] = index+1
        write_state(state_path, state)

    state["status"] = "completed"
    state["finished_at"] = time.time()
    write_state(state_path, state)
    # Worker exits immediately after return, releasing all CUDA allocations.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", type=Path)
    args = ap.parse_args()
    spec_path = args.spec.resolve()
    data_root = (BASE / "data/jobs").resolve()
    if spec_path.parent.parent != data_root or spec_path.name != "spec.json":
        raise SystemExit("Job spec must be in project data/jobs/<id>/spec.json")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    state_path = spec_path.parent / "state.json"
    os.environ.setdefault("HF_HOME", str(BASE / "data/huggingface"))
    os.environ.setdefault("HF_HUB_CACHE", str(BASE / "data/huggingface/hub"))
    os.environ.setdefault("TORCH_HOME", str(BASE / "data/torch"))
    try:
        generate(spec, state_path)
    except Exception as exc:
        previous = {}
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        previous.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                        traceback=traceback.format_exc()[-4000:],
                        finished_at=time.time())
        write_state(state_path, previous)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
