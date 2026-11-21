"""Static UI regressions for quick prompt translations and sketch navigation."""
import unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]


class QuickStudioLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(BASE/"templates"/"studio.html").read_text(encoding="utf-8")
        cls.results=(BASE/"static"/"js"/"results_catalog.js").read_text(encoding="utf-8")
        cls.drafts=(BASE/"static"/"js"/"draft_catalog.js").read_text(encoding="utf-8")
        cls.translation=(BASE/"static"/"js"/"quick_translations.js").read_text(encoding="utf-8")
        cls.css=(BASE/"static"/"css"/"draft_catalog.css").read_text(encoding="utf-8")
        cls.app=(BASE/"app.py").read_text(encoding="utf-8")

    def test_positive_and_negative_prompts_both_have_readonly_ru_column(self):
        for field in ("quickPrompt","quickPromptRu","quickNegative","quickNegativeRu"):
            self.assertIn('id="'+field+'"',self.html)
        self.assertIn('id="quickPromptRu" readonly',self.html)
        self.assertIn('id="quickNegativeRu" rows="3" readonly',self.html)
        self.assertGreaterEqual(self.html.count('class="quick-prompts-pair"'),2)
        self.assertIn('className=\'catalog-prompt-pair\'',self.drafts)
        self.assertIn(".catalog-prompt-pair{display:grid",self.css)

    def test_translation_is_passive_and_keeps_original_text(self):
        self.assertIn("draftsman:draft-saved",self.translation)
        self.assertIn("draftsman:startup-ready",self.translation)
        self.assertIn("draftsman:draft-restored",self.translation)
        self.assertIn("d.prompt===current().prompt",self.translation)
        self.assertIn("d.negative_prompt===current().negative_prompt",self.translation)
        self.assertNotIn("method:'POST'",self.translation)
        self.assertNotIn("method: 'POST'",self.translation)
        self.assertIn('result["draft_id"]=',self.app)

    def test_shelf_has_selected_items_arrows_and_eight_per_page(self):
        for field in ("quickShelfGrid","quickShelfPrev","quickShelfNext","quickShelfStatus"):
            self.assertIn('id="'+field+'"',self.html)
        self.assertIn('id="openResults"',self.html)
        self.assertIn("⌕ Поиск",self.html)
        self.assertIn("size=8",self.results)
        self.assertIn("draftsman_selected_sketch",self.results)
        self.assertIn("aria-pressed",self.results)
        self.assertIn("selected",self.results)
        self.assertIn("wheel",self.results)
        self.assertIn("overflow-x:auto",self.html)
        self.assertNotIn("Все результаты</button>",self.html)

    def test_no_extra_gpu_or_services_for_ui(self):
        for file in (self.translation,self.results):
            self.assertNotIn("ollama",file.lower())
            self.assertNotIn("torch",file)
            self.assertNotIn("systemctl",file)


if __name__=="__main__":
    unittest.main()
