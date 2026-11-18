"""On-demand lightweight host, GPU and application process monitoring for Linux."""
from __future__ import annotations

import os
import subprocess
import time
import psutil


def _mib(value: int | float) -> float:
    return round(float(value) / (1024 * 1024), 1)


def _gpu_processes() -> list[dict]:
    """NVIDIA compute processes only. Desktop display VRAM is in the device total."""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory",
             "--format=csv,noheader,nounits"],
            text=True, capture_output=True, check=False, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if p.returncode != 0:
        return []
    rows = []
    for line in p.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
            used = float(parts[2]) if parts[2] not in ("N/A", "[N/A]", "") else None
        except ValueError:
            continue
        rows.append({"pid": pid, "name": parts[1],
                     "vram_mib": used})
    return rows[:24]


def gpu_snapshot() -> dict:
    fields = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    try:
        p = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            text=True, capture_output=True, check=False, timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "devices": [], "processes": []}
    if p.returncode != 0 or not p.stdout.strip():
        return {"available": False, "devices": [], "processes": [],
                "error": p.stderr.strip()[-200:]}

    entries = []
    for line in p.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != 6:
            continue
        def number(item):
            try:
                return float(item)
            except (ValueError, TypeError):
                return None
        used, total, load, temperature, watts = map(number, parts[1:])
        entries.append({
            "name": parts[0],
            "vram_used_mib": used,
            "vram_total_mib": total,
            "vram_percent": round(used / total * 100, 1) if total else None,
            "utilization_percent": load,
            "temperature_c": temperature,
            "power_w": watts,
        })
    return {"available": bool(entries), "devices": entries,
            "processes": _gpu_processes()}


def disk_snapshot() -> list[dict]:
    items, seen = [], set()
    for part in psutil.disk_partitions(all=False):
        mount, device, fs = part.mountpoint, part.device, part.fstype.lower()
        if (not device.startswith("/dev/") or device.startswith("/dev/loop")
            or fs in {"squashfs", "overlay", "tmpfs", "devtmpfs", "ramfs"}
            or mount == "/boot/efi" or mount == "/snap" or mount.startswith("/snap/")
            or mount.startswith("/var/lib/snapd/") or mount in seen):
            continue
        seen.add(mount)
        try:
            usage = psutil.disk_usage(mount)
        except (OSError, PermissionError):
            continue
        items.append({"mount": mount, "device": device,
                      "total_mib": _mib(usage.total), "used_mib": _mib(usage.used),
                      "free_mib": _mib(usage.free), "percent": round(usage.percent, 1)})
    return sorted(items, key=lambda x: (x["mount"] != "/",
                                       x["mount"] != "/1tbdisk", x["mount"]))


def zombie_snapshot() -> dict:
    zombies = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "status"]):
        try:
            if proc.info.get("status") == psutil.STATUS_ZOMBIE:
                zombies.append({"pid": proc.info["pid"], "ppid": proc.info["ppid"],
                                "name": proc.info.get("name") or "?"})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"count": len(zombies), "examples": zombies[:12]}


def _studio_processes(worker_pid: int | None, gpu_processes: list[dict]) -> list[dict]:
    """Show own Flask, Ollama service/runners and active image worker.

    CPU is per process across cores and may exceed 100%; RAM is resident RSS.
    """
    gpu_memory = {p["pid"]: p["vram_mib"] for p in gpu_processes}
    picked = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            pid = proc.info["pid"]
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()[:450]
            if pid == os.getpid():
                role = "Flask / веб-панель"
            elif pid == worker_pid and worker_pid:
                role = "Diffusers / генерация"
            elif ("ollama" in name or "ollama" in cmdline):
                role = "Ollama / LLM"
            elif pid in gpu_memory:
                role = "GPU / другой процесс"
            else:
                continue
            picked.append((proc, {"pid": pid, "role": role,
                                  "name": (proc.info.get("name") or "?")[:80],
                                  "ram_mib": _mib(proc.info["memory_info"].rss)
                                  if proc.info.get("memory_info") else 0,
                                  "vram_mib": gpu_memory.get(pid)}))
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    time.sleep(0.16)
    rows = []
    for proc, data in picked:
        try:
            data["cpu_percent"] = round(proc.cpu_percent(interval=None), 1)
            rows.append(data)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    priority = {"Diffusers / генерация": 0, "Ollama / LLM": 1,
                "Flask / веб-панель": 2, "GPU / другой процесс": 3}
    return sorted(rows, key=lambda p: (priority.get(p["role"], 9), -p["ram_mib"]))[:18]


def collect_snapshot(active_job: dict | None = None) -> dict:
    # All expensive samples happen only for explicit monitor refresh or while open
    # during active image rendering; never use always-on background collectors.
    psutil.cpu_percent(interval=None)
    gpu = gpu_snapshot()
    worker_pid = (active_job or {}).get("pid")
    process_rows = _studio_processes(worker_pid, gpu.get("processes", []))
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "cpu": {"percent": cpu, "logical_threads": psutil.cpu_count(logical=True),
                "physical_cores": psutil.cpu_count(logical=False),
                "load_average": [round(x, 2) for x in os.getloadavg()]},
        "ram": {"total_mib": _mib(ram.total),
                "used_mib": _mib(ram.total - ram.available),
                "available_mib": _mib(ram.available), "percent": ram.percent},
        "swap": {"total_mib": _mib(swap.total), "used_mib": _mib(swap.used),
                 "free_mib": _mib(swap.free), "percent": swap.percent},
        "gpu": gpu, "processes": process_rows,
        "disks": disk_snapshot(), "zombies": zombie_snapshot(),
        "monitor_note": ("CPU per process may exceed 100% on multicore machines; "
                         "RAM is RSS, GPU per-process is NVIDIA compute VRAM."),
    }
