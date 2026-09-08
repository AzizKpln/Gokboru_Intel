const analysisEsc=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const activeInvestigation=()=>currentCase||cases.find(c=>(c.subject||c.title)===$('#caseName').textContent)||cases[0];
const analysisList=(title,items)=>`<section class="analysis-section"><h3>${analysisEsc(title)}</h3>${items?.length?`<ul>${items.map(item=>`<li>${analysisEsc(item)}</li>`).join('')}</ul>`:`<p>${language==='tr'?'Veri yok':'No data'}</p>`}</section>`;

function showAnalysis(analysis){
  const labels=language==='tr'?{facts:'Gözlemlenen gerçekler',assessments:'Analitik değerlendirme',contradictions:'Çelişkiler',limitations:'Sınırlamalar',actions:'Önerilen işlemler',summary:'Yönetici özeti',confidence:'Güven'}:{facts:'Observed facts',assessments:'Analytic assessment',contradictions:'Contradictions',limitations:'Limitations',actions:'Recommended actions',summary:'Executive summary',confidence:'Confidence'};
  $('#analysisContent').innerHTML=`<div class="analysis-hero"><div class="risk-card ${analysis.risk_level||'unknown'}"><small>RISK LEVEL</small><strong>${analysisEsc(analysis.risk_level||'unknown')}</strong><span>${labels.confidence}: ${Math.round(Number(analysis.confidence||0)*100)}%</span></div><div class="analysis-summary"><small>${labels.summary}</small><p>${analysisEsc(analysis.executive_summary||'—')}</p><small>${analysisEsc(analysis.model||'')}</small></div></div><div class="analysis-grid">${analysisList(labels.facts,analysis.observed_facts)}${analysisList(labels.assessments,analysis.assessments)}${analysisList(labels.contradictions,analysis.contradictions)}${analysisList(labels.limitations,analysis.limitations)}${analysisList(labels.actions,analysis.recommended_actions)}</div>`;
  $('#analysisDialog').showModal();
}

async function runAiAnalysis(){
  currentCase=activeInvestigation();
  if(!currentCase)return toast(language==='tr'?'Önce bir soruşturma açın':'Open an investigation first');
  if(currentCase.analysis&&currentCase.analysis.language===language){showAnalysis(currentCase.analysis);return}
  const button=$('#analyzeButton');button.disabled=true;button.textContent=language==='tr'?'ANALİZ EDİLİYOR…':'ANALYZING…';
  try{const updated=await api(`/api/investigations/${encodeURIComponent(currentCase.id)}/analysis`,{method:'POST',body:JSON.stringify({language})});currentCase=updated;const index=cases.findIndex(c=>c.id===updated.id);if(index>=0)cases[index]=updated;else cases.unshift(updated);buildGraph(withAnalysis(updated));showAnalysis(updated.analysis);toast(language==='tr'?'AI analizi tamamlandı':'AI analysis complete')}catch(error){toast(error.message)}finally{button.disabled=false;button.textContent=language==='tr'?'AI ANALİZ':'AI ANALYSIS'}
}

function exportCurrentJson(){
  const investigation=activeInvestigation();if(!investigation)return toast(language==='tr'?'Kaydedilecek soruşturma yok':'No investigation to save');
  const blob=new Blob([JSON.stringify(investigation,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=`gokboru-${String(investigation.subject||investigation.id).replace(/[^a-zA-Z0-9_-]/g,'_')}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  toast(language==='tr'?'JSON yerel diske kaydedildi':'JSON saved locally');
}

$('#analyzeButton').addEventListener('click',runAiAnalysis);
$('#exportJson').addEventListener('click',exportCurrentJson);
$('#visibleSettings').addEventListener('click',()=>$('#setupDialog').showModal());
$('#visibleLanguage').addEventListener('click',()=>$('#langButton').click());
$('#closeAnalysis').addEventListener('click',()=>$('#analysisDialog').close());
