/* Read-only translations alongside the active prompts.
   Qwen is triggered by Save in Flask, never by a UI timer or every keystroke. */
(() => {
 'use strict';
 const E=id=>document.getElementById(id);
 if(!E('quickPromptRu')||!E('quickNegativeRu'))return;
 const state={draftId:null,serial:0,timer:null};
 const current=()=>({prompt:E('quickPrompt').value,negative_prompt:E('quickNegative').value});
 const reset=(text='Сохрани черновик, чтобы увидеть его перевод.')=>{
   E('quickPromptRu').value=text;
   E('quickNegativeRu').value=text;
 };
 const same=d=>d.prompt===current().prompt&&d.negative_prompt===current().negative_prompt;
 function cancel(){
   state.serial++;
   if(state.timer){clearTimeout(state.timer);state.timer=null}
 }
 async function check(id,serial,attempt=0){
   if(serial!==state.serial||state.draftId!==id||document.hidden)return;
   try{
     const response=await fetch('/api/quick/catalog/'+encodeURIComponent(id));
     if(!response.ok)throw Error('HTTP '+response.status);
     const d=await response.json();
     if(serial!==state.serial||!same(d))return;
     if(d.prompt_ru!==null&&d.negative_prompt_ru!==null){
       E('quickPromptRu').value=d.prompt_ru||'';
       E('quickNegativeRu').value=d.negative_prompt_ru||'';
       return;
     }
     if(d.archived){
       reset('Архив только для чтения; перевод не создавался.');
       return;
     }
     E('quickPromptRu').value=d.prompt_ru??'Перевод готовится и будет сохранён в SQLite.';
     E('quickNegativeRu').value=d.negative_prompt_ru??'Перевод готовится и будет сохранён в SQLite.';
     if(attempt>=24){
       if(d.prompt_ru===null)E('quickPromptRu').value='Перевод пока недоступен; оригинал сохранён.';
       if(d.negative_prompt_ru===null)E('quickNegativeRu').value='Перевод пока недоступен; оригинал сохранён.';
       return;
     }
     state.timer=setTimeout(()=>check(id,serial,attempt+1),10000);
   }catch(e){
     if(serial!==state.serial)return;
     reset('Перевод пока не загрузился: '+e.message);
   }
 }
 function followDraft(id){
   cancel();
   const n=Number(id);
   if(!Number.isSafeInteger(n)||n<=0){
     state.draftId=null;reset();
     return;
   }
   state.draftId=n;
   reset('Загружается сохранённый перевод…');
   check(n,state.serial);
 }
 for(const id of ['quickPrompt','quickNegative']){
   E(id).addEventListener('input',()=>{
     cancel();state.draftId=null;
     reset('Текст изменён. Сохрани новую версию для автоматического перевода.');
   });
 }
 document.addEventListener('draftsman:draft-saved',event=>followDraft(event.detail?.draft_id));
 document.addEventListener('draftsman:draft-restored',event=>followDraft(event.detail?.draft_id));
 document.addEventListener('draftsman:startup-ready',event=>followDraft(event.detail?.draft_id));
 document.addEventListener('visibilitychange',()=>{
   if(state.timer&&document.hidden){
     clearTimeout(state.timer);state.timer=null;
   }
   if(!document.hidden&&state.draftId){
     cancel();check(state.draftId,state.serial);
   }
 });
 reset('Перевод появится рядом после сохранения черновика.');
})();
