"""Tests for universal projects without touching user's existing studio database."""
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from flask import Flask
from studio.projects import register


class GraphStudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        data = root / "data"
        data.mkdir()
        db_path = data / "sandbox.db"
        with sqlite3.connect(db_path) as db:
            db.execute("CREATE TABLE slides(lesson INTEGER,slide INTEGER,story TEXT,prompt TEXT,status TEXT)")
            db.execute("INSERT INTO slides VALUES(1,1,'Existing script','Existing image prompt','approved')")
        self.app = Flask(__name__)
        register(self.app, db_path, data, "http://127.0.0.1:1",
                 "qwen3:8b", [{"id":1,"title":"Sample lesson","story":"Example canon"}])
        self.client = self.app.test_client()

    def post(self, url, obj):
        return self.client.post(url, json=obj)

    def test_create_project_and_prompt_assembly(self):
        response = self.post("/api/studio/projects",{"name":"My architecture","template":"blank"})
        self.assertEqual(response.status_code,201)
        pid = response.get_json()["project_id"]
        self.assertEqual(len(self.client.get("/api/studio/projects").get_json()["projects"]),1)
        response = self.client.patch("/api/studio/projects/"+str(pid), json={
            "base_prompt":"blue technical drawings",
            "negative_prompt":"watermarks",
            "system_prompt":"Follow graph nodes",
            "description":"Visualize software processes"})
        self.assertEqual(response.status_code,200)
        path="/api/studio/projects/"+str(pid)
        a=self.post(path+"/nodes",{"title":"Parent idea","kind":"note","x":10,"y":20}).get_json()["node_id"]
        b=self.post(path+"/nodes",{"title":"Scene B","kind":"scene","x":250,"y":20}).get_json()["node_id"]
        self.assertEqual(self.client.patch(path+"/nodes/"+str(a),json={
            "notes":"orange server", "prompt":"glowing monitor","status":"approved"
        }).status_code,200)
        self.assertEqual(self.client.patch(path+"/nodes/"+str(b),json={
            "notes":"network bridge","prompt":"white background","negative_prompt":"blur"
        }).status_code,200)
        self.assertEqual(self.post(path+"/edges",{"source":a,"target":b}).status_code,201)
        data=self.client.get(path+"/nodes/"+str(b)+"/preview").get_json()
        self.assertIn("blue technical drawings",data["prompt"])
        self.assertIn("orange server",data["graph_context"])
        self.assertIn("network bridge",data["prompt"])
        self.assertIn("watermarks",data["negative_prompt"])
        self.assertIn("blur",data["negative_prompt"])
        self.assertEqual(len(self.client.get(path).get_json()["nodes"]),2)
        self.assertEqual(self.client.post(path+"/nodes/"+str(b)+"/generate",json={}).status_code,409)

    def test_new_empty_project_does_not_copy_current_project_or_prompts(self):
        original=self.post("/api/studio/projects",{
            "name":"Existing comic","template":"comic_storyboard"
        })
        self.assertEqual(original.status_code,201)
        source_id=original.get_json()["project_id"]
        src=self.client.get("/api/studio/projects/"+str(source_id)).get_json()
        self.assertGreater(len(src["nodes"]),0)
        created=self.post("/api/studio/projects",{
            "name":"Fresh clean project","template":"blank"
        })
        self.assertEqual(created.status_code,201)
        pid=created.get_json()["project_id"]
        self.assertNotEqual(pid,source_id)
        new=self.client.get("/api/studio/projects/"+str(pid)).get_json()
        self.assertEqual(new["project"]["name"],"Fresh clean project")
        self.assertEqual(new["project"]["kind"],"general")
        for field in ("base_prompt","negative_prompt","system_prompt","description"):
            self.assertEqual(new["project"][field],"")
        self.assertEqual(new["nodes"],[])
        self.assertEqual(new["edges"],[])
        still=self.client.get("/api/studio/projects/"+str(source_id)).get_json()
        self.assertEqual(len(still["nodes"]),len(src["nodes"]))
        self.assertEqual(len(still["edges"]),len(src["edges"]))

    def test_karate_is_optional_legacy_template(self):
        general = self.post("/api/studio/projects",{"name":"Generic","template":"blank"}).get_json()["project_id"]
        self.assertEqual(self.client.get("/api/studio/projects/"+str(general)).get_json()["nodes"],[])
        karate = self.post("/api/studio/projects",{"name":"Karate","template":"karate"}).get_json()["project_id"]
        path="/api/studio/projects/"+str(karate)
        data=self.client.get(path).get_json()
        self.assertEqual(data["project"]["kind"],"karate")
        self.assertEqual(len(data["nodes"]),1)
        self.assertEqual(len(data["edges"]),0)
        expanded=self.client.post(path+"/lessons/1/expand").get_json()
        self.assertEqual(len(expanded["created"]),1)
        self.assertEqual(self.client.post(path+"/lessons/1/expand").status_code,409)
        new_data=self.client.get(path).get_json()
        self.assertEqual(new_data["nodes"][1]["prompt"],"Existing image prompt")

    def test_edge_cannot_link_other_project_nodes(self):
        a=self.post("/api/studio/projects",{"name":"A"}).get_json()["project_id"]
        b=self.post("/api/studio/projects",{"name":"B"}).get_json()["project_id"]
        node_a=self.post(f"/api/studio/projects/{a}/nodes",{"title":"A scene"}).get_json()["node_id"]
        node_b=self.post(f"/api/studio/projects/{b}/nodes",{"title":"B scene"}).get_json()["node_id"]
        response=self.post(f"/api/studio/projects/{a}/edges",{"source":node_a,"target":node_b})
        self.assertEqual(response.status_code,404)

    def test_project_specific_knowledge(self):
        pid=self.post("/api/studio/projects",{"name":"Architecture"}).get_json()["project_id"]
        f=io.BytesIO("Network topology uses two switches".encode("utf-8"))
        response=self.client.post(
            f"/api/studio/projects/{pid}/knowledge",
            data={"file":(f,"guide.txt")},content_type="multipart/form-data")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()["chunks"],1)

    def test_no_download_without_explicit_button(self):
        status=self.client.get("/api/studio/llm/status").get_json()
        self.assertIn("status",status)
        self.assertEqual(self.post("/api/studio/llm/pull",{"model":"bad space"}).status_code,400)


if __name__ == "__main__":
    unittest.main()
