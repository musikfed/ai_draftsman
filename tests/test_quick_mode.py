"""Persistent direct mode and job history: offline tests, no GPU/LLM/downloads."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as studio_app
from studio import jobs


class QuickModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "test.db"
        with sqlite3.connect(self.db_path) as db:
            db.execute("""CREATE TABLE quick_draft(
                id INTEGER PRIMARY KEY CHECK(id=1),
                prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("""CREATE TABLE quick_draft_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT NOT NULL,
                negative_prompt TEXT NOT NULL,
                prompt_ru TEXT,
                negative_prompt_ru TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        def connect():
            db=sqlite3.connect(self.db_path)
            db.row_factory=sqlite3.Row
            return db
        self.patch_connection=patch.object(studio_app,"connection",connect)
        self.patch_connection.start()
        self.addCleanup(self.patch_connection.stop)
        self.client=studio_app.app.test_client()

    def test_save_and_restore_direct_prompts(self):
        before=self.client.get("/api/quick/draft/saved").get_json()
        self.assertEqual(before["prompt"],"")
        r=self.client.put("/api/quick/draft/saved",
            json={"prompt":"Snowy kitten","negative_prompt":"blur"})
        self.assertEqual(r.status_code,200)
        after=self.client.get("/api/quick/draft/saved").get_json()
        self.assertEqual(after["prompt"],"Snowy kitten")
        self.assertEqual(after["negative_prompt"],"blur")

    def test_draft_history_keeps_old_version_without_duplicate_saves(self):
        a=self.client.put("/api/quick/draft/saved",
            json={"prompt":"Kitten in red glasses","negative_prompt":"blurry"}).get_json()
        b=self.client.put("/api/quick/draft/saved",
            json={"prompt":"Green parrot","negative_prompt":"watermark"}).get_json()
        c=self.client.put("/api/quick/draft/saved",
            json={"prompt":"Green parrot","negative_prompt":"watermark"}).get_json()
        self.assertNotEqual(a["draft_id"],b["draft_id"])
        self.assertEqual(b["draft_id"],c["draft_id"])
        entries=self.client.get("/api/quick/drafts").get_json()["drafts"]
        self.assertEqual(len(entries),2)
        saved=self.client.get("/api/quick/drafts/"+str(a["draft_id"])).get_json()
        self.assertEqual(saved["prompt"],"Kitten in red glasses")
        self.assertEqual(saved["negative_prompt"],"blurry")

    def test_cached_local_translation(self):
        entry=self.client.put("/api/quick/draft/saved",
            json={"prompt":"Kitten","negative_prompt":"blur"}).get_json()
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE quick_draft_history SET prompt_ru=?,negative_prompt_ru=? WHERE id=?",
                ("Котёнок","размытость",entry["draft_id"]))
        r=self.client.post("/api/quick/drafts/"+str(entry["draft_id"])+"/translate",
            json={"model":"qwen3:8b"})
        self.assertEqual(r.status_code,200)
        self.assertTrue(r.get_json()["cached"])
        self.assertEqual(r.get_json()["prompt_ru"],"Котёнок")

    def test_translation_rejected_during_active_render(self):
        entry=self.client.put("/api/quick/draft/saved",
            json={"prompt":"Kitten","negative_prompt":""}).get_json()
        with patch.object(studio_app,"current_job",return_value={"status":"running"}):
            r=self.client.post("/api/quick/drafts/"+str(entry["draft_id"])+"/translate")
        self.assertEqual(r.status_code,409)

    def test_reference_preview_and_safe_deletion(self):
        import os
        from PIL import Image
        path=Path(self.temp.name)/"references"
        path.mkdir()
        filename="a"*32+".png"
        Image.new("RGB",(8,8),"red").save(path/filename)
        with patch.object(studio_app,"DATA",Path(self.temp.name)):
            self.assertEqual(self.client.get("/api/references/"+filename+"/preview").status_code,200)
            self.assertEqual(self.client.delete("/api/references/../../etc/passwd").status_code,404)
            with patch.object(studio_app,"current_job",return_value={"status":"running"}):
                self.assertEqual(self.client.delete("/api/references/"+filename).status_code,409)
            self.assertEqual(self.client.delete("/api/references/"+filename).status_code,200)
            self.assertFalse((path/filename).exists())
            self.assertEqual(self.client.delete("/api/references/"+filename).status_code,404)

    def test_prompt_gallery_uses_real_completed_images_and_seed(self):
        import os
        from PIL import Image
        jid="b"*32
        folder=Path(self.temp.name)/"jobs"/jid
        (folder/"images").mkdir(parents=True)
        Image.new("RGB",(16,20),"orange").save(folder/"images"/"000_00_v01.png")
        (folder/"spec.json").write_text(json.dumps({
            "lesson":0,"slide":0,"source":"quick",
            "prompt":"Ginger kitten","negative_prompt":"blurry","mode":"txt2img",
            "checkpoint":"sdxl-base-1","seed":0,"steps":28,"cfg":6.5,
            "width":768,"height":960,"strength":0.55,"lora":""
        }),encoding="utf-8")
        jobs=[{"job_id":jid,"source":"quick","status":"completed"}]
        state={"status":"completed","outputs":[{"variant":1,"seed":424242}]}
        with patch.object(studio_app,"DATA",Path(self.temp.name)), \\
             patch.object(studio_app,"recent_jobs",return_value=jobs), \\
             patch.object(studio_app,"get_job",return_value=state):
            resp=self.client.get("/api/prompt-gallery")
            self.assertEqual(resp.status_code,200)
            data=resp.get_json()["examples"]
        self.assertEqual(len(data),1)
        self.assertEqual(data[0]["prompt"],"Ginger kitten")
        self.assertEqual(data[0]["negative_prompt"],"blurry")
        self.assertEqual(data[0]["seed"],424242)
        self.assertEqual(data[0]["checkpoint"],"sdxl-base-1")
        self.assertEqual(data[0]["image_url"],"/api/jobs/"+jid+"/images/1")

    def test_prompt_gallery_never_invents_image_when_png_is_missing(self):
        jid="c"*32
        folder=Path(self.temp.name)/"jobs"/jid
        folder.mkdir(parents=True)
        (folder/"spec.json").write_text(json.dumps({"prompt":"A real kitten","mode":"txt2img"}),
                                        encoding="utf-8")
        jobs=[{"job_id":jid,"source":"quick","status":"completed"}]
        state={"status":"completed","outputs":[{"variant":1,"seed":11}]}
        with patch.object(studio_app,"DATA",Path(self.temp.name)), \\
             patch.object(studio_app,"recent_jobs",return_value=jobs), \\
             patch.object(studio_app,"get_job",return_value=state):
            response=self.client.get("/api/prompt-gallery")
        self.assertEqual(response.get_json()["examples"],[])

    def test_empty_prompt_never_starts_gpu(self):
        r=self.client.post("/api/quick/generate",json={"prompt":""})
        self.assertEqual(r.status_code,400)
        r=self.client.post("/api/quick/draft",json={"idea":""})
        self.assertEqual(r.status_code,400)

    def test_recent_jobs_survive_page_reload_without_gpu(self):
        root=Path(self.temp.name)/"jobs"
        root.mkdir()
        jid="a"*32
        folder=root/jid
        folder.mkdir()
        (folder/"spec.json").write_text(json.dumps({
            "source":"quick","prompt":"A snowy kitten","variants":2}),encoding="utf-8")
        (folder/"state.json").write_text(json.dumps({
            "job_id":jid,"status":"completed","stage":"Готово",
            "progress":100,"created_at":101.0,"completed":2,"total":2,
            "outputs":[{"variant":1},{"variant":2}]
        }),encoding="utf-8")
        with patch.object(jobs,"JOBS",root):
            results=jobs.recent_jobs()
        self.assertEqual(results[0]["job_id"],jid)
        self.assertEqual(results[0]["outputs"],2)
        self.assertEqual(results[0]["source"],"quick")


if __name__=="__main__":
    unittest.main()
