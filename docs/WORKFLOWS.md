# Image engine setup — PEGINELAB AI Draftsman

The browser dashboard on **http://192.168.0.100:9898** is a lightweight Flask app. Its image engine is separate, never auto-started. The user launches/stops ComfyUI from its own terminal when needed.

## Local model discovery and official download

The **Найти модели на дисках** button scans `/1tbdisk` (limited to protect latency). It reports candidate weights, not guaranteed working image models.

The **Показать модели Ollama** button lists existing local LLM/VLM/embedding models: Qwen3:8B scripts, Qwen2.5VL:7B image analysis, nomic-embed-text for future vector RAG. They do not themselves paint a panel of manga.

For starter images choose **Illustrious XL v2.0** (SDXL compatible) from the official `OnomaAIResearch/Illustrious-XL-v2.0` repository, CreativeML OpenRAIL-M. The button **Скачать Illustrious XL v2.0** starts a multi-GB download only on click; **Состояние загрузки** reads its status. Downloaded checkpoint: `<project>/models/checkpoints/Illustrious-XL-v2.0.safetensors`. Check model terms before commercial use. Downloads are not started merely by opening the page.

## ComfyUI

1. Choose a compatible NVIDIA driver + PyTorch environment before installing ComfyUI. Avoid changing the host's drivers on an already running server without a separate compatibility review.
2. Install ComfyUI under `<project>/runtime/ComfyUI` with its own `.venv`. It uses GPU separately from Ollama; GPU workloads compete for the same 12 GiB VRAM.
3. After ComfyUI is installed, run `uv run python scripts/configure_comfy_models.py`. If `extra_model_paths.yaml` already exists, the script refuses to overwrite and prints the stanza for manual merge.
4. Launch ComfyUI **in a separate terminal** on localhost port 8188. No startup button is present in the studio.
5. Select the Illustrious checkpoint and construct a compatible SDXL text-to-image workflow. Validate one image directly in ComfyUI (character consistency and Russian lettering are not automatic).
6. Export workflow as **API Format**. Replace exactly one positive prompt text field with the literal `{{PROMPT}}` and save it under `data/workflows/comic_api.json`.
7. In AI Draftsman: select episode, use Ollama to create five drafts, review/approve each, press Generate. A prompt ID is returned from ComfyUI.
8. Final output: `uv run python scripts/export_png8.py input.png output.png` — 800×1000, indexed PNG-8 up to 256 colors. The export utility preserves the canvas by padding, not cropping.

## Memory controls and status

- **ВЫКЛ (Выключить студию)** ends the Python Flask application itself; the user restarts it with `bash scripts/run.sh`.
- **Освободить VRAM** sends `POST /free` to ComfyUI when idle, plus Ollama `/api/generate` keep_alive=0 to loaded models identified using `/api/ps`. This is an explicit unload request, not a process kill or a guarantee that all VRAM will be free. It does not kill Xorg or other unrelated programs.
- Monitor CPU, RAM, VRAM, disks, swap, zombies via **Обновить показатели**. No automatic polling is enabled.

## MVP limitations

- Full automatic image collection, previews, finished ZIP creation, LoRA training, multi-reference/ControlNet workflows, and semantic vector/graph database integration are **planned but not yet implemented**.
- The saved five-slide plan and SQLite FTS5-based textual RAG are implemented; these are not yet a trained image model.
- No GPU model is downloaded or installed unless the user explicitly triggers the action.
- Only use this HTTP dashboard on a trusted test LAN. No authentication is included in the MVP.
