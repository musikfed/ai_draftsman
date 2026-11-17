# Image model and ComfyUI workflow

The Flask studio is an orchestrator; it does **not** download a checkpoint or pretend that image generation is ready.

1. Install compatible NVIDIA driver / CUDA-enabled PyTorch on the host and ComfyUI separately in `/1tbdisk/AI/ComfyUI`, with its own `.venv`.
2. Select and install an image checkpoint with a license suitable for the project. Start with a 12GB-compatible SDXL / Illustrious XL checkpoint; optionally test FLUX models using low-VRAM offloading.
3. Build and validate a **working** ComfyUI graph in the ComfyUI interface first. Use the checkpoint's supported nodes. Test one image manually.
4. Export using ComfyUI's **Save (API Format)** workflow option.
5. In the resulting API JSON, locate the main positive prompt text field and put the literal marker `{{PROMPT}}` in it. Do not use that marker in any other node.
6. Save it as `data/workflows/comic_api.json`.
7. Open the studio at :9898, turn the image engine ON, plan the lesson, review its five slides, mark a slide approved, then press Generate. The backend submits the validated workflow to internal ComfyUI :8188.
8. For export, use `uv run python scripts/export_png8.py input.png output.png`. Final comic size is 800x1000, indexed PNG 256 colors.

## Limits of MVP
- Submitted ComfyUI prompt IDs are shown, but **automatic collecting, assembly and gallery browsing are not implemented yet**.
- Character-consistency training (LoRA), actual model downloads, reference attachment and automated quality checking are planned next steps.
- The browser does not calculate images or run inference; all workloads are on the Ubuntu server.
- The web page does not poll continuously; refresh status manually.
- To free VRAM after Ollama scenario planning, Ollama requests use `keep_alive: "0s"`. Other Ollama users and the service are not stopped.
- The OFF button stops **only** the ComfyUI process launched by this app, and refuses to stop it while jobs are queued/running.
- LAN HTTP has no authentication in the MVP, intentionally intended for isolated trusted test networks. Do not expose port 9898 publicly, and never port-forward it.
