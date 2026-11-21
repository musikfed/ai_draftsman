/* Searchable local draft library. No dependencies, external APIs, or GPU rendering. */
(() => {
'use strict';
const panel=document.getElementById('catalogPanel');
if(!panel)return;
const E=id=>document.getElementById(id);
const state={page:1,pages:1,selected:0,rows:[],version:0,timer:0,poll:0};
function label(tag,value,klass){
 const element=document.createElement(tag);
 element.textContent=value==null?'':String(value);
 if(klass)element.className=klass;
 return element;
}
async function api(url,method='GET',data){
 const response=await fetch(url,{method,headers:data?{'Content-Type':'application/json'}:{},
  body:data?JSON.stringify(data):undefined});
 const result=await response.json();
 if(!response.ok)throw Error(result.error||'HTTP '+response.status);
 return result;
}
function notice(message){E('catalogCount').textContent=message}
function rating(value,callback,readonly=false){
 const row=label('div','','catalog-rating');
 function draw(current){
  row.replaceChildren();
  for(let score=1;score<=5;score++){
   const b=label('button','★',score<=current?'on':'');
   b.type='button';b.title=readonly?'Архив: только чтение':'Поставить '+score+' из 5';
   b.disabled=readonly;
   b.setAttribute('aria-label','Оценка '+score+' из 5');
   b.onclick=async()=>{try{await callback(score);draw(score)}catch(e){notice(e.message)}};
   row.append(b);
  }
 }
 draw(Number(value)||0);
 return row;
}
function textfield(title,value,editable){
 const box=document.createElement('div');
 box.append(label('label',title));
 const area=document.createElement('textarea');
 area.value=value||'';area.rows=editable?3:4;
 area.readOnly=!editable;
 area.setAttribute('aria-label',title);
 box.append(area);
 return {box,area};
}
async function query(reset){
 if(reset)state.page=1;
 const version=++state.version;
 const qs=new URLSearchParams({
  q:E('catalogSearch').value.trim(),sort:E('catalogSort').value,
  rating:E('catalogMinRating').value,
  images:E('catalogImagesOnly').checked?'1':'0',
  archive:E('catalogArchive').value,
  page:String(state.page),size:'8'
 });
 try{
  const data=await api('/api/quick/catalog?'+qs);
  if(version!==state.version)return;
  state.rows=data.drafts||[];state.pages=data.pages;
  const list=E('catalogList');list.replaceChildren();
  for(const d of state.rows){
   const button=label('button','','catalog-entry');
   button.type='button';
   button.append(label('strong',(d.title||'Черновик')+' · #'+d.id));
   button.append(label('small',d.created_at+' · '+(d.rating?'★'+d.rating:'без оценки')+
     ' · '+d.jobs+' генераций · '+(d.archived?'АРХИВ / чтение':'активен')+
     ' · '+(d.translated?'RU ✓':'перевод ожидается')));
   button.append(label('span',d.preview_ru||d.preview||'Без текста','catalog-short'));
   button.onclick=()=>choose(d.id);
   list.append(button);
  }
  if(!state.rows.length)list.append(label('p','Ничего не найдено. Измени фильтры.','catalog-empty'));
  const first=data.total?(data.page-1)*data.size+1:0;
  notice(first+'–'+Math.min(data.total,data.page*data.size)+' из '+data.total+
         ' · страница '+data.page+'/'+data.pages);
  E('catalogPrev').disabled=state.page<=1;
  E('catalogNext').disabled=state.page>=state.pages;
  if(state.rows.length){
   const valid=state.rows.some(d=>d.id===state.selected);
   await choose(valid?state.selected:state.rows[0].id);
  }else{state.selected=0;E('catalogDetail').replaceChildren(
    label('p','Сохранённых записей по этому запросу нет.','catalog-empty'))}
 }catch(e){notice('Ошибка поиска: '+e.message)}
}
function imageBox(img,jobId,readonly=false){
 const c=label('div','','catalog-image-card');
 const link=document.createElement('a');link.href=img.url;link.target='_blank';
 link.rel='noopener';
 const picture=document.createElement('img');picture.src=img.url;
 picture.loading='lazy';picture.alt='Результат генерации '+img.variant;
 link.append(picture);c.append(link);
 c.append(label('small','Вариант '+img.variant+' · '+jobId.slice(0,9)));
 c.append(rating(img.rating,async n=>{
  await api('/api/quick/images/'+jobId+'/'+img.variant+'/rating','PATCH',
   {rating:n,note:img.note||''});
 },readonly));
 return c;
}
async function choose(id){
 if(state.poll)clearTimeout(state.poll);
 state.selected=id;
 const version=state.version;
 E('catalogList').querySelectorAll('.catalog-entry').forEach((item,i)=>{
  item.classList.toggle('selected',state.rows[i]?.id===id);
 });
 const root=E('catalogDetail');
 root.replaceChildren(label('span','Загружаю черновик #'+id+'...','catalog-meta'));
 try{
  const d=await api('/api/quick/catalog/'+id);
  if(state.selected!==id||version!==state.version)return;
  root.replaceChildren(label('h3','Черновик #'+id));
  root.append(label('small','Сохранён: '+d.created_at+
    (d.archived?' · АРХИВ — только чтение':' · активный черновик'),'catalog-meta'));
  const name=document.createElement('input');
  name.value=d.title||'';name.maxLength=140;name.placeholder='Название для удобного поиска';
  name.readOnly=Boolean(d.archived);
  name.setAttribute('aria-label','Название черновика');
  root.append(name);
  root.append(label('span','Оценка черновика','catalog-meta'));
  root.append(rating(d.rating,async score=>{
   await api('/api/quick/catalog/'+id,'PATCH',{rating:score});
   const item=state.rows.find(v=>v.id===id);if(item)item.rating=score;
  },Boolean(d.archived)));
  const orig=textfield('Промпт · оригинал',d.prompt,false);
  const negative=textfield('Негативный промпт · оригинал',d.negative_prompt,false);
  const translated=textfield('Промпт · русский перевод',
   d.prompt_ru===null?'Перевод готовится автоматически один раз...':d.prompt_ru,false);
  const translatedNeg=textfield('Негативный промпт · русский перевод',
   d.negative_prompt_ru===null?'Перевод ожидается...':d.negative_prompt_ru,false);
  const positiveRow=document.createElement('div');positiveRow.className='catalog-prompt-pair';
  positiveRow.append(orig.box,translated.box);
  const negativeRow=document.createElement('div');negativeRow.className='catalog-prompt-pair';
  negativeRow.append(negative.box,translatedNeg.box);
  root.append(positiveRow,negativeRow);
  const note=textfield('Заметка (что понравилось, что исправить)',d.note,!d.archived);
  root.append(note.box);
  const buttons=label('div','','catalog-foot');
  const restore=label('button','Загрузить текст в редактор');
  restore.onclick=()=>{
   E('quickTab').click();
   E('quickPrompt').value=d.prompt;E('quickNegative').value=d.negative_prompt;
   try{
    localStorage.setItem('draftsman_setting_quickPrompt',d.prompt);
    localStorage.setItem('draftsman_setting_quickNegative',d.negative_prompt);
   }catch(e){}
   document.dispatchEvent(new CustomEvent('draftsman:draft-restored',{detail:{draft_id:id}}));
   notice('Черновик #'+id+' открыт в редакторе. Старые версии не изменены.');
  };
  const save=label('button','Сохранить название и заметку');
  save.disabled=Boolean(d.archived);
  save.onclick=async()=>{
   try{
    await api('/api/quick/catalog/'+id,'PATCH',{title:name.value,note:note.area.value});
    const entry=state.rows.find(v=>v.id===id);
    if(entry)entry.title=name.value;
    notice('Название и заметка к черновику #'+id+' сохранены');
   }catch(e){notice('Ошибка: '+e.message)}
  };
  const archive=label('button',d.archived?'Вернуть из архива':'В архив · только чтение');
  archive.onclick=async()=>{
   if(!confirm((d.archived?'Разархивировать':'Зафиксировать только для чтения')+
        ' черновик #'+id+'? Оригинальные промпты и рисунки останутся.'))return;
   try{
    await api('/api/quick/catalog/'+id+'/archive','POST',{archived:!d.archived});
    await query(false);
   }catch(e){notice('Архив: '+e.message)}
  };
  const regenerate=label('button','Перегенерировать · новый Seed');
  regenerate.onclick=()=>window.DraftsmanRegenerate?.(id,'random');
  const repeat=label('button','Повторить · прежний Seed');
  repeat.onclick=()=>window.DraftsmanRegenerate?.(id,'same');
  buttons.append(restore,save,archive,regenerate,repeat);root.append(buttons);
  root.append(label('h4','Результаты генераций'));
  let images=0;
  for(const job of d.jobs||[]){
   if(job.images?.length){
    const grid=label('div','','catalog-images');
    for(const im of job.images){grid.append(imageBox(im,job.job_id,Boolean(d.archived)));images++}
    root.append(grid);
   }else root.append(label('small','Задание '+job.job_id.slice(0,9)+
     ' · '+job.status+' · без готовых PNG','catalog-meta'));
  }
  if(!d.jobs?.length)root.append(label('p',
   'Пока нет генераций. Черновик всё равно сохранён.','catalog-empty'));
  if(images)root.append(label('small','Рисунков: '+images+
   '. Открой миниатюру для полного размера и поставь оценку отдельному изображению.',
   'catalog-meta'));
  if(!d.archived && (d.prompt_ru===null||d.negative_prompt_ru===null)){
   await translateCached(id,version,translated.area,translatedNeg.area,0);
  }else if(d.archived&&d.prompt_ru===null){
   translated.area.value='Архив только для чтения · перевод не создавался.';
  }
 }catch(e){notice('Ошибка загрузки: '+e.message)}
}
async function translateCached(id,version,positive,negative,attempt){
 if(!panel.open||state.selected!==id||version!==state.version||attempt>12)return;
 try{
  const response=await api('/api/quick/catalog/'+id+'/translate','POST');
  if(response.status==='ready'){
   const fresh=await api('/api/quick/catalog/'+id);
   if(state.selected===id){positive.value=fresh.prompt_ru||'';negative.value=fresh.negative_prompt_ru||''}
   return;
  }
  positive.value=response.status==='deferred'?
   'Генерация использует GPU; перевод будет сделан после освобождения видеопамяти.':
   'Qwen переводит в фоновом потоке Flask. Результат сохранится в SQLite.';
  const delay=response.status==='deferred'?15000:12000;
  state.poll=setTimeout(async()=>{
   if(state.selected!==id||!panel.open||version!==state.version)return;
   try{
    const d=await api('/api/quick/catalog/'+id);
    if(d.prompt_ru!==null&&d.negative_prompt_ru!==null){
     positive.value=d.prompt_ru;negative.value=d.negative_prompt_ru;
     return;
    }
   }catch(e){}
   translateCached(id,version,positive,negative,attempt+1);
  },delay);
 }catch(e){positive.value='Перевод пока недоступен: '+e.message}
}
let debounce=0;
E('catalogSearch').addEventListener('input',()=>{
 clearTimeout(debounce);debounce=setTimeout(()=>query(true),300);
});
for(const field of ['catalogSort','catalogMinRating','catalogImagesOnly','catalogArchive']){
 E(field).addEventListener('change',()=>query(true));
}
E('catalogRefresh').onclick=()=>query(true);
E('catalogPrev').onclick=()=>{if(state.page>1){state.page--;query(false)}};
E('catalogNext').onclick=()=>{if(state.page<state.pages){state.page++;query(false)}};
document.addEventListener('draftsman:catalog-open',event=>{
 const id=Number(event.detail?.draft_id||0);
 if(!Number.isInteger(id)||id<=0)return;
 E('catalogArchive').value='all';
 E('catalogSearch').value='#'+id;
 panel.open=true;
 query(true);
});
document.addEventListener('draftsman:job-completed',()=>{
 if(panel.open)query(false);
});
panel.addEventListener('toggle',()=>{
 if(panel.open)query(true);
 else if(state.poll){clearTimeout(state.poll);state.poll=0}
});
})();
