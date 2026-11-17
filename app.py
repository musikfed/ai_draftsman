"""PEGINELAB AI Draftsman: Flask LAN studio and opt-in GPU process."""
import json, os, re, signal, sqlite3, subprocess, threading, time, uuid
from pathlib import Path
from flask import Flask, jsonify, render_template, request
import requests

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv("DRAFTSMAN_DATA", str(BASE / "data"))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
COMFY = Path(os.getenv("COMFYUI_DIR", "/1tbdisk/AI/ComfyUI")).resolve()
COMFY_PORT = int(os.getenv("COMFYUI_PORT", "8188"))
COMFY_URL = f"http://127.0.0.1:{COMFY_PORT}"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
CANON = json.loads((BASE / "canon" / "karate_linux.json").read_text(encoding="utf-8"))
DB = DATA / "draftsman.db"
PIDFILE = DATA / "comfy.pid"
LOGFILE = DATA / "comfy.log"
_lock = threading.RLock()
_process = None
app = Flask(__name__)

def connection():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def initialize():
    with connection() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS slides (
          lesson INTEGER NOT NULL, slide INTEGER NOT NULL,
          story TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'planned',
          PRIMARY KEY(lesson, slide));
        CREATE TABLE IF NOT EXISTS rag (
          id INTEGER PRIMARY KEY, source TEXT NOT NULL, chunk TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(source,chunk);
        """)
        for entry in CANON:
            for n in range(1,6):
                c.execute("INSERT OR IGNORE INTO slides(lesson,slide) VALUES(?,?)",(entry["id"],n))
        if c.execute("SELECT count(*) FROM rag").fetchone()[0] == 0:
            for entry in CANON:
                text=f'Урок {entry["id"]:03d}: {entry["title"]}. {entry["story"]}'
                c.execute("INSERT INTO rag(source,chunk) VALUES (?,?)",("Canon",text))
                c.execute("INSERT INTO rag_fts(source,chunk) VALUES (?,?)",("Canon",text))
initialize()

def owns(pid):
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0",b" ").decode(errors="ignore")
        cwd = Path(f"/proc/{pid}/cwd").resolve()
        return cwd == COMFY and "main.py" in cmd
    except (OSError,ValueError):
        return False

def managed_pid():
    global _process
    if _process is not None and _process.poll() is None and owns(_process.pid):
        return _process.pid
    try:
        p=int(PIDFILE.read_text())
        return p if owns(p) else None
    except (OSError,ValueError):
        return None

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
    try:
        n=subprocess.run(["nvidia-smi","--query-gpu=name,memory.used,memory.total,temperature.gpu",
                          "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=3)
        gpu=n.stdout.strip().splitlines()[0] if n.returncode==0 else "Unavailable"
    except (OSError, subprocess.TimeoutExpired):
        gpu="Unavailable"
    with _lock:
        pid=managed_pid()
    return jsonify(comfy_running=bool(pid),comfy_pid=pid,
        comfy_online=reach(COMFY_URL+"/system_stats"),
        ollama_online=reach(OLLAMA_URL+"/api/tags"),gpu=gpu,port=9898)

@app.post("/api/engine/start")
def engine_start():
    global _process
    with _lock:
        if managed_pid():
            return jsonify(error="Engine already started by Draftsman"),409
        if reach(COMFY_URL+"/system_stats"):
            return jsonify(error="ComfyUI already occupies the internal port; not managed by Draftsman"),409
        py=COMFY/".venv"/"bin"/"python"
        if not py.exists() or not (COMFY/"main.py").exists():
            return jsonify(error=f"Install ComfyUI with .venv under {COMFY} first"),422
        with LOGFILE.open("ab") as log:
            _process=subprocess.Popen(
                [str(py),"main.py","--listen","127.0.0.1","--port",str(COMFY_PORT),
                 "--disable-auto-launch","--lowvram"],
                cwd=COMFY,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                start_new_session=True)
        PIDFILE.write_text(str(_process.pid))
        return jsonify(started=True,pid=_process.pid),202

@app.post("/api/engine/stop")
def engine_stop():
    with _lock:
        pid=managed_pid()
        if not pid: return jsonify(stopped=False,note="No managed engine")
        try:
            queue=requests.get(COMFY_URL+"/queue",timeout=3).json()
            if queue.get("queue_running") or queue.get("queue_pending"):
                return jsonify(error="Finish/cancel running jobs before shutdown"),409
        except requests.RequestException:
            pass
        if not owns(pid): return jsonify(error="Process owner mismatch; refusing to stop"),409
        os.killpg(pid,signal.SIGTERM)
        PIDFILE.unlink(missing_ok=True)
        return jsonify(stopped=True)

@app.get("/api/engine/log")
def engine_log():
    if not LOGFILE.exists():return jsonify(lines=[])
    with LOGFILE.open("rb") as f:
        f.seek(max(0,LOGFILE.stat().st_size-18000))
        return jsonify(lines=f.read().decode("utf-8",errors="replace").splitlines()[-60:])

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

@app.post("/api/engine/generate")
def generate():
    p=request.get_json(silent=True) or {}
    lesson,slide=p.get("lesson"),p.get("slide")
    if type(lesson) is not int or type(slide) is not int or not (1<=lesson<=24 and 1<=slide<=5):
        return jsonify(error="Invalid lesson/slide"),400
    with connection() as c:
        record=c.execute("SELECT * FROM slides WHERE lesson=? AND slide=?",(lesson,slide)).fetchone()
    if record["status"]!="approved":return jsonify(error="Approve this slide first"),409
    workflow_file=DATA/"workflows"/"comic_api.json"
    if not workflow_file.is_file():
        return jsonify(error="Export an actual model-compatible ComfyUI API workflow to data/workflows/comic_api.json"),422
    if not managed_pid() or not reach(COMFY_URL+"/system_stats"):
        return jsonify(error="Switch engine ON first"),409
    workflow=json.loads(workflow_file.read_text(encoding="utf-8"))
    replaced=0
    for node in workflow.values():
        if isinstance(node,dict) and isinstance(node.get("inputs",{}).get("text"),str):
            val=node["inputs"]["text"]
            if "{{PROMPT}}" in val:
                node["inputs"]["text"]=val.replace("{{PROMPT}}",record["prompt"])
                replaced+=1
    if replaced!=1:return jsonify(error="Workflow must have exactly one text input containing {{PROMPT}}"),422
    try:
        result=requests.post(COMFY_URL+"/prompt",json={"prompt":workflow,"client_id":str(uuid.uuid4())},timeout=15)
        result.raise_for_status()
        return jsonify(prompt_id=result.json().get("prompt_id"),submitted=True)
    except requests.RequestException as e:
        return jsonify(error=f"ComfyUI submission failed: {e}"),502

if __name__=="__main__":
    app.run(host=os.getenv("DRAFTSMAN_HOST","0.0.0.0"),
            port=int(os.getenv("DRAFTSMAN_PORT","9898")),debug=False,use_reloader=False)
