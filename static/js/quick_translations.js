/* Show cached Russian translations for the exact active saved draft.
 * Translation is started by explicit Save on the server, or resumed after
 * a deferred save when the single GPU is idle. No per-keystroke model calls.
 */
(()=>{
 'use strict';
 const E=id=>document.getElementById(id);
 if(!E('quickPromptRu')||!E('quickNegativeRu'))return;
 const state={draftId:null,serial:0,timer:null,nextAttempt:0,serverStatus:''};
 const current=()=>({prompt:E('quickPrompt').value,negative_prompt:E('quickNegative').value});
 const same=d=>d.prompt===current().prompt &&
                d.negative_prompt===current().negative_prompt;
 const info=message=>{if(E('quickTranslationStatus'))
   E('quickTranslationStatus').textContent=message};
 function display(pos,neg,message){
  E('quickPromptRu').value=pos;
  E('quickNegativeRu').value=neg;
  info(message);
 }
 function cancel(){
  state.serial++;
  if(state.timer){clearTimeout(state.timer);state.timer=null}
 }
 function nextCheck(id,serial,ms=20000){
  if(serial!==state.serial||document.hidden)return;
  state.timer=setTimeout(()=>check(id,serial),ms);
 }
 async function requestMissingTranslation(id,serial){
  const now=Date.now();
  if(now<state.nextAttempt)return;
  // Never start the LLM while the GPU is rendering. The server repeats
  // the GPU check, so concurrent browser tabs remain safe.
  try{
   const busyResponse=await fetch('/api/jobs/active');
   if(!busyResponse.ok)throw Error('GPU status HTTP '+busyResponse.status);
   const active=await busyResponse.json();
   if(serial!==state.serial)return;
   if(active.active){
    state.serverStatus='deferred';
    state.nextAttempt=now+20000;
    info('GPU занят: оба перевода будут автоматически выполнены после завершения генерации.');
    return;
   }
   const response=await fetch('/api/quick/catalog/'+encodeURIComponent(id)+'/translate',
    {method:'POST'});
   const payload=await response.json();
   if(serial!==state.serial)return;
   if(!response.ok)throw Error(payload.error||'HTTP '+response.status);
   state.serverStatus=payload.status||'translating';
   state.nextAttempt=now+(
    state.serverStatus==='retry_later'?3600000:
    state.serverStatus==='translating'?90000:
    state.serverStatus==='ready'?60000:20000);
   if(state.serverStatus==='retry_later')
    info('Qwen пока недоступен. Оригинал сохранён; повторим перевод после паузы.');
   else if(state.serverStatus==='deferred')
    info('Перевод ожидает освобождения GPU — черновик уже сохранён в SQLite.');
   else if(state.serverStatus==='translating')
    info('Qwen переводит оба промпта. Сохраним русский текст в SQLite и покажем справа.');
  }catch(e){
   if(serial!==state.serial)return;
   state.nextAttempt=now+60000;
   info('Не удалось запустить перевод: '+e.message+'. Оригинал сохранён.');
  }
 }
 async function check(id,serial){
  if(serial!==state.serial||state.draftId!==id||document.hidden)return;
  try{
   const response=await fetch('/api/quick/catalog/'+encodeURIComponent(id));
   if(!response.ok)throw Error('HTTP '+response.status);
   const draft=await response.json();
   if(serial!==state.serial||!same(draft))return;
   if(draft.prompt_ru!==null && draft.negative_prompt_ru!==null){
    display(draft.prompt_ru||'',draft.negative_prompt_ru||'',
     'Перевод готов: оригиналы и оба русских текста сохранены в SQLite.');
    return;
   }
   if(draft.archived){
    display(draft.prompt_ru||'Перевод для этой версии отсутствует.',
     draft.negative_prompt_ru||'Перевод для этой версии отсутствует.',
     'Архив только для чтения; перевод не создаётся.');
    return;
   }
   E('quickPromptRu').value=draft.prompt_ru??'Ожидается перевод положительного промпта…';
   E('quickNegativeRu').value=draft.negative_prompt_ru??'Ожидается перевод негативного промпта…';
   await requestMissingTranslation(id,serial);
   nextCheck(id,serial,state.serverStatus==='translating'?15000:20000);
  }catch(e){
   if(serial!==state.serial)return;
   info('Перевод временно недоступен: '+e.message+'. Сохранённый оригинал не меняется.');
   nextCheck(id,serial,30000);
  }
 }
 function followDraft(id,translationStatus=''){
  cancel();
  const n=Number(id);
  if(!Number.isSafeInteger(n)||n<=0){
   state.draftId=null;
   display('','', 'Нажми «Сохранить черновик» для автоматического перевода на русский.');
   return;
  }
  state.draftId=n;
  state.serverStatus=translationStatus||'';
  // An explicit Save already asked the backend to translate. Avoid
  // double-starting a running translation (the backend deduplicates too).
  state.nextAttempt=Date.now()+(
   translationStatus==='translating'?90000:
   translationStatus==='deferred'?20000:
   translationStatus==='retry_later'?3600000:0);
  display('Загружается сохранённый перевод…','Загружается сохранённый перевод…',
   'Проверяем русский перевод черновика #'+n+' в SQLite.');
  check(n,state.serial);
 }
 for(const id of ['quickPrompt','quickNegative']){
  E(id).addEventListener('input',()=>{
   cancel();
   state.draftId=null;
   display('Текст изменён. Сохрани новую версию для перевода.',
    'Текст изменён. Сохрани новую версию для перевода.',
    'Черновик ещё не сохранён: перевод старой версии скрыт, чтобы не путать тексты.');
  });
 }
 document.addEventListener('draftsman:draft-saved',event=>
  followDraft(event.detail?.draft_id,event.detail?.translation_status));
 document.addEventListener('draftsman:draft-restored',event=>
  followDraft(event.detail?.draft_id));
 document.addEventListener('draftsman:startup-ready',event=>
  followDraft(event.detail?.draft_id));
 document.addEventListener('draftsman:job-completed',()=>{
  if(state.draftId && !document.hidden){
   cancel();state.nextAttempt=0;check(state.draftId,state.serial);
  }
 });
 document.addEventListener('visibilitychange',()=>{
  if(document.hidden){
   if(state.timer){clearTimeout(state.timer);state.timer=null}
  }else if(state.draftId){
   cancel();check(state.draftId,state.serial);
  }
 });
 display('','','Нажми «Сохранить черновик»: перевод появится в правых колонках и сохранится в SQLite.');
})();
