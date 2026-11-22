"""Generic project / node / edge studio with optional Ollama, without heavy GPU imports."""
from __future__ import annotations

import io
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import requests
from flask import jsonify, request
from studio.jobs import submit_job, current_job
from studio.checkpoints import CHECKPOINTS, DEFAULT_CHECKPOINT
from studio.parameters import choose_variants, MAX_VARIANTS
from studio.graph_templates import initialize_templates, list_templates, get_template

PULL_STATE = {"status": "idle", "model": "", "message": "", "completed": 0, "total": 0}
PULL_LOCK = threading.Lock()
KINDS = ("scene", "character", "style", "prompt", "reference", "note", "output", "lesson", "slide")
STATES = ("draft", "approved")
EDITABLE_NODE = ("title", "kind", "notes", "prompt", "negative_prompt", "status", "x", "y")
EDITABLE_PROJECT = ("name", "description", "base_prompt", "negative_prompt", "system_prompt", "llm_model")


def register(app, db_path: Path, data_dir: Path, ollama_url: str, default_model: str, canon: list):
    def db():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS studio_projects (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            base_prompt TEXT NOT NULL DEFAULT '',
            negative_prompt TEXT NOT NULL DEFAULT '',
            system_prompt TEXT NOT NULL DEFAULT '',
            llm_model TEXT NOT NULL DEFAULT 'qwen3:8b',
            kind TEXT NOT NULL DEFAULT 'general',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS studio_nodes (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'scene',
            notes TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '',
            negative_prompt TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
            x INTEGER NOT NULL DEFAULT 30, y INTEGER NOT NULL DEFAULT 30,
            last_job TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS studio_edges (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
            source INTEGER NOT NULL REFERENCES studio_nodes(id) ON DELETE CASCADE,
            target INTEGER NOT NULL REFERENCES studio_nodes(id) ON DELETE CASCADE,
            UNIQUE(project_id,source,target)
        );
        CREATE INDEX IF NOT EXISTS idx_studio_node_project ON studio_nodes(project_id);
        CREATE INDEX IF NOT EXISTS idx_studio_edge_project ON studio_edges(project_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS studio_knowledge USING fts5(
            project_id UNINDEXED, source, content
        );
        """)
        initialize_templates(c)

    def fetch_project(connection, project_id):
        row = connection.execute(
            "SELECT * FROM studio_projects WHERE id=?", (project_id,)
        ).fetchone()
        return dict(row) if row else None

    def node_for_project(connection, project_id, node_id):
        return connection.execute(
            "SELECT * FROM studio_nodes WHERE id=? AND project_id=?",
            (node_id, project_id)
        ).fetchone()

    def graph_context(connection, project_id, node_id):
        """Deterministic parent traversal, bounded and protected from cycles."""
        nodes = {
            row["id"]: dict(row) for row in connection.execute(
                "SELECT * FROM studio_nodes WHERE project_id=?", (project_id,)
            )
        }
        edges = [
            (x["source"], x["target"]) for x in connection.execute(
                "SELECT source,target FROM studio_edges WHERE project_id=?", (project_id,)
            )
        ]
        parents = {}
        for src, dst in edges:
            parents.setdefault(dst, []).append(src)
        visited = {node_id}
        queue = [(node_id, 0)]
        contexts = []
        while queue and len(contexts) < 16:
            current, depth = queue.pop(0)
            if depth >= 5:
                continue
            for p in sorted(parents.get(current, [])):
                if p in visited or p not in nodes:
                    continue
                visited.add(p)
                info = nodes[p]
                contexts.append(f'{info["kind"]} «{info["title"]}»: '
                                f'{info["notes"][:500]}; {info["prompt"][:500]}')
                queue.append((p, depth + 1))
        return "\n".join(reversed(contexts))

    def assemble(connection, project_id, node_id):
        project = fetch_project(connection, project_id)
        node = node_for_project(connection, project_id, node_id)
        if project is None or node is None:
            return None
        context = graph_context(connection, project_id, node_id)
        positive = "\n\n".join(filter(None, [
            project["base_prompt"].strip(),
            ("Project: " + project["name"] + ". " + project["description"]).strip(),
            "Related graph context:\n" + context if context else "",
            "Current node " + node["kind"] + ": " + node["title"],
            node["notes"].strip(),
            node["prompt"].strip()
        ]))
        negative = ", ".join(filter(None, [
            project["negative_prompt"].strip(), node["negative_prompt"].strip()
        ]))
        return project, dict(node), positive[:16000], negative[:4000], context

    def knowledge(connection, project_id, query, limit=4):
        terms = re.findall(r"[\w-]{3,}", query, flags=re.UNICODE)[:8]
        if not terms:
            return []
        expression = " OR ".join('"' + t.replace('"', '') + '"' for t in terms)
        try:
            return [
                dict(x) for x in connection.execute(
                    "SELECT source,content FROM studio_knowledge "
                    "WHERE studio_knowledge MATCH ? AND project_id=? LIMIT ?",
                    (expression, str(project_id), limit)
                )
            ]
        except sqlite3.OperationalError:
            return []

    @app.get("/api/studio/templates")
    def studio_graph_template_catalog():
        """Seven built-in, database-backed graph examples; no projects created."""
        with db() as c:
            result = list_templates(c)
        return jsonify(templates=result)

    @app.get("/api/studio/templates/<template_id>")
    def studio_graph_template_preview(template_id):
        """Return the editable example structure before project creation."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,80}",template_id):
            return jsonify(error="Invalid template ID"),400
        with db() as c:
            definition=get_template(c,template_id)
        if not definition:
            return jsonify(error="Unknown graph template"),404
        return jsonify(template=definition)

    @app.get("/api/studio/projects")
    def studio_projects():
        with db() as c:
            projects = [
                dict(x) for x in c.execute(
                    "SELECT * FROM studio_projects ORDER BY id DESC"
                )
            ]
        return jsonify(projects=projects)

    @app.post("/api/studio/projects")
    def studio_create_project():
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name", "Новый проект")).strip()[:100]
        template = str(payload.get("template", "blank"))
        if not name:
            return jsonify(error="Invalid project name"), 400
        blueprint = None
        if template not in ("blank","karate"):
            if not re.fullmatch(r"[a-z][a-z0-9_]{2,80}",template):
                return jsonify(error="Invalid project template"),400
            with db() as c:
                blueprint = get_template(c,template)
            if blueprint is None:
                return jsonify(error="Unknown graph template"),400
        description = str(payload.get("description", ""))[:5000]
        style = ""
        system = ""
        negative = ""
        if blueprint is not None:
            description = description or blueprint["summary_ru"]
            style = blueprint["base_prompt"]
            negative = blueprint["negative_prompt"]
            system = blueprint["system_prompt"]
        if template == "karate":
            description = description or ("Educational comedy manga series, 24 lessons about Linux, "
                                          "Docker and PostgreSQL; five sequential slides per lesson.")
            style = ("Dynamic colorful manga comic, crisp ink outlines, blue and orange lighting, "
                     "winter Moscow, Grep Paip: clean-shaven young engineer with PL cap and orange "
                     "glasses wearing current belt; ROOT: actual penguin sensei in dark kimono; "
                     "PostgreSQL elephant blue with large ears; clear panel composition.")
            negative = "beard, moustache, ROOT as human, wrong karate belt, illegible text, watermark"
            system = ("Follow the confirmed Karate Linux continuity and linked graph scenes. "
                      "Grep has green belt in lessons 013–015. ROOT is a real penguin. "
                      "Five sequential slides are not five variants. "
                      "Keep Russian dialogue outside image prompts for later lettering. "
                      "Never recommend deleting PostgreSQL pg_wal manually.")
        with db() as c:
            cur = c.execute(
                "INSERT INTO studio_projects(name,description,kind,llm_model,"
                "base_prompt,negative_prompt,system_prompt) VALUES(?,?,?,?,?,?,?)",
                (name, description, "karate" if template == "karate" else
                 (template if blueprint is not None else "general"),
                 default_model, style, negative, system)
            )
            pid = cur.lastrowid
            if blueprint is not None:
                node_ids = {}
                for item in blueprint["nodes"]:
                    created = c.execute(
                        "INSERT INTO studio_nodes "
                        "(project_id,title,kind,notes,prompt,negative_prompt,status,x,y) "
                        "VALUES(?,?,?,?,?,?,'draft',?,?)",
                        (pid,item["title"],item["kind"],item["notes"],
                         item["prompt"],item.get("negative_prompt",""),
                         item["x"],item["y"])
                    )
                    node_ids[item["key"]] = created.lastrowid
                for source, target in blueprint["edges"]:
                    c.execute(
                        "INSERT INTO studio_edges(project_id,source,target) VALUES(?,?,?)",
                        (pid,node_ids[source],node_ids[target])
                    )
            if template == "karate":
                ids = []
                for index, entry in enumerate(canon):
                    item = c.execute(
                        "INSERT INTO studio_nodes(project_id,title,kind,notes,x,y) "
                        "VALUES(?,?,?,?,?,?)",
                        (pid, f'{entry["id"]:03d} — {entry["title"]}', "lesson",
                         entry["story"], 35 + (index % 6) * 230, 35 + (index // 6) * 140)
                    )
                    ids.append(item.lastrowid)
                for src, target in zip(ids, ids[1:]):
                    c.execute(
                        "INSERT INTO studio_edges(project_id,source,target) VALUES(?,?,?)",
                        (pid, src, target)
                    )
        return jsonify(project_id=pid), 201

    @app.delete("/api/studio/projects/<int:project_id>")
    def studio_delete_project(project_id):
        """Explicit delete of one project; legacy comic tables remain untouched."""
        with db() as c:
            if not fetch_project(c, project_id):
                return jsonify(error="Project not found"), 404
            c.execute("DELETE FROM studio_knowledge WHERE project_id=?", (str(project_id),))
            c.execute("DELETE FROM studio_projects WHERE id=?", (project_id,))
        return jsonify(deleted=True)


    @app.get("/api/studio/projects/<int:project_id>")
    def studio_read_project(project_id):
        with db() as c:
            project = fetch_project(c, project_id)
            if not project:
                return jsonify(error="Project not found"), 404
            nodes = [dict(x) for x in c.execute(
                "SELECT * FROM studio_nodes WHERE project_id=? ORDER BY id", (project_id,)
            )]
            edges = [dict(x) for x in c.execute(
                "SELECT * FROM studio_edges WHERE project_id=? ORDER BY id", (project_id,)
            )]
        return jsonify(project=project, nodes=nodes, edges=edges)

    @app.patch("/api/studio/projects/<int:project_id>")
    def studio_update_project(project_id):
        data = request.get_json(silent=True) or {}
        patch = {k: str(data[k])[:16000] for k in EDITABLE_PROJECT if k in data}
        if "name" in patch and not patch["name"].strip():
            return jsonify(error="Project name cannot be blank"), 400
        if not patch:
            return jsonify(error="Nothing to update"), 400
        with db() as c:
            if not fetch_project(c, project_id):
                return jsonify(error="Project not found"), 404
            c.execute("UPDATE studio_projects SET " +
                      ", ".join(k + "=?" for k in patch) +
                      " WHERE id=?", (*patch.values(), project_id))
        return jsonify(saved=True)

    @app.post("/api/studio/projects/<int:project_id>/nodes")
    def studio_add_node(project_id):
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "Новый узел")).strip()[:140]
        kind = str(data.get("kind", "scene"))
        if not title or kind not in KINDS:
            return jsonify(error="Invalid title or node type"), 400
        try:
            x = max(0, min(int(data.get("x", 45)), 5000))
            y = max(0, min(int(data.get("y", 45)), 5000))
        except (TypeError, ValueError):
            return jsonify(error="Invalid coordinates"), 400
        with db() as c:
            if not fetch_project(c, project_id):
                return jsonify(error="Project not found"), 404
            cur = c.execute(
                "INSERT INTO studio_nodes(project_id,title,kind,x,y) VALUES(?,?,?,?,?)",
                (project_id, title, kind, x, y)
            )
        return jsonify(node_id=cur.lastrowid), 201

    @app.patch("/api/studio/projects/<int:project_id>/nodes/<int:node_id>")
    def studio_save_node(project_id, node_id):
        data = request.get_json(silent=True) or {}
        patch = {k: data[k] for k in EDITABLE_NODE if k in data}
        if not patch:
            return jsonify(error="Nothing to update"), 400
        if "kind" in patch and patch["kind"] not in KINDS:
            return jsonify(error="Invalid node kind"), 400
        if "status" in patch and patch["status"] not in STATES:
            return jsonify(error="Invalid node status"), 400
        for key in ("x", "y"):
            if key in patch:
                try:
                    patch[key] = max(0, min(int(patch[key]), 5000))
                except (ValueError, TypeError):
                    return jsonify(error="Invalid coordinates"), 400
        for key in patch.keys() - {"x", "y"}:
            patch[key] = str(patch[key])[:16000]
        if "title" in patch and not patch["title"].strip():
            return jsonify(error="Title cannot be blank"), 400
        with db() as c:
            if not node_for_project(c, project_id, node_id):
                return jsonify(error="Node not found"), 404
            c.execute(
                "UPDATE studio_nodes SET " + ", ".join(k+"=?" for k in patch) +
                " WHERE project_id=? AND id=?",
                (*patch.values(), project_id, node_id)
            )
        return jsonify(saved=True)

    @app.delete("/api/studio/projects/<int:project_id>/nodes/<int:node_id>")
    def studio_delete_node(project_id, node_id):
        with db() as c:
            cur = c.execute(
                "DELETE FROM studio_nodes WHERE id=? AND project_id=?", (node_id, project_id)
            )
        return jsonify(deleted=bool(cur.rowcount))

    @app.post("/api/studio/projects/<int:project_id>/edges")
    def studio_add_edge(project_id):
        p = request.get_json(silent=True) or {}
        try:
            source, target = int(p["source"]), int(p["target"])
        except (ValueError, KeyError, TypeError):
            return jsonify(error="Select source and target"), 400
        if source == target:
            return jsonify(error="No self links"), 400
        with db() as c:
            if (not node_for_project(c, project_id, source) or
                not node_for_project(c, project_id, target)):
                return jsonify(error="Both nodes must be in this project"), 404
            try:
                cur = c.execute(
                    "INSERT INTO studio_edges(project_id,source,target) VALUES(?,?,?)",
                    (project_id, source, target)
                )
            except sqlite3.IntegrityError:
                return jsonify(error="Link already exists"), 409
        return jsonify(edge_id=cur.lastrowid), 201

    @app.delete("/api/studio/projects/<int:project_id>/edges/<int:edge_id>")
    def studio_delete_edge(project_id, edge_id):
        with db() as c:
            cur = c.execute("DELETE FROM studio_edges WHERE project_id=? AND id=?",
                            (project_id, edge_id))
        return jsonify(deleted=bool(cur.rowcount))

    @app.post("/api/studio/projects/<int:project_id>/lessons/<int:lesson_num>/expand")
    def studio_expand_legacy_lesson(project_id, lesson_num):
        if not 1 <= lesson_num <= len(canon):
            return jsonify(error="Unknown legacy lesson"), 400
        with db() as c:
            project = fetch_project(c, project_id)
            if not project or project["kind"] != "karate":
                return jsonify(error="This action requires Karate template"), 400
            node = c.execute(
                "SELECT * FROM studio_nodes WHERE project_id=? AND kind='lesson' "
                "AND title LIKE ? LIMIT 1",
                (project_id, f"{lesson_num:03d} — %")
            ).fetchone()
            if not node:
                return jsonify(error="Lesson node not found"), 404
            existing = c.execute(
                "SELECT count(*) FROM studio_nodes WHERE project_id=? AND kind='slide' "
                "AND title LIKE ?", (project_id, f"{lesson_num:03d}/%")
            ).fetchone()[0]
            if existing:
                return jsonify(error="Slides have already been imported"), 409
            prev = node["id"]
            created = []
            old = [dict(item) for item in c.execute(
                "SELECT * FROM slides WHERE lesson=? ORDER BY slide", (lesson_num,)
            )]
            # Fresh generic installs have no legacy slides; build five empty
            # editable slots only after the user explicitly imports a lesson.
            if not old:
                old = [
                    {"slide": n, "story": "", "prompt": "", "status": "planned"}
                    for n in range(1, 6)
                ]
            for row in old:
                cur = c.execute(
                    "INSERT INTO studio_nodes(project_id,title,kind,notes,prompt,status,x,y) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (project_id, f'{lesson_num:03d}/{row["slide"]:02d}', "slide",
                     row["story"], row["prompt"],
                     "approved" if row["status"] == "approved" else "draft",
                     node["x"] + 60 + row["slide"] * 205, node["y"] + 95)
                )
                n = cur.lastrowid
                created.append(n)
                c.execute("INSERT INTO studio_edges(project_id,source,target) VALUES(?,?,?)",
                          (project_id, prev, n))
                prev = n
        return jsonify(created=created)

    @app.get("/api/studio/projects/<int:project_id>/nodes/<int:node_id>/preview")
    def studio_preview(project_id, node_id):
        with db() as c:
            result = assemble(c, project_id, node_id)
        if not result:
            return jsonify(error="Node/project not found"), 404
        _, _, prompt, negative, context = result
        return jsonify(prompt=prompt, negative_prompt=negative, graph_context=context)

    @app.post("/api/studio/projects/<int:project_id>/knowledge")
    def studio_add_knowledge(project_id):
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith((".txt", ".md")):
            return jsonify(error="Upload UTF-8 TXT/MD only"), 400
        b = f.read(1000001)
        if len(b) > 1000000:
            return jsonify(error="Max 1 MB"), 413
        try:
            content = b.decode("utf-8")
        except UnicodeError:
            return jsonify(error="Use UTF-8"), 400
        with db() as c:
            if not fetch_project(c, project_id):
                return jsonify(error="Project not found"), 404
            chunks = [content[i:i+850] for i in range(0,len(content),850)]
            for chunk in chunks:
                c.execute(
                    "INSERT INTO studio_knowledge(project_id,source,content) VALUES(?,?,?)",
                    (str(project_id), Path(f.filename).name[:120], chunk)
                )
        return jsonify(chunks=len(chunks))

    @app.post("/api/studio/projects/<int:project_id>/nodes/<int:node_id>/ai")
    def studio_ai_draft(project_id, node_id):
        if current_job():
            return jsonify(error="GPU renderer busy; wait before starting Ollama draft"), 409
        with db() as c:
            item = assemble(c, project_id, node_id)
            if item:
                project, node, prompt, negative, context = item
                kb = knowledge(c, project_id, project["name"]+" "+node["title"]+" "+node["notes"])
        if not item:
            return jsonify(error="Project/node not found"), 404
        system = (
            "You are a helpful professional visual-design planner. "
            "Follow the user's project instructions and connected graph node order. "
            "Do not introduce unrelated genres, characters or story constraints. "
            "Return JSON with keys prompt, negative_prompt, explanation. "
            "The prompt must describe one image or visual scene, not alternatives. "
            "The explanation must be in the language of the project instructions. "
            + project["system_prompt"][:6000]
        )
        user = json.dumps({
            "project":project["name"], "brief":project["description"],
            "base_visual_style":project["base_prompt"], "node":dict(node),
            "related_nodes":context, "project_knowledge":kb,
            "existing_prompt":prompt, "existing_negative":negative
        }, ensure_ascii=False)
        try:
            resp=requests.post(ollama_url+"/api/chat",json={
                "model":project["llm_model"] or default_model,
                "stream":False, "format":"json","keep_alive":"0s",
                "messages":[{"role":"system","content":system},
                            {"role":"user","content":user}]
            },timeout=180)
            resp.raise_for_status()
            output=json.loads(resp.json()["message"]["content"])
            positive=str(output.get("prompt","")).strip()[:16000]
            neg=str(output.get("negative_prompt","")).strip()[:4000]
            if not positive:
                return jsonify(error="LLM did not return a valid prompt"), 422
            with db() as c:
                c.execute(
                    "UPDATE studio_nodes SET prompt=?,negative_prompt=?,status='draft' "
                    "WHERE project_id=? AND id=?",
                    (positive,neg,project_id,node_id)
                )
            return jsonify(saved=True, prompt=positive,negative_prompt=neg,
                           explanation=str(output.get("explanation",""))[:1500])
        except (requests.RequestException,ValueError,KeyError) as exc:
            return jsonify(error="Ollama error: "+str(exc)[:350]), 502

    @app.post("/api/studio/projects/<int:project_id>/nodes/<int:node_id>/generate")
    def studio_generate(project_id,node_id):
        active=current_job()
        if active is not None:
            return jsonify(error="GPU занят. Вторую генерацию в очередь не ставим.",
                           active_job_id=active.get("job_id")),409
        data = request.get_json(silent=True) or {}
        with db() as c:
            result = assemble(c,project_id,node_id)
        if not result:
            return jsonify(error="Project/node not found"),404
        project,node,prompt,negative,_=result
        if node["status"]!="approved" or not node["prompt"].strip():
            return jsonify(error="Save and approve the node prompt first"),409
        mode = str(data.get("mode","txt2img"))
        if mode not in ("txt2img","img2img"):
            return jsonify(error="Unsupported image mode"),400
        try:
            count=choose_variants(data.get("variants", "auto"), prompt)
            steps=int(data.get("steps",28))
            cfg=float(data.get("cfg",6.5))
            strength=float(data.get("strength",0.55))
            seed=int(data.get("seed",0)) or secrets.randbelow(2**31)
            width=int(data.get("width",768))
            height=int(data.get("height",960))
        except (TypeError,ValueError):
            return jsonify(error="Invalid image parameters"),400
        if not (1<=count<=MAX_VARIANTS and 10<=steps<=60 and 1<=cfg<=12
                and 0.15<=strength<=0.9 and 0<=seed<2**32
                and (width,height) in ((768,960),(896,1120))):
            return jsonify(error="Image parameters outside supported SDXL limits"),400
        reference = ""
        if mode=="img2img":
            ref=str(data.get("reference",""))
            if not re.fullmatch(r"[0-9a-f]{32}\.png",ref):
                return jsonify(error="Choose an uploaded image reference"),400
            file = (data_dir/"references"/ref).resolve()
            if file.parent!=(data_dir/"references").resolve() or not file.is_file():
                return jsonify(error="Reference missing"),404
            reference=str(file)
        lora=str(data.get("lora",""))
        if lora and (not re.fullmatch(r"[A-Za-z0-9_. -]{1,160}\.safetensors",lora)
                     or not (db_path.parent.parent/"models"/"loras"/lora).is_file()):
            # db_path is data/draftsman.db; parent.parent is repository root
            return jsonify(error="LoRA missing"),400
        model_id=str(data.get("checkpoint") or DEFAULT_CHECKPOINT)
        if model_id not in CHECKPOINTS:
            return jsonify(error="Unsupported SDXL image checkpoint"),400
        try:
            job_id=submit_job({
                "checkpoint":model_id,
                "lesson":project_id,"slide":node_id,"project_id":project_id,"node_id":node_id,
                "prompt":prompt,"negative_prompt":negative,
                "mode":mode,"variants":count,"seed":seed,"steps":steps,
                "cfg":cfg,"strength":strength,"width":width,"height":height,
                "reference":reference,"lora":lora,"lora_scale":0.7
            })
        except (OSError, FileNotFoundError, RuntimeError) as exc:
            active=current_job()
            if active is not None:
                return jsonify(error="GPU занят. Новое задание не поставлено в очередь.",
                               active_job_id=active.get("job_id")),409
            return jsonify(error=str(exc)),422
        with db() as c:
            c.execute(
                "UPDATE studio_nodes SET last_job=? WHERE id=? AND project_id=?",
                (job_id,node_id,project_id)
            )
        return jsonify(job_id=job_id,submitted=True),202

    @app.get("/api/studio/llm/status")
    def studio_llm_download_status():
        with PULL_LOCK:
            return jsonify(dict(PULL_STATE))

    @app.post("/api/studio/llm/pull")
    def studio_llm_pull():
        body=request.get_json(silent=True) or {}
        name=str(body.get("model","")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{2,128}",name):
            return jsonify(error="Invalid Ollama model name"),400
        with PULL_LOCK:
            if PULL_STATE["status"]=="running":
                return jsonify(error="A model is already downloading"),409
            PULL_STATE.update(status="running",model=name,message="Connecting to Ollama...",
                              completed=0,total=0)
        def run_pull():
            try:
                with requests.post(ollama_url+"/api/pull",json={
                    "model":name,"stream":True
                },stream=True,timeout=(8,180)) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        info=json.loads(line)
                        if "error" in info:
                            raise RuntimeError(info["error"])
                        with PULL_LOCK:
                            PULL_STATE.update(
                                status="running",message=str(info.get("status","Downloading")),
                                completed=int(info.get("completed",0)),
                                total=int(info.get("total",0))
                            )
                with PULL_LOCK:
                    PULL_STATE.update(status="completed",message="Model available in Ollama")
            except (requests.RequestException,ValueError,RuntimeError) as exc:
                with PULL_LOCK:
                    PULL_STATE.update(status="failed",message=str(exc)[:350])
        threading.Thread(target=run_pull,daemon=True,name="ollama-explicit-download").start()
        return jsonify(status="running",model=name),202

    @app.get("/api/studio/llm/recommendations")
    def studio_llm_recommendations():
        return jsonify(models=[
            {"name":"qwen3:8b","use":"Scenario planning — already installed on your host"},
            {"name":"qwen3:4b-instruct","use":"Faster text generation — already installed"},
            {"name":"llama3.2:3b","use":"Small general LLM, optional download"},
            {"name":"gemma3:4b","use":"Compact multimodal model, optional download"},
            {"name":"nomic-embed-text","use":"Embeddings for future vector RAG — already installed"}
        ],warning="Pull uses Ollama's configured model storage, which may be on nearly full system /. No automatic downloads.")
