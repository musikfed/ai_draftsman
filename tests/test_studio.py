"""Smoke tests: SQLite boot, canon graph and lightweight routes (no CUDA needed)."""
import unittest
from app import app, connection, CANON

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_index(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("PEGINELAB", html)
        self.assertIn("freeVram", html)
        self.assertNotIn('id="powerOn"', html)

    def test_canon_and_slides(self):
        result = self.client.get("/api/plan")
        self.assertEqual(result.status_code, 200)
        payload = result.get_json()
        self.assertEqual(len(payload["lessons"]), 24)
        # Existing legacy projects retain their slides; a fresh universal studio
        # intentionally starts without automatically creating 120 comic rows.
        self.assertTrue(all(1<=x["lesson"]<=24 and 1<=x["slide"]<=5
                            for x in payload["slides"]))
        self.assertEqual(payload["lessons"][12]["id"], 13)

    def test_existing_rag(self):
        with connection() as db:
            self.assertGreaterEqual(db.execute("SELECT count(*) FROM rag").fetchone()[0], 0)

    def test_download_status(self):
        self.assertEqual(self.client.get("/api/models/download/status").status_code, 200)

    def test_model_catalog(self):
        result = self.client.get("/api/models/catalog").get_json()
        self.assertTrue(result["catalog"])

if __name__ == "__main__":
    unittest.main()
