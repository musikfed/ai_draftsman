/* Results tab + main-page shelf. No duplicated image files. */
(() => {
'use strict';
const E=id=>document.getElementById(id);
if(!E('resultsSection'))return;
const state={page:1,pages:1,request:0,lastRefresh:0};
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
function opening(jobId){
 E('quickTab').click();
 document.dispatchEvent(new CustomEvent('draftsman:open-result',{detail:{job_id:jobId}}));
}
async function regenerate(draftId,seedMode='random'){
 if(!confirm('Перегенерировать черновик #'+draftId+
  ' одним вариантом? Исходная версия и PNG останутся на диске. Будет создан новый черновик.'))return;
 try{
  const result=await api('/api/quick/catalog/'+draftId+'/regenerate','POST',
    {seed_mode:seedMode});
  E('quickTab').click();
  document.dispatchEvent(new CustomEvent('draftsman:job-started',{detail:{job_id:result.job_id}}));
  note('Создана новая версия #'+result.draft_id+', GPU задание запущено.');
 }catch(e){note('Не удалось перегенерировать: '+e.message)}
}
function button(text,click){
 const b=make('button',text);b.type='button';b.onclick=click;return b;
}
function box(item){
 const card=make('div','','result-card'+(item.archived?' archived':''));
 const img=document.createElement('img');
 img.src=item.image_url;img.alt='Результат R-'+String(item.index).padStart(6,'0');
 img.loading='lazy';
 card.append(img);
 card.append(make('strong','R-'+String(item.index).padStart(6,'0')+' · '+item.title));
 const when=item.created_at?new Date(item.created_at*1000).toLocaleString('ru-RU'):'время неизвестно';
 card.append(make('div',when+' · '+(item.rating?item.rating+' ★':'без оценки')+
    (item.archived?' · АРХИВ / только чтение':''),'result-sub'));
 card.append(make('div','Черновик #'+item.draft_id+
  ' · вариант '+item.variant+' · Seed '+(item.seed??'—'),'result-sub'));
 const actions=make('div','','result-actions');
 actions.append(button('Открыть',()=>opening(item.job_id)));
 actions.append(button('Черновик',()=>{
  E('quickTab').click();
  document.dispatchEvent(new CustomEvent('draftsman:catalog-open',{detail:{draft_id:item.draft_id}}));
 }));
 actions.append(button('Перегенерировать',()=>regenerate(item.draft_id)));
 actions.append(button(item.archived?'Вернуть из архива':'В архив',async()=>{
  if(!confirm((item.archived?'Разархивировать':'Зафиксировать только для чтения')+
    ' черновик #'+item.draft_id+'?'))return;
  try{
   await api('/api/quick/catalog/'+item.draft_id+'/archive','POST',
    {archived:!item.archived});
   await loadResults(false);await loadShelf();
  }catch(e){note('Ошибка архива: '+e.message)}
 }));
 card.append(actions);return card;
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
  const grid=E('resultsGrid');grid.replaceChildren(...response.results.map(box));
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
 try{
  const response=await api('/api/quick/results?page=1&size=8&sort=newest&archive=all');
  const target=E('quickShelfGrid');
  target.replaceChildren();
  for(const item of response.results){
   const a=document.createElement('a');
   a.href='#';a.title='R-'+String(item.index).padStart(6,'0')+' · '+item.title;
   a.onclick=e=>{e.preventDefault();opening(item.job_id)};
   const image=document.createElement('img');image.src=item.image_url;
   image.alt=item.title;image.loading='lazy';
   a.append(image,make('div','R-'+String(item.index).padStart(6,'0')+
     ' · '+item.title,'shelf-title'));
   target.append(a);
  }
  if(!response.results.length)target.append(make('span',
   'Пока нет готовых изображений. Сгенерируй первый эскиз.','catalog-meta'));
 }catch(e){E('quickShelfGrid').replaceChildren(make('span','Эскизы временно недоступны.','catalog-meta'))}
}
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
 loadShelf();
 if(!E('resultsSection').classList.contains('collapsed'))loadResults(true);
});
document.addEventListener('visibilitychange',()=>{
 if(!document.hidden){loadShelf();
  if(!E('resultsSection').classList.contains('collapsed'))loadResults(false)}
});
// Only lightweight HTTP reads while the user keeps a visible studio tab open.
// No background system service and no requests to CUDA/Ollama.
setInterval(()=>{
 if(document.hidden)return;
 if(!E('resultsSection').classList.contains('collapsed'))loadResults(false);
 if(!E('quickSection').classList.contains('collapsed'))loadShelf();
},60000);
loadShelf();
if(!E('resultsSection').classList.contains('collapsed'))loadResults(true);
window.DraftsmanRegenerate=regenerate;
})();
