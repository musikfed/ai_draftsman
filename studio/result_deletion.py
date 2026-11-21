"""Safely remove exactly one saved generation result, not its draft or other variants.

Uses only SQLite and the existing on-disk job manifests. No GPU imports.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import uuid
from pathlib import Path

from studio.jobs import atomic_json, read_json

_DELETE_LOCK = threading.Lock()
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def delete_single_result(result_id: int, connection, data_root: Path, get_job):
    """Return (JSON-compatible response, HTTP status).

    A completed job's PNG8 and master PNG are staged before removing the
    output from state.json and deleting its rows from SQLite. On a DB or
    manifest failure, put the files and manifest back, rather than silently
    losing the picture. Prompt versions, job specifications, other variants,
    references and models are deliberately never deleted.
    """
    with _DELETE_LOCK:
        with connection() as db:
            row = db.execute("""
                SELECT r.id, r.job_id, r.variant, d.archived
                FROM quick_result_index r
                JOIN quick_draft_jobs j ON j.job_id=r.job_id
                JOIN quick_draft_history d ON d.id=j.draft_id
                WHERE r.id=?
            """, (result_id,)).fetchone()
        if row is None:
            return {"error": "Result not found or already deleted"}, 404
        if row["archived"]:
            return {"error": "Archived results are read-only. Unarchive the draft first."}, 409

        job_id = row["job_id"]
        variant = int(row["variant"])
        if not _JOB_ID.fullmatch(job_id) or not 1 <= variant <= 48:
            return {"error": "Invalid stored result identity"}, 409
        job = get_job(job_id)
        if job is None:
            return {"error": "Job no longer exists"}, 404
        if job.get("status") not in ("completed", "failed"):
            return {"error": "Cannot delete a result while its worker may be running"}, 409

        folder = (Path(data_root) / "jobs" / job_id).resolve()
        image_dir = (folder / "images").resolve()
        manifest = folder / "state.json"
        if image_dir.parent != folder or not manifest.is_file() or manifest.is_symlink():
            return {"error": "Unsafe or missing job manifest"}, 409

        state = read_json(manifest)
        if not isinstance(state, dict) or not isinstance(state.get("outputs"), list):
            return {"error": "Invalid persisted job output list"}, 409
        target = None
        others = []
        for output in state["outputs"]:
            try:
                matches = int(output.get("variant")) == variant
            except (ValueError, KeyError, TypeError, AttributeError):
                matches = False
            if matches and target is None:
                target = output
            else:
                others.append(output)
        if target is None:
            return {"error": "Result is no longer present in the job"}, 404

        files = []
        for field in ("png8", "master"):
            raw = target.get(field)
            if not raw:
                continue
            source = Path(str(raw))
            if source.is_symlink():
                return {"error": "Refusing to delete a symlinked image"}, 409
            resolved = source.resolve()
            if resolved.parent != image_dir or resolved.suffix.lower() != ".png":
                return {"error": "Refusing to delete an image outside this job"}, 409
            if resolved not in files:
                files.append(resolved)

        staged = []
        original_state = state
        updated_state = dict(state)
        updated_state["outputs"] = others
        updated_state["deleted_variants"] = sorted(set(
            [*state.get("deleted_variants", []), variant]
        ))
        staging = folder / ".delete-staging"
        try:
            staging.mkdir(mode=0o700, exist_ok=True)
            for path in files:
                if path.is_file():
                    temp = staging / (uuid.uuid4().hex + "-" + path.name)
                    os.replace(path, temp)
                    staged.append((temp, path))
            atomic_json(manifest, updated_state)
            with connection() as db:
                # Re-check archive state inside the write transaction.
                check = db.execute("""
                    SELECT d.archived FROM quick_result_index r
                    JOIN quick_draft_jobs j ON j.job_id=r.job_id
                    JOIN quick_draft_history d ON d.id=j.draft_id
                    WHERE r.id=? AND r.job_id=? AND r.variant=?
                """, (result_id, job_id, variant)).fetchone()
                if check is None or check["archived"]:
                    raise RuntimeError("Result was changed while deleting")
                db.execute("DELETE FROM quick_image_ratings WHERE job_id=? AND variant=?",
                           (job_id, variant))
                db.execute("DELETE FROM quick_result_index WHERE id=?", (result_id,))
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
            try:
                atomic_json(manifest, original_state)
                for temp, path in reversed(staged):
                    if temp.is_file():
                        os.replace(temp, path)
            except OSError:
                return {"error": "Deletion failed; manual recovery from .delete-staging may be needed"}, 500
            return {"error": "Deletion cancelled; original result preserved: " + str(error)}, 500

        warnings = []
        for temp, _ in staged:
            try:
                temp.unlink()
            except OSError:
                warnings.append("Pending staged-file cleanup: " + temp.name)
        try:
            staging.rmdir()
        except OSError:
            pass  # May contain previous pending cleanup files.
        return {
            "deleted": True,
            "result_id": result_id,
            "job_id": job_id,
            "variant": variant,
            "files_removed": len(staged) - len(warnings),
            "remaining_variants": len(others),
            "cleanup_warnings": warnings,
        }, 200
