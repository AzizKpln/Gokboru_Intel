let inspectorMode=localStorage.getItem('gokboru-inspector-mode')||'scroll';
const inspectorModeBar=document.createElement('div');
inspectorModeBar.className='inspector-mode-switch';
inspectorModeBar.innerHTML=`<span>${language==='tr'?'İNCELEME':'INSPECTOR'}</span><button data-mode="scroll">${language==='tr'?'Kaydırmalı':'Scroll'}</button><button data-mode="tabs">${language==='tr'?'Butonlu':'Tabbed'}</button>`;
document.querySelector('.graph-actions').prepend(inspectorModeBar);

function syncInspectorModeButtons(){
  inspectorModeBar.querySelector('span').textContent=language==='tr'?'İNCELEME':'INSPECTOR';
  inspectorModeBar.querySelector('[data-mode="scroll"]').textContent=language==='tr'?'Kaydırmalı':'Scroll';
  inspectorModeBar.querySelector('[data-mode="tabs"]').textContent=language==='tr'?'Butonlu':'Tabbed';
  inspectorModeBar.querySelectorAll('button').forEach(button=>button.classList.toggle('active',button.dataset.mode===inspectorMode));
}

function inspectorSections(data){
  const entries=Object.entries(data||{}),primitive=entries.filter(([,value])=>value===null||typeof value!=='object'),complex=entries.filter(([,value])=>value!==null&&typeof value==='object');
  const sections=[];
  if(primitive.length)sections.push({id:'summary',label:language==='tr'?'Özet':'Summary',entries:primitive});
  complex.forEach(([key,value],index)=>sections.push({id:`section-${index}`,label:humanKey(key),entries:[[key,value]]}));
  if(!sections.length)sections.push({id:'empty',label:language==='tr'?'Veri':'Data',entries:[]});
  return sections;
}

function renderTabbedInspector(node){
  const detail=document.querySelector('#inspectorContent');if(!detail||!node)return;
  const sections=inspectorSections(node.data),toolbar=detail.querySelector('.detail-toolbar'),properties=detail.querySelector('.property-list');
  if(!toolbar||!properties)return;
  const tabs=document.createElement('nav');tabs.className='property-tabs';
  tabs.innerHTML=sections.map((section,index)=>`<button data-section="${section.id}" class="${index===0?'active':''}">${esc(section.label)}</button>`).join('');
  toolbar.insertAdjacentElement('afterend',tabs);
  const show=section=>{tabs.querySelectorAll('button').forEach(button=>button.classList.toggle('active',button.dataset.section===section.id));properties.innerHTML=section.entries.map(([key,value])=>renderInspectorValue(key,value)).join('')||`<div class="no-data">${language==='tr'?'Bu bölümde veri yok':'No data in this section'}</div>`;properties.scrollTop=0;detail.scrollTop=0};
  tabs.querySelectorAll('button').forEach(button=>button.onclick=()=>show(sections.find(section=>section.id===button.dataset.section)));
  show(sections[0]);detail.classList.add('tabbed-inspector');
}

const scrollSelectNode=selectNode;
selectNode=function(id){scrollSelectNode(id);const node=graph.nodes.find(item=>item.id===id);if(inspectorMode==='tabs')renderTabbedInspector(node)};

inspectorModeBar.querySelectorAll('button').forEach(button=>button.onclick=()=>{
  inspectorMode=button.dataset.mode;localStorage.setItem('gokboru-inspector-mode',inspectorMode);syncInspectorModeButtons();
  const selectedNode=document.querySelector('.graph-node.selected');if(selectedNode)selectNode(selectedNode.dataset.id);
  toast(inspectorMode==='tabs'?(language==='tr'?'Butonlu inceleme etkin':'Tabbed inspector enabled'):(language==='tr'?'Kaydırmalı inceleme etkin':'Scroll inspector enabled'));
});
syncInspectorModeButtons();
document.querySelector('#langButton').addEventListener('click',()=>setTimeout(syncInspectorModeButtons,0));
