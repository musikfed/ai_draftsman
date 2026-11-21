"""Searchable, durable draft catalog + real output ratings. No model imports or services."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
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
        "archived": "INTEGER NOT NULL DEFAULT 0",
        "parent_draft_id": "INTEGER",
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
        CREATE TABLE IF NOT EXISTS quick_result_index (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id TEXT NOT NULL,
          variant INTEGER NOT NULL,
          UNIQUE(job_id,variant)
        );
        CREATE TABLE IF NOT EXISTS quick_translation_attempts (
          draft_id INTEGER PRIMARY KEY,
          attempted_at TEXT NOT NULL,
          failed INTEGER NOT NULL DEFAULT 0
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


def register(app, connection, data_source, ollama_url, ollama_model, current_job, get_job):
    """Uses only the existing Flask server and SQLite DB."""
    def data_root():
        return data_source() if callable(data_source) else data_source
    def lookup(draft_id):
        with connection() as db:
            row=db.execute("""SELECT id,title,prompt,negative_prompt,prompt_ru,
                negative_prompt_ru,created_at,rating,note,archived,parent_draft_id FROM quick_draft_history
                WHERE id=?""",(draft_id,)).fetchone()
        if not row:
            return None
        item=dict(row)
        if not item["title"].strip():
            source=(item.get("prompt_ru") or item.get("prompt") or "Без описания").strip()
            item["title"]=f"Эскиз #{draft_id:05d} · "+source[:56]
        return item

    @app.get("/api/quick/catalog")
    def catalog_search():
        query=(request.args.get("q") or "").strip()[:150]
        order=request.args.get("sort","newest")
        min_rating=_safe_param_int(request.args.get("rating"),0,0,5)
        page=_safe_param_int(request.args.get("page"),1,1,999999)
        page_size=_safe_param_int(request.args.get("size"),8,1,30)
        has_images=request.args.get("images")=="1"
        archive_filter=request.args.get("archive","active")
        where=["d.rating>=?"]
        if archive_filter=="active":
            where.append("d.archived=0")
        elif archive_filter=="archived":
            where.append("d.archived=1")
        args=[min_rating]
        if query:
            if re.fullmatch(r"#[0-9]{1,9}",query):
                where.append("d.id=?")
                args.append(int(query[1:]))
            else:
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
            rows=db.execute(f"""SELECT d.id,d.title,d.created_at,d.rating,d.archived,d.parent_draft_id,
                substr(d.prompt,1,155) AS preview,
                substr(d.prompt_ru,1,155) AS preview_ru,
                (d.prompt_ru IS NOT NULL AND d.negative_prompt_ru IS NOT NULL) AS translated,
                (SELECT COUNT(*) FROM quick_draft_jobs j WHERE j.draft_id=d.id) AS jobs
                FROM quick_draft_history d WHERE {clause}
                ORDER BY {order_by} LIMIT ? OFFSET ?""",
                [*args,page_size,(page-1)*page_size]).fetchall()
        items=[dict(row) for row in rows]
        for item in items:
            if not item["title"].strip():
                source=(item.get("preview_ru") or item.get("preview") or "Без описания").strip()
                item["title"]=f"Эскиз #{item['id']:05d} · "+source[:56]
        return jsonify(drafts=items,total=total,page=page,
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
                expected=(data_root()/"jobs"/job_id/"images").resolve()
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

    @app.get("/api/quick/results")
    def catalog_results():
        """Stable result IDs, original PNG paths, no copied images or repeated GPU tasks."""
        query=(request.args.get("q") or "").strip()[:150]
        archived=request.args.get("archive","all")
        order=request.args.get("sort","newest")
        page=_safe_param_int(request.args.get("page"),1,1,99999)
        size=_safe_param_int(request.args.get("size"),12,1,36)
        where=["1=1"]
        args=[]
        if archived=="active":
            where.append("d.archived=0")
        elif archived=="archived":
            where.append("d.archived=1")
        if query:
            where.append("""(d.title LIKE ? OR d.prompt LIKE ? OR
                d.negative_prompt LIKE ? OR d.prompt_ru LIKE ? OR d.note LIKE ?)""")
            args.extend(["%"+query+"%"]*5)
        with connection() as db:
            rows=db.execute(f"""SELECT j.job_id,j.draft_id,d.title,d.prompt,
                d.prompt_ru,d.archived,j.created_at
                FROM quick_draft_jobs j JOIN quick_draft_history d ON d.id=j.draft_id
                WHERE {" AND ".join(where)} ORDER BY j.rowid DESC LIMIT 2000""",args).fetchall()
            info=[dict(row) for row in rows]
            ratings=db.execute("SELECT job_id,variant,rating FROM quick_image_ratings").fetchall()
        scores={(row["job_id"],row["variant"]):row["rating"] for row in ratings}
        results=[]
        root=(data_root()/"jobs").resolve()
        for row in info:
            job_id=row["job_id"]
            if not _ID.fullmatch(job_id):continue
            state=get_job(job_id) or {}
            if state.get("status")!="completed":continue
            for output in state.get("outputs",[])[:48]:
                try:
                    variant=int(output["variant"])
                except (ValueError,TypeError,KeyError):
                    continue
                if not 1<=variant<=48:continue
                picture=Path(str(output.get("png8") or "")).resolve()
                if picture.parent!=(root/job_id/"images").resolve() or not picture.is_file():
                    continue
                title=row["title"].strip() if row["title"] else ""
                if not title:
                    base=(row["prompt_ru"] or row["prompt"] or "Рисунок").strip()
                    title=base[:75] or "Без названия"
                results.append({
                    "job_id":job_id,"variant":variant,"draft_id":row["draft_id"],
                    "title":title,"archived":bool(row["archived"]),
                    "image_url":f"/api/jobs/{job_id}/images/{variant}",
                    "rating":scores.get((job_id,variant),0),
                    "created_at":state.get("finished_at") or state.get("created_at") or 0,
                    "seed":output.get("seed")
                })
        # Image identity is immutable even when the user generates a new version.
        # Indexing stores only job_id+variant; the actual PNG remains in data/jobs.
        with connection() as db:
            for item in results:
                db.execute("""INSERT OR IGNORE INTO quick_result_index(job_id,variant)
                    VALUES(?,?)""",(item["job_id"],item["variant"]))
            keys={(row["job_id"],row["variant"]):row["id"] for row in
                db.execute("SELECT id,job_id,variant FROM quick_result_index")}
        for item in results:
            item["index"]=keys[(item["job_id"],item["variant"])]
        if order=="rating":
            results.sort(key=lambda r:(r["rating"],r["created_at"]),reverse=True)
        elif order=="oldest":
            results.sort(key=lambda r:(r["created_at"],r["index"]))
        else:
            results.sort(key=lambda r:(r["created_at"],r["index"]),reverse=True)
        count=len(results)
        return jsonify(results=results[(page-1)*size:page*size],
                       total=count,page=page,size=size,
                       pages=max(1,(count+size-1)//size))


    @app.post("/api/quick/catalog/<int:draft_id>/archive")
    def catalog_archive(draft_id):
        payload=request.get_json(silent=True) or {}
        if type(payload.get("archived")) is not bool:
            return jsonify(error="archived must be true or false"),400
        archived=1 if payload["archived"] else 0
        with connection() as db:
            item=db.execute("SELECT 1 FROM quick_draft_history WHERE id=?",
                            (draft_id,)).fetchone()
            if not item:
                return jsonify(error="Draft not found"),404
            db.execute("UPDATE quick_draft_history SET archived=? WHERE id=?",
                       (archived,draft_id))
        return jsonify(saved=True,id=draft_id,archived=bool(archived))

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
            row=db.execute("SELECT archived FROM quick_draft_history WHERE id=?",
                           (draft_id,)).fetchone()
            if row is None:
                return jsonify(error="Draft not found"),404
            if row["archived"]:
                return jsonify(error="Archived draft is read-only; unlock it explicitly before editing"),409
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
            row=db.execute("""SELECT d.archived FROM quick_draft_jobs j
                JOIN quick_draft_history d ON d.id=j.draft_id
                WHERE j.job_id=?""",(job_id,)).fetchone()
            if row is None:
                return jsonify(error="Image is not linked to a draft"),404
            if row["archived"]:
                return jsonify(error="Archived result is read-only"),409
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
                db.execute("UPDATE quick_translation_attempts SET failed=0 WHERE draft_id=?",
                           (draft_id,))
        except (requests.RequestException,ValueError,KeyError,OSError):
            with connection() as db:
                db.execute("UPDATE quick_translation_attempts SET failed=1 WHERE draft_id=?",
                           (draft_id,))
            return
        finally:
            with _TRANSLATE_LOCK:
                _TRANSLATING.discard(draft_id)

    def queue_translation(draft_id,model=None):
        row=lookup(draft_id)
        if not row:
            return {"error":"Draft not found"},404
        if row["archived"]:
            return {"status":"read_only","note":"Archived drafts are immutable"},200
        if try_existing_translation(draft_id,row):
            return {"status":"ready","cached":True},200
        def already_russian(text):
            if not text.strip():return True
            cyr=len(re.findall(r"[А-Яа-яЁё]",text))
            latin=len(re.findall(r"[A-Za-z]",text))
            return cyr>=max(5,latin)
        if already_russian(row["prompt"]) and already_russian(row["negative_prompt"]):
            with connection() as db:
                db.execute("""UPDATE quick_draft_history
                    SET prompt_ru=prompt,negative_prompt_ru=negative_prompt WHERE id=?""",
                    (draft_id,))
            return {"status":"ready","cached":True,"source":"already_russian"},200
        # No additional GPU workload during an active render, no persistent daemon.
        if current_job():
            return {"status":"deferred","note":"Translation postponed until GPU is idle"},202
        selected=model or ollama_model
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{2,128}",selected):
            return {"error":"Invalid Ollama model"},400
        with connection() as db:
            last=db.execute("""SELECT attempted_at,failed FROM quick_translation_attempts
                WHERE draft_id=?""",(draft_id,)).fetchone()
            if last and last["failed"]:
                try:
                    previous=datetime.fromisoformat(last["attempted_at"])
                    if datetime.now(timezone.utc)-previous < timedelta(hours=1):
                        return {"status":"retry_later","note":"Failed translation is cached for 1 hour"},202
                except (ValueError,TypeError):
                    pass
            db.execute("""INSERT INTO quick_translation_attempts(draft_id,attempted_at,failed)
                VALUES(?,?,0) ON CONFLICT(draft_id) DO UPDATE SET
                attempted_at=excluded.attempted_at,failed=0""",
                (draft_id,datetime.now(timezone.utc).isoformat()))
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
