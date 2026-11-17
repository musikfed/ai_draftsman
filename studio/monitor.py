"""Low-overhead on-demand system telemetry for Linux host."""
from __future__ import annotations

import os
import subprocess

import psutil


def _mib(value: int) -> int:
    return round(value / (1024 * 1024))


def gpu_snapshot() -> dict:
    # nvidia-smi is invoked only when the user refreshes, not in a timer.
    fields = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    try:
        p = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            text=True, capture_output=True, check=False, timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False}
    if p.returncode != 0 or not p.stdout.strip():
        return {"available": False, "error": p.stderr.strip()[-200:]}
    entries = []
    for line in p.stdout.splitlines():
        parts = [s.strip() for s in line.split(",")]
        if len(parts) != 6:
            continue
        name = parts[0]

        def number(text):
            try:
                return float(text)
            except (ValueError, TypeError):
                return None

        used, total, load, temperature, watts = map(number, parts[1:])
        entries.append({
            "name": name,
            "vram_used_mib": used,
            "vram_total_mib": total,
            "vram_percent": round(used / total * 100, 1) if total else None,
            "utilization_percent": load,
            "temperature_c": temperature,
            "power_w": watts,
        })
    return {"available": bool(entries), "devices": entries}


def disk_snapshot() -> list[dict]:
    items = []
    seen = set()
    for partition in psutil.disk_partitions(all=False):
        # Snap packages are read-only squashfs images mounted as /dev/loop*.
        # They show 100% "usage" by design; they are NOT full physical disks.
        mount = partition.mountpoint
        device = partition.device
        filesystem = partition.fstype.lower()
        if (
            not device.startswith("/dev/")
            or device.startswith("/dev/loop")
            or filesystem in {"squashfs", "overlay", "tmpfs", "devtmpfs", "ramfs"}
            or mount == "/boot/efi"
            or mount == "/snap"
            or mount.startswith("/snap/")
            or mount.startswith("/var/lib/snapd/")
            or mount in seen
        ):
            continue
        seen.add(partition.mountpoint)
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (OSError, PermissionError):
            continue
        items.append({
            "mount": partition.mountpoint,
            "device": partition.device,
            "total_mib": _mib(usage.total),
            "used_mib": _mib(usage.used),
            "free_mib": _mib(usage.free),
            "percent": round(usage.percent, 1),
        })
    return sorted(items, key=lambda x: (x["mount"] != "/", x["mount"] != "/1tbdisk", x["mount"]))


def zombie_snapshot() -> dict:
    zombies = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "status"]):
        try:
            if proc.info.get("status") == psutil.STATUS_ZOMBIE:
                zombies.append({
                    "pid": proc.info["pid"],
                    "ppid": proc.info["ppid"],
                    "name": proc.info.get("name") or "?",
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"count": len(zombies), "examples": zombies[:12]}


def collect_snapshot() -> dict:
    # 120 ms CPU sample on explicit page refresh; no background polling.
    cpu = psutil.cpu_percent(interval=0.12)
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "cpu": {
            "percent": cpu,
            "logical_threads": psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "load_average": [round(x, 2) for x in os.getloadavg()],
        },
        "ram": {
            "total_mib": _mib(vm.total),
            "used_mib": _mib(vm.total - vm.available),
            "available_mib": _mib(vm.available),
            "percent": vm.percent,
        },
        "swap": {
            "total_mib": _mib(swap.total),
            "used_mib": _mib(swap.used),
            "free_mib": _mib(swap.free),
            "percent": swap.percent,
        },
        "gpu": gpu_snapshot(),
        "disks": disk_snapshot(),
        "zombies": zombie_snapshot(),
    }
