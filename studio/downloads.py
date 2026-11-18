"""Explicit, resumable, integrity-checked single-checkpoint downloads.

This module does not download or import GPU libraries on import.
One model file and optional .part live under the user-owned project directory.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from pathlib import Path
from typing import Callable

import requests
from studio.checkpoints import get_checkpoint

_CHUNK = 2 * 1024 * 1024
_REQUIRED_BUFFER = 1 * 1024**3


def download_checkpoint(model_id: str, progress: Callable[[dict], None]) -> Path:
    path, cfg = get_checkpoint(model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    expected_sha = cfg["expected_sha256"]
    expected_size = int(cfg["expected_size_bytes"])

    if path.is_file():
        progress({"stage": "Проверка уже скачанного файла", "downloaded_bytes": path.stat().st_size})
        if _digest(path) == expected_sha:
            progress({"percent": 100, "stage": "Проверено: SHA-256 совпадает"})
            return path
        raise RuntimeError("Existing checkpoint hash differs from official SHA-256. No files deleted.")

    current = partial.stat().st_size if partial.is_file() else 0
    if current > expected_size * 1.05:
        raise RuntimeError("Partial checkpoint is unexpectedly large; inspect the .part file")
    free = shutil.disk_usage(path.parent).free
    if free < max(0, expected_size - current) + _REQUIRED_BUFFER:
        raise RuntimeError(
            f"Not enough free space on model disk: {free / 1024**3:.1f} GiB. "
            "Keep at least 1 GiB free in addition to remaining checkpoint bytes."
        )

    url = (f"https://huggingface.co/{cfg['repo_id']}/resolve/main/"
           f"{cfg['filename']}?download=true")
    headers = {"Accept-Encoding": "identity"}
    if current:
        headers["Range"] = f"bytes={current}-"

    with requests.get(url, headers=headers, stream=True, timeout=(20, 120),
                      allow_redirects=True) as response:
        response.raise_for_status()
        # If CDN ignored Range, start again rather than corrupting the partial file.
        code = response.status_code
        if current and code == 206:
            content_range = response.headers.get("Content-Range", "")
            match = re.match(r"bytes\s+(\d+)-\d+/\d+", content_range)
            if not match or int(match.group(1)) != current:
                raise RuntimeError("Server returned a mismatched resume position")
        elif current and code == 200:
            current = 0
        elif code not in (200, 206):
            raise RuntimeError(f"Unexpected checkpoint HTTP status {code}")

        downloaded = current
        total = expected_size
        if response.headers.get("Content-Length"):
            server_length = int(response.headers["Content-Length"])
            if server_length > 0:
                total = current + server_length
        if not (6_500_000_000 <= total <= 8_000_000_000):
            raise RuntimeError(f"Unexpected model download size ({total} bytes); refusing file")

        started = time.monotonic()
        previous = started
        initial = current
        with partial.open("ab" if current else "wb") as output:
            for chunk in response.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > total + _CHUNK:
                    raise RuntimeError("Checkpoint larger than expected")
                output.write(chunk)
                now = time.monotonic()
                if now - previous >= 0.5:
                    elapsed = max(0.1, now - started)
                    progress({
                        "stage": "Скачивание весов SDXL",
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "percent": round(100 * downloaded / total, 1),
                        "speed_mib_s": round((downloaded - initial) / elapsed / 1024**2, 2),
                    })
                    previous = now
            output.flush()

    if downloaded != total:
        raise RuntimeError(f"File incomplete: received {downloaded} of {total} bytes")
    progress({"stage": "Проверка SHA-256", "downloaded_bytes": downloaded,
              "total_bytes": total, "percent": 99.9})
    if _digest(partial) != expected_sha:
        partial.unlink(missing_ok=True)  # Only our own corrupt temporary download
        raise RuntimeError("SHA-256 mismatch. Temporary corrupt file discarded.")
    partial.replace(path)
    progress({"stage": "Скачано и проверено", "downloaded_bytes": downloaded,
              "total_bytes": total, "percent": 100, "speed_mib_s": 0})
    return path


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()
