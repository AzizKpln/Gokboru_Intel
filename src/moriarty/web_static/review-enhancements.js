const englishSourceLabels={local:'Number & Carrier',truecaller:'Truecaller',syncme:'Sync.me',telegram:'Telegram',facebook:'Facebook',whatsapp:'WhatsApp',cybernews:'Cybernews',databreach:'DataBreach',hudsonrock:'Hudson Rock',github:'GitHub',reddit:'Reddit',brave:'Brave Search',duckduckgo:'DuckDuckGo','web-mentions':'Open Web',pastebin:'Pastebin',documents:'PDF & Documents',reputation:'Phone Comments',business:'Business Records',disposable:'Temporary SMS Services',opensanctions:'OpenSanctions',ftc:'FTC Complaints',btk:'BTK Carrier Lookup','ai-analysis':'AI Analysis'};
const localizedCategories={identity:{tr:'Temel Bilgi',en:'Core Identity'},caller_identity:{tr:'Arayan Kimliği',en:'Caller Identity'},social_presence:{tr:'Sosyal Hesap',en:'Social Presence'},breach_exposure:{tr:'Veri Sızıntısı',en:'Data Exposure'},public_web:{tr:'Açık Web',en:'Open Web'},documents:{tr:'Belge',en:'Documents'},reputation:{tr:'İtibar',en:'Reputation'},business:{tr:'İşletme',en:'Business'},line_intelligence:{tr:'Hat Bilgisi',en:'Line Intelligence'},watchlists:{tr:'Yaptırım',en:'Sanctions'},complaints:{tr:'Şikâyet',en:'Complaints'},carrier:{tr:'Operatör',en:'Carrier'},analysis:{tr:'Analiz',en:'Analysis'}};
function localizeCatalog(){catalog.forEach(item=>{item._trLabel??=item.label;item.label=language==='en'?(englishSourceLabels[item.id]||item.label):item._trLabel});Object.entries(localizedCategories).forEach(([key,value])=>categoryLabels[key]=value[language]||value.tr)}
const baseRenderSourcesLocalized=renderSources;
renderSources=function(filter=''){localizeCatalog();return baseRenderSourcesLocalized(filter)};
localizeCatalog();

function collectReadableFindings(value,path='',output=[],seen=new Set()){
  if(!value||output.length>=80)return output;
  if(Array.isArray(value)){value.forEach((item,index)=>{if(typeof item==='string'&&/comments?|reviews?|snippets?|mentions?|context|matched_text|body|content|signals?/i.test(path)){const signature=`${path}|${item}`;if(!seen.has(signature)){seen.add(signature);output.push({title:/comments?/i.test(path)?(language==='tr'?'Kullanıcı Yorumu':'User Comment'):humanKey(path.split('.').filter(Boolean).pop()||'finding'),text:item,url:'',date:'',path:`${path}.${index}`})}}else collectReadableFindings(item,`${path}.${index}`,output,seen)});return output}
  if(typeof value!=='object')return output;
  const pick=(...keys)=>keys.map(key=>value[key]).find(item=>typeof item==='string'&&item.trim());
  const title=pick('title','name','display_name','database','provider','source'),text=pick('comment','review','snippet','description','context','matched_text','text','note','body','content','summary','reason'),url=pick('url','link','page_url','profile_url'),date=pick('date','published_at','observed_at','created_at');
  if(text||url){const signature=[title,text,url].join('|');if(!seen.has(signature)){seen.add(signature);output.push({title:title||humanKey(path.split('.').pop()||'finding'),text:text||'',url:url||'',date:date||'',path})}}
  Object.entries(value).forEach(([key,item])=>{
    if(typeof item==='string'&&/comment|review|snippet|description|context|matched_text|body|content|reason/i.test(key)){const signature=`${key}|${item}`;if(!seen.has(signature)){seen.add(signature);output.push({title:humanKey(key),text:item,url:'',date:'',path:`${path}.${key}`})}}
    else if(item&&typeof item==='object')collectReadableFindings(item,`${path}.${key}`,output,seen);
  });
  return output;
}

