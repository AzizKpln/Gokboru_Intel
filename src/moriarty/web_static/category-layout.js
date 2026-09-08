const graphGroups={
  people:{tr:'Kişi ve profiller',en:'People & profiles',icon:'◉',categories:['caller_identity','social_presence']},
  metadata:{tr:'Numara, hat ve konum',en:'Number, line & location',icon:'⌖',categories:['identity','line_intelligence','carrier']},
  documents:{tr:'PDF ve belgeler',en:'PDF & documents',icon:'▤',categories:['documents']},
  reputation:{tr:'Yorumlar ve şikâyetler',en:'Comments & complaints',icon:'!',categories:['reputation','complaints']},
  exposure:{tr:'Sızıntı ve yaptırımlar',en:'Exposure & sanctions',icon:'⚠',categories:['breach_exposure','watchlists']},
  web:{tr:'Açık web ve işletmeler',en:'Open web & businesses',icon:'⌕',categories:['public_web','business']},
  analysis:{tr:'Analitik değerlendirme',en:'Analytic assessment',icon:'✦',categories:['analysis']},
  other:{tr:'Diğer bulgular',en:'Other findings',icon:'◇',categories:[]}
};
const groupOrder=['people','metadata','documents','reputation','exposure','web','analysis','other'];
const groupFor=category=>groupOrder.find(key=>graphGroups[key].categories.includes(category))||'other';
const baseNodeMarkup=nodeMarkup;
nodeMarkup=function(node){const html=baseNodeMarkup(node);return node.kind==='group'?html.replace(language==='tr'?'VARLIK':'ENTITY',language==='tr'?'KATEGORİ':'CATEGORY'):html};

function buildUsernameGraph(investigation){
  currentCase=investigation;
  const sources=investigation.sources||[],profiles=[],historical=[],diagnostics=[];
  for(const source of sources){
    const data=source.data||{};
    if(Array.isArray(data.profiles))profiles.push(...data.profiles);
    if(Array.isArray(data.mentions))historical.push(...data.mentions);
    if(source.state==='failed'||source.finding==='indeterminate')diagnostics.push({source:source.source,status:source.provider_status,error:source.error||data.note});
  }
  const unique=[...new Map(profiles.map(profile=>[profile.canonical_url||profile.url||profile.web_url,profile])).values()].filter(profile=>profile&&profile.url||profile?.web_url);
  const sections=[
    {key:'confirmed',tr:'Doğrulanmış profiller',en:'Confirmed profiles',items:unique.filter(item=>item.status==='confirmed'),tone:'finding'},
    {key:'probable',tr:'Olası profiller',en:'Probable profiles',items:unique.filter(item=>item.status==='probable'),tone:'neutral'},
    {key:'unverified',tr:'Doğrulanmamış sinyaller',en:'Unverified signals',items:unique.filter(item=>!['confirmed','probable'].includes(item.status)),tone:'neutral'},
    {key:'historical',tr:'Geçmiş kayıtlar',en:'Historical records',items:historical,tone:'neutral'},
    {key:'diagnostics',tr:'Kaynak durumları',en:'Source diagnostics',items:diagnostics,tone:'neutral'},
  ].filter(section=>section.items.length);
  const nodes=[{id:'target',kind:'target',title:investigation.subject||investigation.title,subtitle:language==='tr'?'Kullanıcı Adı':'Username',x:1100,y:800,data:{target:investigation.subject||investigation.title,target_type:'username',summary:investigation.summary,profile_count:unique.length,historical_count:historical.length}}],edges=[];
  const radius=390;
  sections.forEach((section,index)=>{
    const angle=-Math.PI/2+(Math.PI*2*index/sections.length),x=1100+Math.cos(angle)*radius,y=800+Math.sin(angle)*radius,id=`username-${section.key}`,visible=section.items.slice(0,12);
    nodes.push({id,kind:'group',tone:section.tone,title:language==='tr'?section.tr:section.en,subtitle:`${section.items.length} ${language==='tr'?'bulgu':'findings'}`,x,y,data:{category:section.key,total:section.items.length,shown:visible.length,items:section.items.slice(0,50)}});edges.push({from:'target',to:id,tone:section.tone});
    visible.forEach((item,itemIndex)=>{const fan=(itemIndex-(visible.length-1)/2)*.17,childAngle=angle+fan,childRadius=170+Math.floor(itemIndex/7)*85,childId=`${id}-${itemIndex}`,url=item.url||item.web_url||item.original_url||'',title=item.name||item.source||url||`${section.key} ${itemIndex+1}`,photo=item.avatar_url||'';nodes.push({id:childId,kind:'entity',tone:section.tone,title,subtitle:item.status||item.archive||section.key,x:x+Math.cos(childAngle)*childRadius,y:y+Math.sin(childAngle)*childRadius,photo,data:item});edges.push({from:id,to:childId,tone:section.tone})});
    if(section.items.length>visible.length){const hidden=section.items.length-visible.length,childId=`${id}-more`;nodes.push({id:childId,kind:'entity',tone:'neutral',title:`+${hidden} ${language==='tr'?'ek kayıt':'more records'}`,subtitle:language==='tr'?'Kategori panelinde':'In category inspector',x:x+Math.cos(angle+.8)*190,y:y+Math.sin(angle+.8)*190,data:{hidden,total:section.items.length,note:language==='tr'?'Grafik performansı için yalnızca ilk 12 kayıt çizildi.':'Only the first 12 records are drawn for graph performance.'}});edges.push({from:id,to:childId,tone:'neutral'})}
  });
  graph={nodes,edges};$('#caseName').textContent=investigation.subject||investigation.title;renderGraph();fitGraph();
}

