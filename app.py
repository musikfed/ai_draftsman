"""PEGINELAB AI Draftsman: local comic studio, command-line lifecycle."""
import io, json, os, re, secrets, signal, sqlite3, threading, uuid
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
import requests
from studio.monitor import collect_snapshot
from studio.models import CATALOG, scan_models
from studio.jobs import submit_job, get_job, current_job, CHECKPOINT, WORKER_PY

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv("DRAFTSMAN_DATA", str(BASE / "data"))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
CANON = json.loads((BASE / "canon" / "karate_linux.json").read_text(encoding="utf-8"))
DB = DATA / "draftsman.db"
app = Flask(__name__)
_download_lock = threading.Lock()
_download_state = {"status": "idle", "message": "Загрузка ещё не запускалась"}

def connection():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def initialize():
    """Create/migrate only Draftsman's own SQLite tables, never touch external services."""
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS slides (
            lesson INTEGER NOT NULL, slide INTEGER NOT NULL,
            story TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planned',
            PRIMARY KEY(lesson, slide)
        );
        CREATE TABLE IF NOT EXISTS rag (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL, chunk TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(source, chunk);
        """)
        for lesson in CANON:
            for number in range(1, 6):
                db.execute("INSERT OR IGNORE INTO slides(lesson, slide) VALUES(?, ?)",
                           (lesson["id"], number))
        has_canon = db.execute("SELECT 1 FROM rag WHERE source='Canon' LIMIT 1").fetchone()
        if not has_canon:
            for lesson in CANON:
                line = f'Урок {lesson["id"]:03d}: {lesson["title"]}. {lesson["story"]}'
                db.execute("INSERT INTO rag(source,chunk) VALUES(?,?)", ("Canon",line))
                db.execute("INSERT INTO rag_fts(source,chunk) VALUES(?,?)", ("Canon",line))

initialize()

# Generic project studio. Legacy comic endpoints are kept for existing data.
from studio.projects import register as register_project_studio
register_project_studio(app, DB, DATA, OLLAMA_URL, OLLAMA_MODEL, CANON)

def reach(url):
    try:
        return requests.get(url,timeout=1.5).ok
    except requests.RequestException:
        return False

def find_context(query):
    terms=re.findall(r"[\w-]{3,}",query,flags=re.UNICODE)[:8]
    if not terms: return []
    expression=" OR ".join('"' + t.replace('"','') + '"' for t in terms)
    try:
        with connection() as c:
            return [dict(x) for x in c.execute(
                "SELECT source,chunk FROM rag_fts WHERE rag_fts MATCH ? LIMIT 5",
                (expression,))]
    except sqlite3.OperationalError:
        return []

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/status")
def status():
    snapshot = collect_snapshot()
    snapshot.update({
        "engine_ready": CHECKPOINT.is_file() and WORKER_PY.is_file(),
        "engine_busy": current_job() is not None,
        "ollama_online": reach(OLLAMA_URL + "/api/tags"),
        "port": int(os.getenv("DRAFTSMAN_PORT", "9898")),
    })
    return jsonify(snapshot)


@app.post("/api/shutdown")
def shutdown():
    """Stop only this Flask studio. It is launched manually via scripts/run.sh."""
    def stop_self():
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(0.35, stop_self)
    timer.daemon = True
    timer.start()
    return jsonify(shutting_down=True, note="Restart with bash scripts/run.sh")


@app.post("/api/models/scan")
def model_scan():
    roots = os.getenv("DRAFTSMAN_MODEL_ROOTS", "/1tbdisk:/1tb500dgmext:/1tb500dmntfs:/ssd120").split(os.pathsep)
    return jsonify(scan_models([p for p in roots if p]))


@app.get("/api/models/download/status")
def model_download_status():
    with _download_lock:
        return jsonify(dict(_download_state))


@app.post("/api/models/download/illustrious")
def model_download_illustrious():
    """Explicit opt-in: official Hugging Face repository only; download to user project folder."""
    with _download_lock:
        if _download_state["status"] == "running":
            return jsonify(error="Download is already running"), 409
        _download_state.update(status="running", message="Downloading Illustrious XL 2.0...", path=None)
    def worker():
        try:
            from huggingface_hub import hf_hub_download
            directory = BASE / "models" / "checkpoints"
            directory.mkdir(parents=True, exist_ok=True)
            local_path = hf_hub_download(
                repo_id="OnomaAIResearch/Illustrious-XL-v2.0",
                filename="Illustrious-XL-v2.0.safetensors",
                local_dir=directory,
                cache_dir=str(DATA / "huggingface" / "hub")
            )
            with _download_lock:
                _download_state.update(status="completed", path=str(local_path),
                                       message="Checkpoint downloaded. Independent Diffusers worker can now use it.")
        except Exception as exc:
            with _download_lock:
                _download_state.update(status="failed", message=str(exc)[:500])
    threading.Thread(target=worker, daemon=True, name="hf-model-download").start()
    return jsonify(status="running"), 202


@app.post("/api/gpu/free")
def free_vram():
    """Release locally loaded Ollama models. Image worker releases its CUDA context on exit."""
    active = current_job()
    if active:
        return jsonify(error="Image generation is active. Wait for it to finish before releasing VRAM.",
                       job_id=active["job_id"]), 409
    report = {"image_worker": "not running — no persistent GPU process",
              "ollama": [], "warnings": []}
    try:
        running = requests.get(OLLAMA_URL + "/api/ps", timeout=5)
        running.raise_for_status()
        names = [x.get("name") or x.get("model") for x in running.json().get("models", [])]
        for name in filter(None, names):
            try:
                r = requests.post(OLLAMA_URL + "/api/generate",
                    json={"model":name, "keep_alive":"0s", "stream":False}, timeout=30)
                r.raise_for_status()
                report["ollama"].append({"model":name, "result":"unload requested"})
            except requests.RequestException as exc:
                report["warnings"].append(f"{name}: {exc}")
    except (requests.RequestException, ValueError) as exc:
        report["warnings"].append(f"Ollama: {exc}")
    report["note"] = ("The image worker exits after each job; "
        "its GPU context is released automatically. Other GPU programs are untouched.")
    return jsonify(report)


@app.get("/api/models/catalog")
def model_catalog():
    return jsonify(catalog=CATALOG)


@app.get("/api/ollama/models")
def ollama_models():
    try:
        res = requests.get(OLLAMA_URL + "/api/tags", timeout=4)
        res.raise_for_status()
        models = [
            {"name": m.get("name"), "size_gib": round(m.get("size", 0)/1073741824, 2)}
            for m in res.json().get("models", [])
        ]
        return jsonify(models=models, note="Ollama language/vision models are not automatically diffusion image checkpoints")
    except (requests.RequestException, ValueError) as exc:
        return jsonify(error=f"Ollama unavailable: {exc}"), 502


@app.get("/api/plan")
def plan():
    with connection() as c:
        slides=[dict(x) for x in c.execute("SELECT * FROM slides ORDER BY lesson,slide")]
    return jsonify(lessons=CANON,slides=slides)

@app.post("/api/slides/<int:lesson>/<int:slide>")
def slide_save(lesson,slide):
    if not (1<=lesson<=24 and 1<=slide<=5):return jsonify(error="Only 24 lessons and five slides"),400
    p=request.get_json(silent=True) or {}
    s,prompt=str(p.get("story",""))[:8000],str(p.get("prompt",""))[:16000]
    state=p.get("status","draft")
    if state not in ("planned","draft","approved"):return jsonify(error="Invalid status"),400
    with connection() as c:
        c.execute("UPDATE slides SET story=?,prompt=?,status=? WHERE lesson=? AND slide=?",
                  (s,prompt,state,lesson,slide))
    return jsonify(saved=True)

@app.get("/api/rag/search")
def rag_search():
    return jsonify(results=find_context(request.args.get("q","")))

@app.post("/api/rag/import")
def rag_import():
    file=request.files.get("file")
    if not file or not file.filename.lower().endswith((".md",".txt")):
        return jsonify(error="Upload .md/.txt UTF-8 file"),400
    data=file.read(1000001)
    if len(data)>1000000:return jsonify(error="Max 1 MB"),413
    try: content=data.decode("utf-8")
    except UnicodeDecodeError:return jsonify(error="Use UTF-8"),400
    parts=[content[i:i+900] for i in range(0,len(content),900)]
    with connection() as c:
        for chunk in parts:
            source=Path(file.filename).name[:100]
            c.execute("INSERT INTO rag(source,chunk) VALUES (?,?)",(source,chunk))
            c.execute("INSERT INTO rag_fts(source,chunk) VALUES (?,?)",(source,chunk))
    return jsonify(imported=len(parts))

@app.post("/api/ollama/plan")
def ollama_plan():
    p=request.get_json(silent=True) or {}
    lesson=p.get("lesson")
    if type(lesson) is not int or not 1<=lesson<=24:
        return jsonify(error="lesson must be an integer 1..24"),400
    entry=CANON[lesson-1]
    system=("You are a strict Russian manga comic screenwriter. Return only JSON: "
      "{\"slides\":[{\"slide\":1,\"story\":\"...\",\"prompt\":\"...\"},...]} "
      "with EXACTLY 5 sequential slides, not alternatives. Each slide has 1-3 panels. "
      "Never change the episode name, established events, characters or belt sequence. "
      "Grep is a beardless man, black PL cap, orange glasses and black-orange coat. "
      "ROOT is always a penguin in a dark kimono. Blue PostgreSQL elephant appears after lesson 012. "
      "Lessons 013-015: GREEN BELT. Text Russian. Safe and valid commands only. "
      "Prompts for generated art should leave dialogue bubbles BLANK to add text later. "
      "Only first slide has the compact title. Target output 800x1000 PNG8.")
    try:
        resp=requests.post(OLLAMA_URL+"/api/chat",json={
          "model":OLLAMA_MODEL,"stream":False,"format":"json","keep_alive":"0s",
          "messages":[{"role":"system","content":system},{"role":"user",
            "content":f'Lesson {lesson:03d}: {entry["title"]}. CANON: {entry["story"]}. Context: {find_context(entry["title"]+" "+entry["story"])}'}]
        },timeout=180)
        resp.raise_for_status()
        slides=json.loads(resp.json()["message"]["content"])["slides"]
        if len(slides)!=5 or sorted(x.get("slide") for x in slides)!=[1,2,3,4,5]:
            return jsonify(error="The model did not return exactly five slides; nothing saved"),422
        output=[]
        for x in slides:
            if not x.get("story") or not x.get("prompt"):return jsonify(error="Empty draft; nothing saved"),422
            output.append((str(x["story"])[:8000],str(x["prompt"])[:16000],lesson,x["slide"]))
        with connection() as c:
            c.executemany("UPDATE slides SET story=?,prompt=?,status='draft' WHERE lesson=? AND slide=?",output)
        return jsonify(saved=5,slides=slides,note="Review and approve before image generation")
    except (ValueError,KeyError,requests.RequestException) as e:
        return jsonify(error=f"Ollama planning failed: {e}"),502

@app.get("/api/references")
def reference_list():
    directory = DATA / "references"
    directory.mkdir(parents=True, exist_ok=True)
    return jsonify(references=sorted(
        p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower()==".png"))


@app.post("/api/references/upload")
def reference_upload():
    from PIL import Image, ImageOps
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith((".png",".jpg",".jpeg",".webp")):
        return jsonify(error="Choose PNG, JPEG or WEBP reference image"),400
    content=f.read(12*1024*1024+1)
    if len(content)>12*1024*1024:
        return jsonify(error="Reference exceeds 12 MB"),413
    try:
        image=Image.open(io.BytesIO(content))
        if image.width*image.height>22000000: return jsonify(error="Image too large"),413
        image=ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((2048,2048))
    except (OSError,ValueError) as exc:
        return jsonify(error=f"Invalid image: {exc}"),400
    folder=DATA/"references"
    folder.mkdir(parents=True,exist_ok=True)
    filename=uuid.uuid4().hex+".png"
    image.save(folder/filename,format="PNG",optimize=True)
    return jsonify(saved=True,filename=filename)


@app.get("/api/loras")
def lora_list():
    folder=BASE/"models"/"loras"
    if not folder.exists():return jsonify(loras=[])
    return jsonify(loras=sorted(x.name for x in folder.iterdir()
                               if x.is_file() and x.suffix.lower()==".safetensors"))


@app.post("/api/engine/generate")
def generate():
    p=request.get_json(silent=True) or {}
    lesson,slide=p.get("lesson"),p.get("slide")
    if type(lesson) is not int or type(slide) is not int or not (1<=lesson<=24 and 1<=slide<=5):
        return jsonify(error="Invalid lesson/slide"),400
    with connection() as db:
        record=db.execute("SELECT * FROM slides WHERE lesson=? AND slide=?", (lesson,slide)).fetchone()
    if not record or record["status"]!="approved" or not record["prompt"].strip():
        return jsonify(error="Review and approve a non-empty slide prompt first"),409
    mode=str(p.get("mode","txt2img"))
    if mode not in ("txt2img","img2img"):
        return jsonify(error="Mode not implemented; use txt2img or img2img"),400
    variants=p.get("variants",1)
    if type(variants) is not int or not 1<=variants<=3:
        return jsonify(error="Variants must be 1, 2 or 3"),400
    try:
        steps=int(p.get("steps",28))
        strength=float(p.get("strength",0.55))
        cfg=float(p.get("cfg",6.5))
        seed=int(p.get("seed",0)) or secrets.randbelow(2**31)
        quality=str(p.get("quality","standard"))
        if quality not in ("standard","high") or not 10<=steps<=60 or not 0.15<=strength<=0.9 or not 1.0<=cfg<=12.0 or seed<0:
            raise ValueError("Invalid generation settings")
    except (TypeError, ValueError):
        return jsonify(error="Invalid seed, steps, CFG, strength or resolution"),400
    reference_name=str(p.get("reference",""))
    reference=None
    if mode=="img2img":
        if not re.fullmatch(r"[0-9a-f]{32}\.png",reference_name):
            return jsonify(error="Upload and select a reference image"),400
        reference=DATA/"references"/reference_name
        if not reference.is_file():
            return jsonify(error="Reference file not found"),404
    lora=str(p.get("lora",""))
    if lora and (not re.fullmatch(r"[A-Za-z0-9_. -]{1,160}\.safetensors",lora)
                 or not (BASE/"models"/"loras"/lora).is_file()):
        return jsonify(error="Selected LoRA file not found"),400
    spec={"lesson":lesson,"slide":slide,"mode":mode,
          "prompt":record["prompt"],
          "negative_prompt":"low quality, blurry, malformed anatomy, extra hands, text, watermark, signature, cropped",
          "variants":variants,"seed":seed,"steps":steps,"cfg":cfg,
          "strength":strength,"width":896 if quality=="high" else 768,
          "height":1120 if quality=="high" else 960,
          "reference":str(reference) if reference else "",
          "lora":lora,"lora_scale":0.7}
    try:
        job_id=submit_job(spec)
        return jsonify(submitted=True,job_id=job_id,
                       note="Separate GPU process started; check status manually"),202
    except (FileNotFoundError,RuntimeError,OSError) as exc:
        return jsonify(error=str(exc)),422


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    j=get_job(job_id)
    if j is None:return jsonify(error="Job not found"),404
    j.pop("traceback",None)
    for out in j.get("outputs",[]):
        out["preview_url"]=f'/api/jobs/{job_id}/images/{out["variant"]}'
    return jsonify(j)


@app.get("/api/jobs/<job_id>/images/<int:variant>")
def job_image(job_id,variant):
    if not 1<=variant<=3:return jsonify(error="Invalid variant"),404
    job=get_job(job_id)
    if job is None:return jsonify(error="Job not found"),404
    for item in job.get("outputs",[]):
        if item["variant"]==variant:
            img=Path(item["png8"]).resolve()
            folder=(DATA/"jobs"/job_id/"images").resolve()
            if img.parent==folder and img.is_file():
                return send_file(img,mimetype="image/png")
    return jsonify(error="Image is not ready"),404


if __name__=="__main__":
    app.run(host=os.getenv("DRAFTSMAN_HOST","0.0.0.0"),
            port=int(os.getenv("DRAFTSMAN_PORT","9898")),debug=False,use_reloader=False)
