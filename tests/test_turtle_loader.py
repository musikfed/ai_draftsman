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
        self.assertIn("turtle.src='/static/images/sea-turtle-swim.svg'",html)
        self.assertNotIn("createSwimmingTurtle(i)",html)
        self.assertNotIn("turtle-left-clip-",html)
        self.assertNotIn("turtle-right-clip-",html)
        svg_path=BASE/"static"/"images"/"sea-turtle-swim.svg"
        self.assertTrue(svg_path.is_file(), "Missing detailed vector turtle")
        svg=svg_path.read_text(encoding="utf-8")
        import xml.etree.ElementTree as ET
        ET.fromstring(svg)
        self.assertIn('class="near-flipper"',svg)
        self.assertIn('class="far-flipper"',svg)
        self.assertIn("@keyframes near-stroke",svg)
        self.assertIn("@keyframes far-stroke",svg)
        self.assertIn("prefers-reduced-motion",svg)
        self.assertLess(len(svg.encode("utf-8")),55000)
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
