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
