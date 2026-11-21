"""Lightweight regression tests for the sea turtle job waiting scene.

These checks do not start Flask, Ollama, CUDA or any image generation.
"""
import unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]


class TurtleWaitingUITests(unittest.TestCase):
    def test_asset_is_real_small_transparent_webp(self):
        path=BASE/"static"/"images"/"sea-turtle.webp"
        self.assertTrue(path.is_file(), "Missing local turtle asset")
        payload=path.read_bytes()
        self.assertTrue(payload.startswith(b"RIFF") and payload[8:12]==b"WEBP")
        self.assertLess(len(payload), 25000, "Loader image should not burden browser")

    def test_loader_uses_image_not_font_emoji(self):
        html=(BASE/"templates"/"studio.html").read_text(encoding="utf-8")
        self.assertIn("const asset='/static/images/sea-turtle.webp'",html)
        self.assertIn("createSwimmingTurtle(i)",html)
        self.assertIn("turtle-body-mask-",html)
        self.assertIn("turtle-left-clip-",html)
        self.assertIn("turtle-right-clip-",html)
        self.assertIn("@keyframes turtle-paddle-left",html)
        self.assertIn("@keyframes turtle-paddle-right",html)
        self.assertIn(".wait-turtle-flipper,.wait-bubble{animation:none!important}",html)
        self.assertNotIn("turtle.textContent='🐢'",html)
        self.assertIn("@keyframes sea-turtle-swim",html)
        self.assertIn("@keyframes bubble-float",html)
        self.assertIn("prefers-reduced-motion",html)
        self.assertIn("grid.classList.toggle('single',visible===1)",html)
        self.assertIn("renderWaiting(job.total,job.completed)",html)
        self.assertIn('id="demoWait"',html)
        self.assertIn("renderWaiting(amount)",html)
        self.assertIn("Демо: черепаха плавает, но GPU не запущен",html)

    def test_waiting_only_for_active_jobs(self):
        html=(BASE/"templates"/"studio.html").read_text(encoding="utf-8")
        self.assertIn("const busy=['running','queued'].includes(job.status)",html)
        self.assertIn("stopJobPolling();await refreshJobHistory(false)",html)


if __name__=="__main__":
    unittest.main()