function readableFindingsMarkup(data,source){
  const findings=collectReadableFindings(data),isReputation=['reputation','complaints'].includes(source.category),heading=isReputation?(language==='tr'?'Yorumlar ve Topluluk Bulguları':'Comments & Community Findings'):(language==='tr'?'Okunabilir Web Bulguları':'Readable Web Findings');
  if(!findings.length)return `<section class="readable-findings empty"><h4>${heading}</h4><p>${isReputation?(language==='tr'?'Bu kaynak risk sinyali döndürdü ancak herkese açık yorum metni sağlamadı.':'This source returned a risk signal but did not provide public comment text.'):(language==='tr'?'Bu kaynakta başlık, açıklama veya bağlam metni bulunamadı.':'No title, description, or context text was returned by this source.')}</p></section>`;
  return `<section class="readable-findings"><h4>${heading}<span>${findings.length}</span></h4><div>${findings.map(item=>`<article><div><small>${esc(item.date||item.path.replace(/^\./,''))}</small><h5>${esc(item.title)}</h5></div>${item.text?`<p>${esc(item.text)}</p>`:''}${item.url?`<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${language==='tr'?'Kaynağı aç':'Open source'} ↗</a>`:''}</article>`).join('')}</div></section>`;
}

sourceCard=function(source){
  const data=source.data||{},photo=findPhoto(data),showReadable=['reputation','complaints','public_web','business','documents'].includes(source.category);
  localizeCatalog();const sourceLabel=language==='en'?(englishSourceLabels[source.source]||source.source):(catalog.find(item=>item.id===source.source)?._trLabel||catalog.find(item=>item.id===source.source)?.label||source.source),categoryLabel=localizedCategories[source.category]?.[language]||categoryLabels[source.category]||source.category;return `<article class="review-source-card"><header>${photo?`<img src="${esc(photo)}" alt="">`:`<span>${iconFor(source.source)}</span>`}<div><small>${esc(categoryLabel)}</small><h3>${esc(sourceLabel)}</h3></div><b class="state-${esc(source.finding||'neutral')}">${esc(source.provider_status||source.state||'unknown')}</b></header>${showReadable?readableFindingsMarkup(data,source):''}<details class="raw-source-details"><summary>${language==='tr'?'Tüm ham özellikler':'All raw properties'}<b>${countFields(data)}</b></summary><div class="review-source-data">${Object.entries(data).map(([key,value])=>renderInspectorValue(key,value)).join('')||`<div class="no-data">${language==='tr'?'Veri yok':'No data'}</div>`}</div></details></article>`
};

