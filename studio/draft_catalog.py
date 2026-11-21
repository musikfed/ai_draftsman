"""Searchable, durable draft catalog + real output ratings. No model imports or services."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

import requests
from flask import jsonify, request

_TRANSLATING = set()
_TRANSLATE_LOCK = threading.Lock()
_ID = re.compile(r"^[0-9a-f]{32}$")


def migrate(db, data: Path):
    """Additive SQLite migration: never remove or rewrite old saved drafts."""
    existing = {r[1] for r in db.execute("PRAGMA table_info(quick_draft_history)")}
    additions = {
        "title": "TEXT NOT NULL DEFAULT ''",
        "rating": "INTEGER NOT NULL DEFAULT 0",
        "note": "TEXT NOT NULL DEFAULT ''",
    }
    for name, declaration in additions.items():
        if name not in existing:
            db.execute(f"ALTER TABLE quick_draft_history ADD COLUMN {name} {declaration}")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS quick_draft_jobs (
          job_id TEXT PRIMARY KEY,
          draft_id INTEGER NOT NULL REFERENCES quick_draft_history(id),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_quick_draft_jobs_draft
          ON quick_draft_jobs(draft_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS quick_image_ratings (
          job_id TEXT NOT NULL,
          variant INTEGER NOT NULL,
          rating INTEGER NOT NULL CHECK(rating BETWEEN 0 AND 5),
          note TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(job_id,variant)
        );
        CREATE TABLE IF NOT EXISTS quick_catalog_migrations (
          key TEXT PRIMARY KEY
        );
    """)
    # Once only, match earlier successful/failed quick generations by exact prompt.
    # History is not replaced. Previously unrecorded prompts become their own records.
    if db.execute("SELECT 1 FROM quick_catalog_migrations WHERE key='legacy_jobs_v1'").fetchone():
        return
    folder = data / "jobs"
    if folder.is_dir():
        for job_dir in folder.iterdir():
            if not job_dir.is_dir() or not _ID.fullmatch(job_dir.name):
                continue
            try:
                spec=json.loads((job_dir/"spec.json").read_text(encoding="utf-8"))
            except (OSError,ValueError):
                continue
            if not isinstance(spec,dict) or spec.get("source")!="quick":
                continue
            positive=str(spec.get("prompt") or "")
            negative=str(spec.get("negative_prompt") or "")
            if not positive.strip():
                continue
            row=db.execute("""SELECT id FROM quick_draft_history
                WHERE prompt=? AND negative_prompt=? ORDER BY id DESC LIMIT 1""",
                (positive,negative)).fetchone()
            if row:
                draft_id=row[0]
            else:
                draft_id=db.execute("""INSERT INTO quick_draft_history(prompt,negative_prompt)
                    VALUES(?,?)""",(positive,negative)).lastrowid
            db.execute("""INSERT OR IGNORE INTO quick_draft_jobs(draft_id,job_id)
                VALUES(?,?)""",(draft_id,job_dir.name))
    db.execute("INSERT OR IGNORE INTO quick_catalog_migrations(key) VALUES('legacy_jobs_v1')")


def link_job(db, draft_id: int, job_id: str):
    if not _ID.fullmatch(job_id):
        raise ValueError("Invalid job identifier")
    db.execute("INSERT OR IGNORE INTO quick_draft_jobs(draft_id,job_id) VALUES(?,?)",
               (draft_id,job_id))


def _safe_param_int(s, default, low, high):
    try:
        n=int(s)
    except (ValueError,TypeError):
        n=default
    return max(low,min(high,n))


