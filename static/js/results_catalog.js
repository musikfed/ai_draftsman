/* Results tab + main-page shelf. No duplicated image files. */
(() => {
'use strict';
const E=id=>document.getElementById(id);
if(!E('resultsSection'))return;
const state={page:1,pages:1,request:0,lastRefresh:0,
 shelfPage:1,shelfPages:1,shelfRequest:0,shelfSelectedKey:''};
const gpu={busy:false,starting:false,jobId:'',resultId:0,
 progress:0,stage:'',lastError:''};
const cardMessages=new Map();
let syncingGpu=false;
try{state.shelfSelectedKey=localStorage.getItem('draftsman_selected_sketch')||''}catch(e){}
const make=(tag,text='',cls='')=>{
 const node=document.createElement(tag);
 node.textContent=String(text);
 if(cls)node.className=cls;
 return node;
};
async function api(url,method='GET',data){
 const res=await fetch(url,{method,headers:data?{'Content-Type':'application/json'}:{},
  body:data?JSON.stringify(data):undefined});
 const json=await res.json();
 if(!res.ok)throw Error(json.error||'HTTP '+res.status);
 return json;
}
function note(t){E('resultsPage').textContent=t}
function selectSketch(jobId,variant){
 state.shelfSelectedKey=jobId+':'+variant;
 try{localStorage.setItem('draftsman_selected_sketch',state.shelfSelectedKey)}catch(e){}
 for(const item of E('quickShelfGrid').querySelectorAll('.quick-shelf-item')){
  const active=item.dataset.key===state.shelfSelectedKey;
  item.classList.toggle('selected',active);
  item.setAttribute('aria-pressed',active?'true':'false');
 }
}
function opening(jobId,variant=1){
 selectSketch(jobId,variant);
 E('quickTab').click();
 document.dispatchEvent(new CustomEvent('draftsman:open-result',{detail:{job_id:jobId}}));
}
function broadcastGpu(){
 document.dispatchEvent(new CustomEvent('draftsman:gpu-state',{
  detail:{busy:gpu.busy||gpu.starting,job_id:gpu.jobId}
 }));
 applyBusyToCards();
}
function cardMessage(id,message){
 if(!id)return;
 cardMessages.set(Number(id),String(message));
 const card=E('resultsGrid').querySelector('.result-card[data-result-id="'+id+'"]');
 if(card)drawCardMessage(card,Number(id));
}
function drawCardMessage(card,id){
 let line=card.querySelector('.result-card-feedback');
 const message=cardMessages.get(Number(id))||'';
 if(!message){line?.remove();return}
 if(!line){
  line=make('div','','result-card-feedback');line.setAttribute('role','alert');
  card.querySelector('.result-card-top')?.after(line);
 }
 line.textContent=message;
}
function makeBubbleOverlay(frame){
 const overlay=make('div','','result-rerender-overlay');
 overlay.setAttribute('role','status');
 overlay.setAttribute('aria-label','Выполняется повторная генерация');
 const water=make('div','','result-rerender-water');
 const hues=[175,191,207,235,264,304,46,153];
 for(let i=0;i<26;i++){
  const dot=make('i','','wait-bubble');
  const rnd=Math.random;
  const speed=3.3+rnd()*6;
  dot.style.setProperty('--bubble-x',(2+rnd()*94).toFixed(1)+'%');
  dot.style.setProperty('--bubble-size',(4+rnd()*29).toFixed(1)+'px');
  dot.style.setProperty('--bubble-hue',String(hues[Math.floor(rnd()*hues.length)]));
  dot.style.setProperty('--bubble-drift',(rnd()*86-43).toFixed(1)+'px');
  dot.style.setProperty('--bubble-speed',speed.toFixed(2)+'s');
  dot.style.setProperty('--bubble-delay',(-rnd()*speed).toFixed(2)+'s');
  dot.setAttribute('aria-hidden','true');
  water.append(dot);
 }
 const label=make('div','','result-rerender-label');
 const bar=document.createElement('progress');
 bar.className='result-rerender-progress';bar.max=100;bar.value=0;
 overlay.append(water,label,bar);
 frame.append(overlay);
 return overlay;
}
function applyBusyToCards(){
 const blocked=gpu.busy||gpu.starting;
 const banner=E('resultsBusyBanner');
 banner.classList.toggle('collapsed',!blocked);
 if(blocked){
  banner.textContent='GPU занят · '+(gpu.stage||'подготовка генерации')+
   ' · '+Math.max(0,Math.round(gpu.progress))+'% · новые генерации отключены (без очереди)';
 }
 for(const card of E('resultsGrid').querySelectorAll('.result-card')){
  const rerun=card.querySelector('.result-regenerate');
  if(rerun){rerun.disabled=blocked;rerun.title=blocked?'Дождись завершения текущей генерации':rerun.dataset.readyTitle||rerun.title}
  const id=Number(card.dataset.resultId);
  const frame=card.querySelector('.result-image-frame');
  if(!frame)continue;
  let overlay=frame.querySelector('.result-rerender-overlay');
  if(blocked&&gpu.resultId===id){
   if(!overlay)overlay=makeBubbleOverlay(frame);
   overlay.querySelector('.result-rerender-label').textContent=
    (gpu.stage||'Подготовка модели')+' · '+Math.max(0,Math.round(gpu.progress))+'%';
   overlay.querySelector('progress').value=Number(gpu.progress)||0;
  }else if(overlay){overlay.remove()}
  drawCardMessage(card,id);
 }
}
async function syncGpu(){
 if(syncingGpu || document.hidden)return;
 syncingGpu=true;
 try{
  const active=await api('/api/jobs/active');
  if(active.active){
   gpu.busy=true;gpu.starting=false;gpu.jobId=active.job_id||gpu.jobId;
   gpu.resultId=Number(active.rerun_source_result_id)||0;
   gpu.progress=Number(active.progress)||0;
   gpu.stage=active.stage||'Генерация изображения';
  }else if(!gpu.starting){
   const wasBusy=gpu.busy,previousId=gpu.jobId,previousResult=gpu.resultId;
   if(wasBusy&&previousId){
    let job=null;
    try{job=await api('/api/jobs/'+encodeURIComponent(previousId))}catch(_){}
    if(job&&['queued','running'].includes(job.status)){
     gpu.progress=Number(job.progress)||0;
     gpu.stage=job.stage||'Генерация изображения';
     broadcastGpu();return;
    }
    if(job&&job.status==='failed'&&previousResult){
     cardMessage(previousResult,'Генерация не удалась: '+(job.error||'проверь журнал задания'));
    }
    if(job&&job.status==='completed'&&previousResult){
     cardMessage(previousResult,'Готово! Новый вариант сохранён в результатах.');
    }
    state.shelfPage=1;
    await loadResults(true);
    await loadShelf();
   }
   gpu.busy=false;gpu.jobId='';gpu.resultId=0;gpu.progress=0;gpu.stage='';
  }
  broadcastGpu();
 }catch(error){
  // Network failures must never be interpreted as confirmed GPU idleness.
  if(gpu.busy||gpu.starting){
   gpu.stage='Проверка состояния GPU недоступна';
   broadcastGpu();
  }
  note('Состояние генерации: '+error.message);
 }finally{syncingGpu=false}
}
async function regenerate(draftId,seedMode='random',resultId=null){
 if(gpu.busy||gpu.starting){
  cardMessage(resultId,'GPU занят другой генерацией. Очередь отключена.');
  return;
 }
 if(!confirm('Перегенерировать черновик #'+draftId+
  ' одним вариантом? Исходный PNG останется на диске. Новая версия появится после завершения.'))return;
 gpu.starting=true;gpu.stage='Запуск GPU';gpu.progress=0;
 gpu.resultId=Number(resultId)||0;
 cardMessages.delete(gpu.resultId);
 broadcastGpu();
 try{
  const result=await api('/api/quick/catalog/'+draftId+'/regenerate','POST',
    {seed_mode:seedMode,result_id:resultId});
  gpu.starting=false;gpu.busy=true;gpu.jobId=result.job_id;
  gpu.stage='Ожидание GPU';
  broadcastGpu();
  // Stay on Results. Also update Quick panel's existing job tracker silently.
  document.dispatchEvent(new CustomEvent('draftsman:job-started',
   {detail:{job_id:result.job_id,stayOnResults:true}}));
  note('Запущена генерация версии #'+result.draft_id+' · очередь отключена');
  await syncGpu();
 }catch(error){
  gpu.starting=false;gpu.busy=false;gpu.jobId='';gpu.stage='';
  cardMessage(resultId,'Не удалось запустить: '+error.message);
  note('Повторная генерация: '+error.message);
  broadcastGpu();
  await syncGpu();
 }
}
async function deleteResult(item,control){
 const title='R-'+String(item.index).padStart(6,'0');
 if(item.archived){
  note('Архив только для чтения: сначала верни черновик #'+item.draft_id+' из архива');
  return;
 }
 if(!confirm('НАВСЕГДА удалить '+title+' — '+item.title+
  '?\\nБудут удалены PNG, полноразмерный master PNG, оценка и запись результата в SQLite. '+
  'Черновик и остальные рисунки сохранятся. Отменить удаление после подтверждения нельзя.'))return;
 control.disabled=true;
 try{
  const response=await api('/api/quick/results/'+item.index,'DELETE');
  if(state.shelfSelectedKey===item.job_id+':'+item.variant){
   state.shelfSelectedKey='';
   try{localStorage.removeItem('draftsman_selected_sketch')}catch(e){}
  }
  await loadResults(false);
  await loadShelf();
  document.dispatchEvent(new CustomEvent('draftsman:result-deleted',{
   detail:{job_id:item.job_id,variant:item.variant,result_id:item.index}
  }));
  const warning=response.cleanup_warnings?.length?
   ' Внимание: часть файлов ожидает очистки в .delete-staging.':'';
  note('Удалён '+title+' из SQLite и галереи. Файлов удалено: '+
    response.files_removed+'.'+warning);
 }catch(e){
  note('Удаление '+title+' не выполнено: '+e.message);
 }finally{
  control.disabled=false;
 }
}
function button(text,click){
 const b=make('button',text);b.type='button';b.onclick=click;return b;
}
function box(item){
 // Sketch layout: action bar / large portrait preview / three-button footer.
 // No duplicated thumbnails: the existing job PNG is displayed directly.
 const label='R-'+String(item.index).padStart(6,'0');
 const card=make('article','','result-card'+(item.archived?' archived':''));
 card.setAttribute('aria-label',label+' · '+item.title);
 card.dataset.resultId=String(item.index);

 const top=make('div','','result-card-top');
 const rerun=button('Сгенерировать снова',()=>regenerate(item.draft_id,'random',item.index));
 rerun.className='result-regenerate';
 rerun.title='Новая версия черновика #'+item.draft_id+' с новым Seed';
 rerun.dataset.readyTitle=rerun.title;
 rerun.disabled=gpu.busy||gpu.starting;
 const remove=button('Удалить',()=>deleteResult(item,remove));
 remove.className='delete-result';
 remove.title=item.archived?'Архив только для чтения — сначала разархивируй':
  'Безвозвратно удалить этот вариант, его PNG и запись в SQLite';
 remove.disabled=Boolean(item.archived);
 top.append(rerun,remove);

 const frame=make('div','','result-image-frame');
 frame.title=label+' · '+item.title+
  ' · черновик #'+item.draft_id+' · Seed '+(item.seed??'—');
 const img=document.createElement('img');
 img.src=item.image_url;
 img.alt=item.title+' ('+label+')';
 img.loading='lazy';
 img.decoding='async';
 frame.append(img);
 const index=make('span',label,'result-image-index');
 frame.append(index);
 if(item.rating){
  frame.append(make('span','★ '+item.rating+'/5','result-image-rating'));
 }
 if(item.archived){
  frame.append(make('span','АРХИВ','result-image-archived'));
 }

 const bottom=make('div','','result-card-bottom');
 const open=button('Открыть',()=>opening(item.job_id,item.variant));
 open.title='Открыть оригинал '+label+' в быстром режиме';
 const prompt=button('Промпт',()=>{
  E('quickTab').click();
  document.dispatchEvent(new CustomEvent('draftsman:catalog-open',{
   detail:{draft_id:item.draft_id}
  }));
 });
 prompt.title='Открыть сохранённый промпт и настройки черновика #'+item.draft_id;
 const archive=button(item.archived?'Вернуть':'В архив',async()=>{
  if(!confirm((item.archived?'Разархивировать':'Зафиксировать только для чтения')+
    ' черновик #'+item.draft_id+'?'))return;
  try{
   await api('/api/quick/catalog/'+item.draft_id+'/archive','POST',
    {archived:!item.archived});
   await loadResults(false);await loadShelf();
  }catch(e){note('Ошибка архива: '+e.message)}
 });
 archive.title=item.archived?'Вернуть черновик из архива':
  'Защитить черновик и его результаты от изменений';
 bottom.append(open,prompt,archive);
 card.append(top,frame,bottom);
 return card;
}
async function loadResults(reset=false){
 if(reset)state.page=1;
 const token=++state.request;
 const query=new URLSearchParams({
  q:E('resultsSearch').value.trim(),sort:E('resultsSort').value,
  archive:E('resultsArchive').value,page:String(state.page),size:'12'
 });
 try{
  const response=await api('/api/quick/results?'+query);
  if(token!==state.request)return;
  state.pages=response.pages;
  if(state.page>state.pages){state.page=state.pages;return loadResults(false)}
  const grid=E('resultsGrid');grid.replaceChildren(...response.results.map(box));
  applyBusyToCards();
  if(!response.results.length)grid.append(make('p',
   'Здесь появятся завершённые генерации. Историю PNG не удаляли.','catalog-empty'));
  const from=response.total?(response.page-1)*response.size+1:0;
  note(from+'–'+Math.min(response.total,response.page*response.size)+
    ' из '+response.total+' · страница '+response.page+'/'+response.pages);
  E('resultsPrev').disabled=state.page<=1;
  E('resultsNext').disabled=state.page>=state.pages;
  state.lastRefresh=Date.now();
 }catch(e){note('Ошибка загрузки результатов: '+e.message)}
}
async function loadShelf(){
 if(document.hidden)return;
 const token=++state.shelfRequest;
 const page=state.shelfPage;
 try{
  const response=await api('/api/quick/results?page='+page+'&size=8&sort=newest&archive=all');
  if(token!==state.shelfRequest)return;
  state.shelfPages=response.pages||1;
  if(page>state.shelfPages){state.shelfPage=state.shelfPages;return loadShelf()}
  const target=E('quickShelfGrid');target.replaceChildren();
  for(const item of response.results){
   const key=item.job_id+':'+item.variant;
   const chosen=key===state.shelfSelectedKey;
   const entry=document.createElement('button');
   entry.type='button';entry.className='quick-shelf-item'+(chosen?' selected':'');
   entry.dataset.key=key;entry.title='R-'+String(item.index).padStart(6,'0')+' · '+item.title;
   entry.setAttribute('aria-pressed',chosen?'true':'false');
   entry.setAttribute('aria-label','Выбрать эскиз R-'+String(item.index).padStart(6,'0'));
   entry.onclick=()=>opening(item.job_id,item.variant);
   const image=document.createElement('img');image.src=item.image_url;
   image.alt=item.title;image.loading='lazy';
   entry.append(image,make('div','R-'+String(item.index).padStart(6,'0')+
    ' · '+item.title,'shelf-title'));
   target.append(entry);
  }
  if(!response.results.length)target.append(make('span',
   'Пока нет готовых эскизов.','catalog-meta'));
  E('quickShelfPrev').disabled=state.shelfPage<=1;
  E('quickShelfNext').disabled=state.shelfPage>=state.shelfPages;
  const first=response.total?(state.shelfPage-1)*8+1:0;
  const last=Math.min(response.total,state.shelfPage*8);
  E('quickShelfStatus').textContent=first+'–'+last+' из '+response.total+
   ' · страница '+state.shelfPage+'/'+state.shelfPages+
   ' · кликни эскиз, чтобы выделить и открыть справа';
 }catch(e){
  E('quickShelfStatus').textContent='Не удалось загрузить эскизы: '+e.message;
 }
}
E('quickShelfPrev').onclick=()=>{
 if(state.shelfPage>1){state.shelfPage--;loadShelf()}
};
E('quickShelfNext').onclick=()=>{
 if(state.shelfPage<state.shelfPages){state.shelfPage++;loadShelf()}
};
E('quickShelfGrid').addEventListener('wheel',event=>{
 const grid=E('quickShelfGrid');
 if(grid.scrollWidth<=grid.clientWidth||!event.deltaY||Math.abs(event.deltaX)>Math.abs(event.deltaY))return;
 event.preventDefault();
 grid.scrollLeft+=event.deltaY;
},{passive:false});
E('resultsRefresh').onclick=()=>loadResults(true);
E('resultsPrev').onclick=()=>{if(state.page>1){state.page--;loadResults()}};
E('resultsNext').onclick=()=>{if(state.page<state.pages){state.page++;loadResults()}};
let searchTimer=0;
E('resultsSearch').addEventListener('input',()=>{
 clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadResults(true),300);
});
for(const id of ['resultsSort','resultsArchive']){
 E(id).addEventListener('change',()=>loadResults(true));
}
E('resultsTab').addEventListener('click',()=>loadResults(true));
document.addEventListener('draftsman:job-completed',()=>{
 state.shelfPage=1;loadShelf();
 if(!E('resultsSection').classList.contains('collapsed'))loadResults(true);
 syncGpu();
});
document.addEventListener('visibilitychange',()=>{
 if(!document.hidden){loadShelf();syncGpu();
  if(!E('resultsSection').classList.contains('collapsed'))loadResults(false)}
});
// Only lightweight HTTP reads while the user keeps a visible studio tab open.
// No background service and no requests to model runtimes.
setInterval(()=>{
 if(document.hidden)return;
 if(!E('resultsSection').classList.contains('collapsed'))loadResults(false);
 if(!E('quickSection').classList.contains('collapsed'))loadShelf();
},60000);
loadShelf();
if(!E('resultsSection').classList.contains('collapsed'))loadResults(true);
syncGpu();
setInterval(()=>{if(!document.hidden)syncGpu()},4000);
window.DraftsmanRegenerate=regenerate;
})();
