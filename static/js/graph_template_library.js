/* Independent, SQLite-backed graph template library. No GPU or Ollama calls. */
(()=>{
 'use strict';
 const E=id=>document.getElementById(id);
 const chooser=E('graphTemplateSelect');
 if(!chooser)return;
 const create=E('createGraphTemplate');
 const panel=E('graphTemplateDiagram');
 const legend=E('graphTemplateNodeLegend');
 const desc=E('graphTemplateDescription');
 const help=E('graphTemplateHelp');
 const note=E('graphTemplateNote');
 const heading=E('graphTemplatesPanel').querySelector('summary');
 const ns='http://www.w3.org/2000/svg';
 let templates=[],definition=null,requested=0,creating=false;
 const english=()=>E('lang')?.value==='en';
 const message=(text)=>{desc.textContent=text};
 function option(value,label){
  const node=document.createElement('option');node.value=value;
  node.textContent=label;return node;
 }
 function name(t){return english()?t.title_en:t.title_ru}
 function updateLanguage(){
  heading.textContent=english()?'📚 Graph library · 7 examples':'📚 Библиотека графов · 7 готовых схем';
  create.textContent=english()?'+ Create from template':'+ Создать по схеме';
  help.textContent=english()?
    'Select a graph, inspect the node connections and create an independent SQLite project copy.':
    'Выбери схему, посмотри структуру узлов и создай независимую копию проекта из SQLite.';
  note.textContent=english()?
    'Edges pass context, not automatic execution. Reference nodes contain text; choose an actual image separately in img2img.':
    'Связи — контекст, не автоматическое выполнение. Узел «Референс» описывает образец; реальное фото для img2img выбирается отдельно.';
  const current=chooser.value;
  chooser.replaceChildren(...templates.map(t=>option(t.id,name(t))));
  if(templates.some(t=>t.id===current))chooser.value=current;
  if(definition)draw(definition);
 }
 function svgEl(tag,attributes){
  const el=document.createElementNS(ns,tag);
  for(const [key,val] of Object.entries(attributes))
   el.setAttribute(key,String(val));
  return el;
 }
 function draw(t){
  panel.replaceChildren();legend.replaceChildren();
  if(!t)return;
  message((english()?t.summary_en:t.summary_ru)+' · '+t.nodes.length+
   (english()?' nodes · ':' узлов · ')+t.edges.length+
   (english()?' links':' связей'));
  const scale=.58,boxW=116,boxH=44,margin=24;
  const width=Math.ceil(Math.max(...t.nodes.map(n=>n.x))*scale+boxW+margin);
  const height=Math.ceil(Math.max(...t.nodes.map(n=>n.y))*scale+boxH+margin);
  const board=document.createElement('div');
  board.className='graph-template-drawing';
  board.style.width=width+'px';board.style.height=height+'px';
  const svg=svgEl('svg',{width,height,viewBox:'0 0 '+width+' '+height,
   'aria-hidden':'true'});
  const markerId='graph-template-arrow';
  const defs=svgEl('defs',{}),marker=svgEl('marker',{
   id:markerId,viewBox:'0 0 10 10',refX:8,refY:5,
   markerWidth:5,markerHeight:5,orient:'auto-start-reverse'
  });
  marker.append(svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#ee9138'}));
  defs.append(marker);svg.append(defs);
  const byKey=new Map(t.nodes.map(n=>[n.key,n]));
  for(const [aKey,bKey] of t.edges){
   const a=byKey.get(aKey),b=byKey.get(bKey);
   if(!a||!b)continue;
   const x1=a.x*scale+boxW,y1=a.y*scale+boxH/2;
   const x2=b.x*scale,y2=b.y*scale+boxH/2;
   const bend=Math.max(20,Math.abs(x2-x1)/2);
   const line=svgEl('path',{
    d:'M '+x1+' '+y1+' C '+(x1+bend)+' '+y1+' '+(x2-bend)+' '+y2+' '+x2+' '+y2,
    stroke:'#ef943d','stroke-width':1.8,fill:'none','marker-end':'url(#'+markerId+')'
   });
   svg.append(line);
  }
  board.append(svg);
  for(const n of t.nodes){
   const card=document.createElement('div');
   card.className='graph-template-chip';
   card.style.left=(n.x*scale)+'px';card.style.top=(n.y*scale)+'px';
   card.title=n.kind+' · '+n.notes;
   const kind=document.createElement('small');kind.textContent=n.kind;
   const title=document.createElement('span');title.textContent=n.title;
   card.append(kind,title);board.append(card);
   const row=document.createElement('div');row.className='graph-template-legend-item';
   const head=document.createElement('strong');head.textContent=n.title;
   const explanation=document.createElement('span');
   explanation.textContent=n.kind+' · '+n.notes;
   row.append(head,explanation);legend.append(row);
  }
  panel.append(board);
 }
 async function preview(){
  const id=chooser.value;
  if(!id)return;
  const token=++requested;
  try{
   const response=await api('/api/studio/templates/'+encodeURIComponent(id));
   if(token!==requested||id!==chooser.value)return;
   definition=response.template;
   draw(definition);
   try{localStorage.setItem('draftsman_graph_template',id)}catch(_){}
  }catch(error){
   if(token!==requested)return;
   definition=null;panel.replaceChildren();legend.replaceChildren();
   message((english()?'Failed to load graph: ':'Ошибка загрузки схемы: ')+error.message);
  }
 }
 async function load(){
  try{
   const response=await api('/api/studio/templates');
   templates=response.templates||[];
   if(!templates.length)throw Error('Empty template library');
   const stored=(()=>{try{return localStorage.getItem('draftsman_graph_template')}catch(_){return null}})();
   updateLanguage();
   if(templates.some(t=>t.id===stored))chooser.value=stored;
   await preview();
  }catch(error){
   create.disabled=true;
   message((english()?'Template library unavailable: ':'Библиотека графов недоступна: ')+error.message);
  }
 }
 async function createProject(){
  if(creating||!definition||definition.id!==chooser.value)return;
  const t=definition;
  const proposal=name(t);
  const projectName=prompt(english()?'New project name':'Название нового проекта',proposal);
  if(!projectName||!projectName.trim())return;
  creating=true;create.disabled=true;
  try{
   const response=await api('/api/studio/projects','POST',
    {name:projectName.trim(),template:t.id});
   await loadProjects(response.project_id);
   E('graphTemplatesPanel').open=false;
   say((english()?'Created graph: ':'Создан граф: ')+t.nodes.length+
    (english()?' nodes and ':' узлов и ')+t.edges.length+
    (english()?' links. Edit and approve a scene to generate.':
      ' связей. Измени сцену и утверди её промпт перед генерацией.'));
  }catch(error){
   message((english()?'Cannot create project: ':'Не удалось создать проект: ')+error.message);
  }finally{creating=false;create.disabled=false}
 }
 chooser.addEventListener('change',preview);
 create.addEventListener('click',createProject);
 E('lang')?.addEventListener('change',updateLanguage);
 load();
 window.DraftsmanGraphTemplates={refresh:load};
})();