def register(app, connection, data, ollama_url, ollama_model, current_job, get_job):
    """Uses only the existing Flask server and SQLite DB."""
    def lookup(draft_id):
        with connection() as db:
            row=db.execute("""SELECT id,title,prompt,negative_prompt,prompt_ru,
                negative_prompt_ru,created_at,rating,note FROM quick_draft_history
                WHERE id=?""",(draft_id,)).fetchone()
        return dict(row) if row else None

    @app.get("/api/quick/catalog")
    def catalog_search():
        query=(request.args.get("q") or "").strip()[:150]
        order=request.args.get("sort","newest")
        min_rating=_safe_param_int(request.args.get("rating"),0,0,5)
        page=_safe_param_int(request.args.get("page"),1,1,999999)
        page_size=_safe_param_int(request.args.get("size"),8,1,30)
        has_images=request.args.get("images")=="1"
        where=["d.rating>=?"]
        args=[min_rating]
        if query:
            where.append("""(d.title LIKE ? OR d.prompt LIKE ? OR
                d.negative_prompt LIKE ? OR d.prompt_ru LIKE ? OR
                d.negative_prompt_ru LIKE ? OR d.note LIKE ?)""")
            args.extend(["%"+query+"%"]*6)
        if has_images:
            where.append("EXISTS(SELECT 1 FROM quick_draft_jobs j WHERE j.draft_id=d.id)")
        clause=" AND ".join(where)
        order_by={"newest":"d.id DESC", "oldest":"d.id ASC",
                  "rating":"d.rating DESC,d.id DESC"}.get(order,"d.id DESC")
        with connection() as db:
            total=db.execute(f"SELECT COUNT(*) FROM quick_draft_history d WHERE {clause}",args).fetchone()[0]
            rows=db.execute(f"""SELECT d.id,d.title,d.created_at,d.rating,
                substr(d.prompt,1,155) AS preview,
                substr(d.prompt_ru,1,155) AS preview_ru,
                (d.prompt_ru IS NOT NULL AND d.negative_prompt_ru IS NOT NULL) AS translated,
                (SELECT COUNT(*) FROM quick_draft_jobs j WHERE j.draft_id=d.id) AS jobs
                FROM quick_draft_history d WHERE {clause}
                ORDER BY {order_by} LIMIT ? OFFSET ?""",
                [*args,page_size,(page-1)*page_size]).fetchall()
        return jsonify(drafts=[dict(row) for row in rows],total=total,page=page,
                       size=page_size,pages=max(1,(total+page_size-1)//page_size))

    @app.get("/api/quick/catalog/<int:draft_id>")
    def catalog_details(draft_id):
        item=lookup(draft_id)
        if not item:
            return jsonify(error="Draft not found"),404
        with connection() as db:
            links=db.execute("""SELECT job_id FROM quick_draft_jobs
                WHERE draft_id=? ORDER BY created_at DESC, rowid DESC LIMIT 50""",
                (draft_id,)).fetchall()
            reviews=db.execute("""SELECT r.job_id,r.variant,r.rating,r.note
                FROM quick_image_ratings r JOIN quick_draft_jobs j ON j.job_id=r.job_id
                WHERE j.draft_id=?""",(draft_id,)).fetchall()
        grades={(r["job_id"],r["variant"]):dict(r) for r in reviews}
        item["jobs"]=[]
        for link in links:
            job_id=link["job_id"]
            if not _ID.fullmatch(job_id):
                continue
            state=get_job(job_id) or {}
            result={"job_id":job_id,"status":state.get("status","unknown"),"images":[]}
            for output in state.get("outputs",[])[:48]:
                try:
                    variant=int(output["variant"])
                except (ValueError,KeyError,TypeError):
                    continue
                if not 1<=variant<=48:
                    continue
                image=Path(str(output.get("png8") or "")).resolve()
                expected=(data/"jobs"/job_id/"images").resolve()
                if image.parent!=expected or not image.is_file():
                    continue
                score=grades.get((job_id,variant),{})
                result["images"].append({
                    "variant":variant,
                    "url":f"/api/jobs/{job_id}/images/{variant}",
                    "rating":score.get("rating",0),"note":score.get("note","")
                })
            item["jobs"].append(result)
        with _TRANSLATE_LOCK:
            item["translating"]=draft_id in _TRANSLATING
        return jsonify(item)

    @app.patch("/api/quick/catalog/<int:draft_id>")
    def catalog_edit(draft_id):
        payload=request.get_json(silent=True) or {}
        allowed={"title","rating","note"}
        changes={}
        if "title" in payload:
            changes["title"]=str(payload["title"] or "").strip()[:140]
        if "note" in payload:
            changes["note"]=str(payload["note"] or "").strip()[:900]
        if "rating" in payload:
            try:
                score=int(payload["rating"])
            except (TypeError,ValueError):
                return jsonify(error="Rating must be 0..5"),400
            if score not in range(6):
                return jsonify(error="Rating must be 0..5"),400
            changes["rating"]=score
        if not changes:
            return jsonify(error="Nothing to update"),400
        with connection() as db:
            if not db.execute("SELECT 1 FROM quick_draft_history WHERE id=?",
                              (draft_id,)).fetchone():
                return jsonify(error="Draft not found"),404
            db.execute("UPDATE quick_draft_history SET "+
                       ", ".join(f"{k}=?" for k in changes)+" WHERE id=?",
                       [*changes.values(),draft_id])
        return jsonify(saved=True,id=draft_id)

    @app.patch("/api/quick/images/<job_id>/<int:variant>/rating")
    def image_rating(job_id,variant):
        if not _ID.fullmatch(job_id) or not 1<=variant<=48:
            return jsonify(error="Invalid job or variant"),400
        payload=request.get_json(silent=True) or {}
        try:
            rating=int(payload.get("rating",0))
        except (TypeError,ValueError):
            return jsonify(error="Rating must be 0..5"),400
        if rating not in range(6):
            return jsonify(error="Rating must be 0..5"),400
        note=str(payload.get("note") or "").strip()[:500]
        state=get_job(job_id) or {}
        if not any(output.get("variant")==variant for output in state.get("outputs",[])):
            return jsonify(error="Image not found"),404
        with connection() as db:
            if not db.execute("SELECT 1 FROM quick_draft_jobs WHERE job_id=?",
                              (job_id,)).fetchone():
                return jsonify(error="Image is not linked to a draft"),404
            db.execute("""INSERT INTO quick_image_ratings(job_id,variant,rating,note)
                VALUES(?,?,?,?) ON CONFLICT(job_id,variant)
                DO UPDATE SET rating=excluded.rating,note=excluded.note""",
                (job_id,variant,rating,note))
        return jsonify(saved=True,job_id=job_id,variant=variant,rating=rating)

    def try_existing_translation(draft_id, row):
        if row["prompt_ru"] is not None and row["negative_prompt_ru"] is not None:
            return True
        with connection() as db:
            other=db.execute("""SELECT prompt_ru,negative_prompt_ru
              FROM quick_draft_history WHERE prompt=? AND negative_prompt=?
                AND prompt_ru IS NOT NULL AND negative_prompt_ru IS NOT NULL
              ORDER BY id DESC LIMIT 1""",
              (row["prompt"],row["negative_prompt"])).fetchone()
            if other:
                db.execute("""UPDATE quick_draft_history SET prompt_ru=?,negative_prompt_ru=?
                  WHERE id=? AND prompt_ru IS NULL""",
                  (other["prompt_ru"],other["negative_prompt_ru"],draft_id))
                return True
        return False

    def do_translation(draft_id,model,prompt,negative):
        try:
            if current_job():
                return
            response=requests.post(ollama_url+"/api/chat",json={
                "model":model,"stream":False,"format":"json","keep_alive":"0s",
                "options":{"temperature":0},
                "messages":[
                    {"role":"system","content":
                     "Translate two image generation prompts faithfully to Russian. "
                     "Return JSON strings prompt_ru and negative_prompt_ru only. "
                     "Preserve proper names, syntax, and technical commands. Do not invent content."},
                    {"role":"user","content":json.dumps({
                        "prompt":prompt,"negative_prompt":negative},ensure_ascii=False)}
                ]
            },timeout=180)
            response.raise_for_status()
            result=json.loads(response.json()["message"]["content"])
            pos=str(result.get("prompt_ru") or "").strip()[:16000]
            neg=str(result.get("negative_prompt_ru") or "").strip()[:4000]
            if prompt.strip() and not pos:
                return
            if negative.strip() and not neg:
                return
            with connection() as db:
                db.execute("""UPDATE quick_draft_history
                    SET prompt_ru=?, negative_prompt_ru=?
                    WHERE id=? AND prompt=? AND negative_prompt=?""",
                    (pos,neg,draft_id,prompt,negative))
        except (requests.RequestException,ValueError,KeyError,OSError):
            # Missing translation remains empty; reopening the draft can retry.
            return
        finally:
            with _TRANSLATE_LOCK:
                _TRANSLATING.discard(draft_id)

    def queue_translation(draft_id,model=None):
        row=lookup(draft_id)
        if not row:
            return {"error":"Draft not found"},404
        if try_existing_translation(draft_id,row):
            return {"status":"ready","cached":True},200
        # No additional GPU workload during an active render, no persistent daemon.
        if current_job():
            return {"status":"deferred","note":"Translation postponed until GPU is idle"},202
        selected=model or ollama_model
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{2,128}",selected):
            return {"error":"Invalid Ollama model"},400
        with _TRANSLATE_LOCK:
            if draft_id in _TRANSLATING:
                return {"status":"translating"},202
            _TRANSLATING.add(draft_id)
        threading.Thread(target=do_translation,
                         args=(draft_id,selected,row["prompt"],row["negative_prompt"]),
                         daemon=True,name="draft-translation").start()
        return {"status":"translating"},202

    @app.post("/api/quick/catalog/<int:draft_id>/translate")
    def catalog_auto_translate(draft_id):
        result,status=queue_translation(draft_id)
        return jsonify(result),status

    # Called only for *explicit* manual Save, not every keystroke or each GPU job.
    return queue_translation
