"""Regression tests for the lightweight bubble-only generation waiting scene.

No Flask server, CUDA or Ollama is started.
"""
import unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]


class WaitingBubblesUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(BASE/"templates"/"studio.html").read_text(encoding="utf-8")

    def test_no_turtle_asset_or_animation_is_used(self):
        html=self.html
        self.assertNotIn("wait-turtle",html)
        self.assertNotIn("turtle.src=",html)
        self.assertNotIn("sea-turtle-swim",html)
        self.assertNotIn("sea-turtle-cartoon.svg",html)
        self.assertNotIn("черепашк",html.lower())

    def test_many_bubbles_have_random_color_size_position_and_speed(self):
        html=self.html
        self.assertIn("const bubbleCount=visible===1?26:16;",html)
        self.assertIn("Math.random",html)
        for variable in ("--bubble-size","--bubble-x","--bubble-hue",
                         "--bubble-speed","--bubble-delay","--bubble-drift"):
            self.assertIn("bubble.style.setProperty('"+variable+"'",html)
        self.assertIn("@keyframes bubble-float",html)
        self.assertIn("hsl(var(--bubble-hue",html)
        self.assertIn("will-change:transform",html)

    def test_waiting_only_during_active_jobs(self):
        html=self.html
        self.assertIn("const busy=['running','queued'].includes(job.status)",html)
        self.assertIn("renderWaiting(job.total,job.completed)",html)
        self.assertIn("renderWaiting(amount)",html)
        self.assertIn("grid.classList.toggle('single',visible===1)",html)
        self.assertIn("stopJobPolling();await refreshJobHistory(false)",html)
        self.assertIn('id="demoWait"',html)
        self.assertIn("GPU не запущен",html)
        self.assertIn("prefers-reduced-motion",html)


if __name__=="__main__":
    unittest.main()