buildGraph=function(investigation){
  currentCase=investigation;
  if(investigation?.audits?.at(-1)?.audit_type==='username'){buildUsernameGraph(investigation);return}
  const sources=investigation.sources||[],activeGroups=groupOrder.filter(key=>sources.some(source=>groupFor(source.category)===key));
  const nodes=[{id:'target',kind:'target',title:investigation.subject||investigation.title,subtitle:language==='tr'?'Telefon Numarası':'Phone Number',x:1100,y:800,data:{number:investigation.subject||investigation.title,status:investigation.status,summary:investigation.summary,started_at:investigation.created_at}}],edges=[];
  const groupRadius=Math.min(490,330+activeGroups.length*22);
  activeGroups.forEach((groupKey,groupIndex)=>{
    const definition=graphGroups[groupKey],groupAngle=-Math.PI/2+(Math.PI*2*groupIndex/activeGroups.length),groupX=1100+Math.cos(groupAngle)*groupRadius,groupY=800+Math.sin(groupAngle)*groupRadius,groupId=`group-${groupKey}`;
    const members=sources.filter(source=>groupFor(source.category)===groupKey);
    nodes.push({id:groupId,kind:'group',tone:'neutral',title:definition[language]||definition.tr,subtitle:`${members.length} ${language==='tr'?'kaynak':'sources'}`,x:groupX,y:groupY,data:{category:groupKey,source_count:members.length,sources:members.map(item=>item.source)}});
    edges.push({from:'target',to:groupId,tone:'neutral'});
    members.forEach((source,memberIndex)=>{
      const memberSpread=Math.min(1.35,.42*members.length),memberAngle=groupAngle-Math.PI/2-memberSpread/2+(members.length===1?memberSpread/2:memberSpread*memberIndex/(members.length-1)),sourceRadius=190+(memberIndex%2)*35,x=groupX+Math.cos(memberAngle)*sourceRadius,y=groupY+Math.sin(memberAngle)*sourceRadius,id=`source-${groupKey}-${memberIndex}`,data=source.data||{},allEntities=simpleEntities(source,data),entities=allEntities.slice(0,10);
      nodes.push({id,kind:'source',tone:source.finding,title:catalog.find(c=>c.id===source.source)?.label||source.source,subtitle:categoryLabels[source.category]||source.category,x,y,photo:findPhoto(data),data:{...data,provider_status:source.provider_status,state:source.state,error:source.error,duration_ms:source.duration_ms,graph_entities_shown:entities.length,total_entities_detected:allEntities.length,category_group:definition[language]||definition.tr}});
      edges.push({from:groupId,to:id,tone:source.finding});
      const outward=Math.atan2(y-groupY,x-groupX);
      entities.forEach((entity,entityIndex)=>{
        const row=Math.floor(entityIndex/5),slot=entityIndex%5,fan=(slot-2)*.24,childRadius=145+row*95,childAngle=outward+fan,childId=`${id}-entity-${entityIndex}`;
        nodes.push({id:childId,kind:'entity',tone:source.finding,title:entity.value,subtitle:entity.label,x:x+Math.cos(childAngle)*childRadius,y:y+Math.sin(childAngle)*childRadius,photo:entity.photo,data:{type:entity.type,value:entity.value,source:source.source,category_group:definition[language]||definition.tr,raw:entity.raw}});
        edges.push({from:id,to:childId,tone:source.finding});
      });
      if(allEntities.length>entities.length){const hidden=allEntities.length-entities.length,childId=`${id}-more`,childAngle=outward+.72;nodes.push({id:childId,kind:'entity',tone:'neutral',title:`+${hidden} ${language==='tr'?'ek bulgu':'more findings'}`,subtitle:language==='tr'?'İnceleme panelinde':'In inspector',x:x+Math.cos(childAngle)*175,y:y+Math.sin(childAngle)*175,data:{hidden_findings:hidden,note:language==='tr'?'Tüm veriler kaynak düğümünün inceleme panelinde korunur.':'All data remains available in the source inspector.'}});edges.push({from:id,to:childId,tone:'neutral'})}
    });
  });
  graph={nodes,edges};$('#caseName').textContent=investigation.subject||investigation.title;renderGraph();fitGraph();
};
