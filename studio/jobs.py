"""Local job management with no heavy GPU imports and no persistent model daemon."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("DRAFTSMAN_DATA", str(BASE / "data"))).resolve()
JOBS = DATA / "jobs"
WORKER_PY = BASE / "runtime/gpu-venv/bin/python"
CHECKPOINT = BASE / "models/checkpoints/Illustrious-XL-v2.0.safetensors"


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default if default is not None else {}


def process_is_worker(pid, job_id):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        return ("studio.worker" in cmd and job_id in cmd)
    except (OSError, ValueError):
        return False


def get_job(job_id: str):
    if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
        return None
    folder = JOBS / job_id
    if not folder.is_dir():
        return None
    state = read_json(folder / "state.json")
    state["job_id"] = job_id
    try:
        pid = int((folder / "worker.pid").read_text())
    except (OSError, ValueError):
        pid = None
    if state.get("status") in ("queued", "running") and pid and not process_is_worker(pid, job_id):
        # Worker exited before it could write a successful/failed result.
        # Wait briefly for a finishing state write to avoid race at process exit.
        if time.time() - (folder / "state.json").stat().st_mtime > 10:
            state.update(status="failed", error="GPU worker exited unexpectedly; inspect worker.log")
            atomic_json(folder / "state.json", state)
    state["pid"] = pid
    return state


def current_job():
    if not JOBS.is_dir():
        return None
    for folder in JOBS.iterdir():
        if not folder.is_dir():
            continue
        state = get_job(folder.name)
        if not state or state.get("status") not in ("queued", "running"):
            continue
        pid = state.get("pid")
        if process_is_worker(pid, folder.name):
            return state
        if state.get("status") == "queued" and time.time() - (folder/"state.json").stat().st_mtime < 10:
            return state
    return None


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def submit_job(spec: dict):
    if current_job():
        raise RuntimeError("GPU already busy. Wait for the existing job to finish.")
    if not WORKER_PY.is_file():
        raise FileNotFoundError("GPU environment absent; run bash scripts/install_gpu.sh")
    if not CHECKPOINT.is_file():
        raise FileNotFoundError("SDXL checkpoint absent; use explicit model download in the UI")
    job_id = uuid.uuid4().hex
    folder = JOBS / job_id
    folder.mkdir(parents=True, exist_ok=False)
    spec = dict(spec)
    spec.update(job_id=job_id, output_dir=str(folder / "images"))
    atomic_json(folder/"spec.json", spec)
    atomic_json(folder/"state.json", {
        "job_id": job_id, "status":"queued", "total":spec["variants"],
        "completed":0, "created_at":time.time(), "outputs":[]
    })
    env=os.environ.copy()
    env["DRAFTSMAN_DATA"] = str(DATA)
    env["HF_HOME"] = str(DATA/"huggingface")
    env["HF_HUB_CACHE"] = str(DATA/"huggingface"/"hub")
    env["TORCH_HOME"] = str(DATA/"torch")
    # Do not load Diffusers, torch or checkpoint inside the Flask process.
    with (folder/"worker.log").open("ab") as output:
        process=subprocess.Popen(
            [str(WORKER_PY), "-m", "studio.worker", str(folder/"spec.json")],
            cwd=str(BASE), env=env, stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            close_fds=True)
    (folder/"worker.pid").write_text(str(process.pid))
    return job_id


def recent_jobs(limit: int = 20):
    """Read persisted job manifests without loading CUDA or depending on browser state."""
    if not JOBS.is_dir():
        return []
    result = []
    folders = sorted((p for p in JOBS.iterdir() if p.is_dir()),
                     key=lambda p: p.stat().st_mtime, reverse=True)[:min(200, limit*3)]
    for folder in folders:
        status = get_job(folder.name)
        if status is None:
            continue
        spec = read_json(folder / "spec.json")
        result.append({
            "job_id":folder.name,
            "status":status.get("status", "unknown"),
            "stage":status.get("stage", ""),
            "progress":status.get("progress", 0),
            "completed":status.get("completed", 0),
            "total":status.get("total", 0),
            "created_at":status.get("created_at"),
            "project_id":spec.get("project_id"),
            "node_id":spec.get("node_id"),
            "source":spec.get("source", "graph"),
            "prompt_preview":str(spec.get("prompt", ""))[:95],
            "outputs":len(status.get("outputs",[]))
        })
        if len(result)>=limit:
            break
    return result
