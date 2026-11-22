"""Seven built-in SQLite graph examples; isolated DB, no Ollama or GPU."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from flask import Flask
from studio.projects import register
from studio.graph_templates import BUILTIN_TEMPLATES, validate_template


class GraphTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name)/"data"
        self.data.mkdir()
        self.db_path=self.data/"sandbox.sqlite"
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("""
                CREATE TABLE slides (
                  lesson INTEGER, slide INTEGER, story TEXT, prompt TEXT, status TEXT
                )
            """)
        self.app=Flask(__name__)
        register(self.app,self.db_path,self.data,"http://127.0.0.1:1",
                 "qwen3:8b",[{"id":1,"title":"Known lesson","story":"Known story"}])
        self.client=self.app.test_client()

    def test_catalog_persists_exactly_seven_typed_blueprints(self):
        response=self.client.get("/api/studio/templates")
        self.assertEqual(response.status_code,200)
        templates=response.get_json()["templates"]
        self.assertEqual(len(templates),7)
        ids={t["id"] for t in templates}
        self.assertEqual(ids, {t["id"] for t in BUILTIN_TEMPLATES})
        self.assertIn("comic_storyboard",ids)
        self.assertIn("technical_diagram",ids)
        for template in templates:
            self.assertTrue(template["title_ru"])
            self.assertTrue(template["summary_ru"])
            self.assertEqual(template["schema_version"],1)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM studio_graph_templates").fetchone()[0],7)

    def test_all_dags_can_be_previsited_without_creating_project(self):
        for template in BUILTIN_TEMPLATES:
            with self.subTest(template=template["id"]):
                validate_template(template)
                response=self.client.get("/api/studio/templates/"+template["id"])
                self.assertEqual(response.status_code,200)
                payload=response.get_json()["template"]
                self.assertEqual(payload["id"],template["id"])
                self.assertGreaterEqual(len(payload["nodes"]),6)
                keys={node["key"] for node in payload["nodes"]}
                for src,dst in payload["edges"]:
                    self.assertIn(src,keys)
                    self.assertIn(dst,keys)
                self.assertTrue(all(node["kind"] in (
                    "scene","character","style","prompt","reference",
                    "note","output","lesson","slide"
                ) for node in payload["nodes"]))
        self.assertEqual(self.client.get("/api/studio/projects").get_json()["projects"],[])

    def test_each_example_creates_editable_independent_project(self):
        for template in BUILTIN_TEMPLATES:
            with self.subTest(template=template["id"]):
                response=self.client.post("/api/studio/projects",json={
                    "name":"Example "+template["id"],"template":template["id"]
                })
                self.assertEqual(response.status_code,201,response.get_json())
                project_id=response.get_json()["project_id"]
                detail=self.client.get(f"/api/studio/projects/{project_id}").get_json()
                self.assertEqual(detail["project"]["kind"],template["id"])
                self.assertEqual(detail["project"]["base_prompt"],template["base_prompt"])
                self.assertEqual(len(detail["nodes"]),len(template["nodes"]))
                self.assertEqual(len(detail["edges"]),len(template["edges"]))
                self.assertTrue(all(node["status"]=="draft" for node in detail["nodes"]))
                ids={node["id"] for node in detail["nodes"]}
                self.assertTrue(all(edge["source"] in ids and edge["target"] in ids
                                    for edge in detail["edges"]))
                self.assertTrue(all(node["last_job"]=="" for node in detail["nodes"]))
                first=detail["nodes"][0]
                updated=self.client.patch(
                    f"/api/studio/projects/{project_id}/nodes/{first['id']}",
                    json={"notes":"Personal changes"})
                self.assertEqual(updated.status_code,200)
                original=self.client.get("/api/studio/templates/"+template["id"]).get_json()["template"]
                self.assertEqual(original["nodes"][0]["notes"],template["nodes"][0]["notes"])

    def test_comic_has_five_sequential_swipes_not_five_random_variants(self):
        response=self.client.post("/api/studio/projects",json={
            "name":"Five-panel comic","template":"comic_storyboard"
        })
        project_id=response.get_json()["project_id"]
        graph=self.client.get(f"/api/studio/projects/{project_id}").get_json()
        self.assertEqual(len(graph["nodes"]),9)
        self.assertEqual(len([node for node in graph["nodes"] if node["kind"]=="slide"]),5)
        self.assertEqual(len(graph["edges"]),10)
        slides=[node for node in graph["nodes"] if node["kind"]=="slide"]
        for left,right in zip(slides,slides[1:]):
            self.assertTrue(any(edge["source"]==left["id"] and edge["target"]==right["id"]
                                for edge in graph["edges"]))
        preview=self.client.get(
            f"/api/studio/projects/{project_id}/nodes/{slides[1]['id']}/preview").get_json()
        self.assertIn("завязка",preview["graph_context"].lower())
        self.assertIn("character",preview["graph_context"])

    def test_restarts_seed_idempotently_and_keep_existing_project(self):
        project_id=self.client.post("/api/studio/projects",json={
            "name":"Keep forever","template":"technical_diagram"
        }).get_json()["project_id"]
        other=Flask("second-startup")
        register(other,self.db_path,self.data,"http://127.0.0.1:1",
                 "qwen3:8b",[{"id":1,"title":"Known lesson","story":"Known story"}])
        client=other.test_client()
        self.assertEqual(len(client.get("/api/studio/templates").get_json()["templates"]),7)
        self.assertEqual(client.get(f"/api/studio/projects/{project_id}").status_code,200)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM studio_graph_templates").fetchone()[0],7)

    def test_blank_karate_and_invalid_templates_unchanged(self):
        self.assertEqual(self.client.post("/api/studio/projects",json={
            "name":"Empty","template":"blank"
        }).status_code,201)
        comic=self.client.post("/api/studio/projects",json={
            "name":"Karate Legacy","template":"karate"
        })
        self.assertEqual(comic.status_code,201)
        project_id=comic.get_json()["project_id"]
        self.assertEqual(self.client.get(f"/api/studio/projects/{project_id}")
                         .get_json()["project"]["kind"],"karate")
        self.assertEqual(self.client.get("/api/studio/templates/nonexistent").status_code,404)
        self.assertEqual(self.client.post("/api/studio/projects",json={
            "name":"Bad","template":"nonexistent"
        }).status_code,400)


if __name__=="__main__":
    unittest.main()
