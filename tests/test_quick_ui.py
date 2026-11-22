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
        self.assertIn("if(draft.prompt_ru!==null && draft.negative_prompt_ru!==null)",self.translation)
        self.assertIn("requestMissingTranslation(id,serial)",self.translation)
        self.assertIn("if(active.active)",self.translation)
        self.assertIn("{method:'POST'}",self.translation)
        self.assertIn("state.nextAttempt",self.translation)
        self.assertIn("d.prompt===current().prompt",self.translation)
        self.assertIn("quickTranslationStatus",self.translation)
        self.assertIn('result["draft_id"]=',self.app)

    def test_blank_project_button_visible_and_uses_existing_project_api(self):
        self.assertIn('id="quickCreateBlankProject"',self.html)
        self.assertIn('id="projectSettingsPanel"',self.html)
        self.assertIn('async function createBlankProject()',self.html)
        self.assertIn("template:'blank'",self.html)
        self.assertIn("switchMode('graph')",self.html)
        self.assertIn("$('projectSettingsPanel').open=true",self.html)
        self.assertIn("$('quickCreateBlankProject').onclick=()=>task(createBlankProject)",self.html)
        self.assertIn("$('addProject').onclick=()=>task(createBlankProject)",self.html)
        self.assertIn('id="quickTranslationStatus"',self.html)
        self.assertIn('translation_status:d.translation_status',self.html)

    def test_translation_deferred_until_gpu_finishes_and_is_read_only(self):
        self.assertIn("'/api/jobs/active'",self.translation)
        self.assertIn("state.serverStatus='deferred'",self.translation)
        self.assertIn("draftsman:job-completed",self.translation)
        self.assertIn("retry_later",self.translation)
        self.assertIn("document.hidden",self.translation)
        self.assertIn("same(draft)",self.translation)
        self.assertIn("Перевод готов:",self.translation)
        self.assertNotIn("'/api/chat'",self.translation)

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

    def test_delete_result_button_confirms_and_refreshes_both_galleries(self):
        self.assertIn("button('Удалить',()=>deleteResult(item,remove))",self.results)
        self.assertIn("await api('/api/quick/results/'+item.index,'DELETE')",self.results)
        self.assertIn("if(!confirm('НАВСЕГДА удалить '",self.results)
        self.assertIn("remove.disabled=Boolean(item.archived)",self.results)
        self.assertIn("await loadResults(false)",self.results)
        self.assertIn("await loadShelf()",self.results)
        self.assertIn("draftsman:result-deleted",self.results)
        self.assertIn("delete-result:hover",self.html)
        self.assertIn("document.addEventListener('draftsman:result-deleted'",self.html)

    def test_result_cards_follow_sketch_two_rows_of_actions_and_large_preview(self):
        # Top: regenerate / delete; centre: image; bottom: open / prompt / archive.
        self.assertIn("const top=make('div','','result-card-top')",self.results)
        self.assertIn("const frame=make('div','','result-image-frame')",self.results)
        self.assertIn("const bottom=make('div','','result-card-bottom')",self.results)
        self.assertIn("const rerun=button('Сгенерировать снова'",self.results)
        self.assertIn("const remove=button('Удалить',()=>deleteResult(item,remove))",self.results)
        self.assertIn("const open=button('Открыть'",self.results)
        self.assertIn("const prompt=button('Промпт'",self.results)
        self.assertIn("'В архив'",self.results)
        self.assertIn("top.append(rerun,remove)",self.results)
        self.assertIn("bottom.append(open,prompt,archive)",self.results)
        self.assertIn("card.append(top,frame,bottom)",self.results)
        self.assertIn("aspect-ratio:4/5",self.html)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))",self.html)
        self.assertIn("@media(max-width:860px)",self.html)
        self.assertIn("grid-template-columns:minmax(0,1fr)",self.html)
        self.assertIn("result-image-index",self.results)

    def test_sketch_buttons_preserve_existing_result_actions(self):
        self.assertIn("()=>regenerate(item.draft_id,'random',item.index)",self.results)
        self.assertIn("deleteResult(item,remove)",self.results)
        self.assertIn("opening(item.job_id,item.variant)",self.results)
        self.assertIn("draftsman:catalog-open",self.results)
        self.assertIn("'/api/quick/catalog/'+item.draft_id+'/archive'",self.results)
        self.assertIn("remove.disabled=Boolean(item.archived)",self.results)

    def test_rerender_stays_on_results_with_bubbles_and_progress(self):
        self.assertIn("const gpu={busy:false,starting:false",self.results)
        self.assertIn("function makeBubbleOverlay(frame)",self.results)
        self.assertIn("result-rerender-overlay",self.results)
        self.assertIn("result-rerender-water",self.results)
        self.assertIn("for(let i=0;i<26;i++)",self.results)
        self.assertIn("'/api/quick/catalog/'+draftId+'/regenerate'",self.results)
        self.assertIn("stayOnResults:true",self.results)
        self.assertIn("if(!event.detail?.stayOnResults)switchMode('quick')",self.html)
        self.assertIn("result-rerender-progress",self.html)
        self.assertIn("result-rerender-label",self.html)
        self.assertIn("result-card-feedback",self.html)

    def test_single_gpu_busy_state_disables_all_start_buttons(self):
        self.assertIn("'/api/jobs/active'",self.results)
        self.assertIn("gpu.busy||gpu.starting",self.results)
        self.assertIn("rerun.disabled=blocked",self.results)
        self.assertIn("setInterval(()=>{if(!document.hidden)syncGpu()},4000)",self.results)
        self.assertIn("draftsman:gpu-state",self.results)
        self.assertIn("document.addEventListener('draftsman:gpu-state'",self.html)
        self.assertIn("renderBusyServer||activeRendering||generationLaunching",self.html)
        self.assertIn("if(renderBusyServer||generationLaunching||activeRendering)",self.html)
        self.assertIn("setRenderControlsBusy(busy)",self.html)
        self.assertIn("id=\"resultsBusyBanner\"",self.html)
        self.assertNotIn("E('quickTab').click();\n  document.dispatchEvent(new CustomEvent('draftsman:job-started'",self.results)

    def test_no_extra_gpu_or_services_for_ui(self):
        for file in (self.translation,self.results):
            self.assertNotIn("ollama",file.lower())
            self.assertNotIn("torch",file)
            self.assertNotIn("systemctl",file)


if __name__=="__main__":
    unittest.main()
