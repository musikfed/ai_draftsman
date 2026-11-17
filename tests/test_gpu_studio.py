"""Offline HTTP smoke checks, without downloading models or loading CUDA."""
import io
import os
import unittest
from pathlib import Path
from PIL import Image
from app import app, DATA

class GPULessTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()

    def test_get_models_and_references(self):
        self.assertEqual(self.client.get("/api/models/catalog").status_code,200)
        self.assertEqual(self.client.get("/api/references").status_code,200)
        self.assertEqual(self.client.get("/api/loras").status_code,200)

    def test_job_is_not_found(self):
        self.assertEqual(self.client.get("/api/jobs/"+"0"*32).status_code,404)
        self.assertEqual(self.client.get("/api/jobs/not-a-uuid").status_code,404)

    def test_generation_rejects_invalid_slide(self):
        r=self.client.post("/api/engine/generate",json={"lesson":0,"slide":42})
        self.assertEqual(r.status_code,400)

    def test_upload_reference(self):
        image=Image.new("RGB",(64,80),color=(21,47,68))
        data=io.BytesIO()
        image.save(data,format="PNG")
        data.seek(0)
        r=self.client.post("/api/references/upload",
            data={"file":(data,"test.png")},content_type="multipart/form-data")
        self.assertEqual(r.status_code,200)
        filename=r.get_json()["filename"]
        target=DATA/"references"/filename
        try:
            self.assertTrue(target.is_file())
            self.assertEqual(target.suffix,".png")
        finally:
            target.unlink(missing_ok=True)

    def test_gpu_status_shape(self):
        r=self.client.get("/api/status")
        self.assertEqual(r.status_code,200)
        value=r.get_json()
        self.assertIn("engine_ready",value)
        self.assertIn("engine_busy",value)
        self.assertNotIn("comfy_online",value)

if __name__=="__main__":
    unittest.main()