function directReputationComments(data){
  const output=[],seen=new Set(),add=(provider,text,url='')=>{if(typeof text!=='string'||!text.trim())return;const signature=`${provider}|${text.trim()}`;if(seen.has(signature))return;seen.add(signature);output.push({provider,text:text.trim(),url})};
  (data.providers||[]).forEach(provider=>{const name=provider.provider||provider.data?.source||'reputation',url=provider.data?.url||'',comments=provider.data?.comments||[];(Array.isArray(comments)?comments:[comments]).forEach(comment=>add(name,comment,url));(provider.evidence||[]).forEach(evidence=>{const nested=evidence.attributes?.comments||[];(Array.isArray(nested)?nested:[nested]).forEach(comment=>add(name,comment,evidence.source?.url||url))})});
  return output;
}
function renderReputationReview(investigation){
  const sources=sourcesForGroup(investigation,'reputation'),comments=sources.flatMap(source=>directReputationComments(source.data||{})),providers=sources.flatMap(source=>(source.data?.providers||[]));
  $('#detailWorkspaceContent').innerHTML=`<div class="review-section-head"><small>${language==='tr'?'TOPLULUK GERİ BİLDİRİMİ':'COMMUNITY FEEDBACK'}</small><h1>${language==='tr'?'Yorumlar ve Şikâyetler':'Comments & Complaints'}</h1><p>${comments.length} ${language==='tr'?'gerçek yorum metni,':'actual comment texts,'} ${providers.length} ${language==='tr'?'sağlayıcı sonucu':'provider results'}</p></div><section class="direct-comments ${comments.length?'':'empty'}"><h2>${language==='tr'?'Kullanıcı Yorumları':'User Comments'}<span>${comments.length}</span></h2>${comments.length?`<div>${comments.map(comment=>`<article><small>${esc(comment.provider)}</small><p>${esc(comment.text)}</p>${comment.url?`<a href="${esc(comment.url)}" target="_blank" rel="noreferrer">${language==='tr'?'Kaynağı aç':'Open source'} ↗</a>`:''}</article>`).join('')}</div>`:`<p>${language==='tr'?'Kontrol edilen sağlayıcılar bu numara için risk/rapor sinyali döndürdü fakat herhangi bir yorum metni döndürmedi.':'The checked providers returned risk/report signals for this number, but returned no comment text.'}</p>`}</section><section class="provider-status-board"><h2>${language==='tr'?'Sağlayıcı Durumları':'Provider Statuses'}</h2><div>${providers.map(provider=>`<article><b>${esc(provider.provider||provider.data?.source||'provider')}</b><span>${esc(provider.status||'unknown')}</span><em>${provider.data?.comments?.length||0} ${language==='tr'?'yorum':'comments'}</em></article>`).join('')}</div></section><details class="reputation-raw"><summary>${language==='tr'?'İtibar özetini ve ham veriyi aç':'Open reputation summary and raw data'}</summary>${sources.map(sourceCard).join('')}</details>`;
  $$('#detailWorkspaceNav button').forEach(button=>button.classList.toggle('active',button.dataset.reviewKey==='reputation'));requestAnimationFrame(()=>{$('#detailWorkspaceContent').scrollTop=0});
}

let analysisLanguageLoading=false;
const baseShowReviewSection=showReviewSection;
showReviewSection=async function(investigation,key){
  if(key==='reputation'){renderReputationReview(investigation);return}
  if(key==='analysis'&&(!investigation.analysis||investigation.analysis.language!==language)&&!analysisLanguageLoading){
    analysisLanguageLoading=true;$('#detailWorkspaceContent').innerHTML=`<div class="review-analysis-loading"><b>${language==='tr'?'AI analizi hazırlanıyor…':'Generating English AI analysis…'}</b><span>${language==='tr'?'Mevcut analiz farklı dildeyse yeniden oluşturulur.':'An analysis in another language will be regenerated.'}</span></div>`;
    try{const updated=await api(`/api/investigations/${encodeURIComponent(investigation.id)}/analysis`,{method:'POST',body:JSON.stringify({language})});currentCase=updated;const index=cases.findIndex(item=>item.id===updated.id);if(index>=0)cases[index]=updated;renderCaseReview(updated);baseShowReviewSection(updated,'analysis')}catch(error){$('#detailWorkspaceContent').innerHTML=`<div class="review-analysis-loading error"><b>${esc(error.message)}</b></div>`}finally{analysisLanguageLoading=false}return;
  }
  baseShowReviewSection(investigation,key);requestAnimationFrame(()=>{$('#detailWorkspaceContent').scrollTop=0});
};
$('#langButton').addEventListener('click',()=>setTimeout(()=>{localizeCatalog();renderSources($('#sourceSearch').value);const investigation=reviewInvestigation();if(investigation){currentCase=investigation;buildGraph(withAnalysis(investigation))}if(reviewDialog.open)renderCaseReview(investigation)},0));
reviewDialog.addEventListener('wheel',event=>{const content=$('#detailWorkspaceContent');if(content&&event.target.closest('#detailWorkspaceContent')){content.scrollTop+=event.deltaY;event.preventDefault()}},{passive:false});
