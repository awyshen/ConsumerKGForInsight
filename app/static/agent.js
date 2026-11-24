'use strict';
const research = {session:null,tenant:null,sessions:[],runs:[],capabilities:null,pollTimer:null,artifactId:null,drafts:{},sending:false};
const toolLabels={cohort_profile:'样本与需求画像',compare_cohorts:'群体需求对比',segment_needs:'消费者分群',product_paths:'知识图谱产品路径',evidence_search:'原文证据核验',behavior_summary:'行为事件分析'};
const kindLabels={observation:'数据观察',hypothesis:'待验证假设',recommendation:'行动建议'};
const fieldLabels={need:'需求',consumer_count:'消费者数',share_pct:'提及占比 %',wilson_95:'Wilson 95% 区间',a_count:'A 组人数',a_n:'A 样本量',a_share_pct:'A 占比 %',b_count:'B 组人数',b_n:'B 样本量',b_share_pct:'B 占比 %',delta_pp:'差异 / 百分点',a_wilson_95:'A 区间',b_wilson_95:'B 区间',group:'分群',sample_size:'组内样本量',name:'名称',count:'数量',event_type:'事件类型',events:'事件次数',consumers:'涉及人数',cohort_size:'样本量',product:'产品',feature:'功能 / 卖点',supporting_consumers:'支持人数',relation:'关联类型'};
const researchExamples=['分析菲律宾26-30岁消费者的需求，按使用场景细分，并结合产品路径提出待验证的机会。','对比菲律宾和印度尼西亚26-30岁消费者的需求差异，核对样本与原文证据。','分析菲律宾消费者的需求与购买事件关联，说明哪些结论不能从数据推出。'];
function researchDate(value){return new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});}
function researchKey(){return `${state.tenant}:${research.session||'new'}`;}
function currentResearch(){return research.tenant===state.tenant && state.view==='agent';}
function lastArtifact(){return [...research.runs].reverse().find(r=>r.artifact)?.artifact;}
function stopAgentPoll(){if(research.pollTimer)clearTimeout(research.pollTimer);research.pollTimer=null;}
window.addEventListener('hashchange',stopAgentPoll);
async function agentView(){
  stopAgentPoll();
  const tenant=state.tenant;
  const [capabilities,sessions]=await Promise.all([api('/v1/agent/capabilities'),api('/v1/agent/sessions')]);
  if(tenant!==state.tenant)return '';
  research.capabilities=capabilities;research.sessions=sessions;
  if(research.tenant!==tenant){research.session=sessionStorage.getItem('kg-research-'+tenant)||null;research.tenant=tenant;research.runs=[];research.sending=false;}
  if(research.session&&!sessions.some(s=>s.id===research.session))research.session=null;
  if(!research.session&&sessions.length)research.session=sessions[0].id;
  if(research.session){const data=await api('/v1/agent/sessions/'+encodeURIComponent(research.session));research.runs=data.runs;}else research.runs=[];
  if(research.runs.some(r=>['queued','running'].includes(r.status)))scheduleAgentPoll();
  return `<div class="agent-toolbar"><label class="session-selector">研究会话<select id="research-session"><option value="">新的研究对话</option>${sessions.map(s=>`<option value="${esc(s.id)}" ${s.id===research.session?'selected':''}>${esc(s.title)}</option>`).join('')}</select></label><button class="button secondary" id="new-research">＋ 新建研究</button><div class="model-label"><span class="pill ${capabilities.enabled?'teal':'amber'}">${capabilities.enabled?'LLM 已启用':'LLM 未启用'}</span>${capabilities.enabled&&capabilities.thinking==='disabled'?'<span class="pill blue" title="非思考模式；仍执行统计工具和证据引用校验">快速生成</span>':''}<span>${esc(capabilities.model)}</span></div></div>${!capabilities.enabled?'<div class="error-banner">需要在服务端启用 LLM 并配置模型，才能执行 Agent 分析。快速统计仍然可用。</div>':''}<div class="agent-layout"><article class="panel agent-conversation"><div class="panel-header"><div><h2>研究对话</h2><p>沿着一个问题，逐步深入到群体、证据与产品路径。</p></div><span class="pill blue">${research.runs.length} 轮</span></div><div class="agent-thread" id="agent-thread" role="log" aria-label="研究对话记录">${researchMessages()}</div><form class="agent-composer" id="agent-message-form"><label for="agent-question">研究问题或追问</label><textarea id="agent-question" name="question" required minlength="2" maxlength="2000" placeholder="例如：这些需求在不同使用场景中有什么差异？">${esc(research.drafts[researchKey()]||'')}</textarea><div class="agent-compose-bottom"><span>最多 ${capabilities.max_tool_calls} 次只读工具调用 · 每轮保存报告<br>未完成任务可在刷新后继续查看</span><button type="submit" class="button primary" ${!capabilities.enabled||research.runs.some(r=>['queued','running'].includes(r.status))?'disabled':''}>开始分析</button></div></form></article><aside class="agent-side" id="agent-side">${researchSidebar()}</aside></div>`;
}
function researchMessages(){
  if(!research.runs.length)return `<div class="agent-welcome"><span class="qa-symbol">✦</span><h2>从一个值得追问的问题开始</h2><p>Agent 会制定简要计划，调用统计与图谱工具，再将数据观察、研究假设和行动建议分开呈现。</p><div class="research-examples">${researchExamples.map(q=>`<button class="research-example" data-research-question="${esc(q)}">${esc(q)}</button>`).join('')}</div><p class="form-note">分析受当前数据与本体约束。无法支持的预测或因果问题会要求澄清。</p></div>`;
  return research.runs.map(r=>`<div class="research-turn"><div class="research-user"><span class="turn-avatar">你</span><div><small>${researchDate(r.created_at)}</small><p>${esc(r.question)}</p></div></div><div class="research-assistant"><span class="turn-avatar agent-avatar">✦</span><div class="turn-body"><strong>Consumer Atlas</strong>${['queued','running'].includes(r.status)?`<div class="agent-working"><span class="working-spinner"></span>${r.status==='queued'?'等待执行':'正在分析'} · ${esc(r.trace.filter(t=>t.type==='tool'&&t.status==='running').map(t=>toolLabels[t.name]).join('、')||'模型规划与报告整理')}</div><p class="form-note">真实模型通常需要数十秒，多步骤分析可能需要数分钟。</p>`:r.status==='failed'?`<div class="inline-error">${esc(r.error)}</div><button class="text-link" data-research-question="${esc(r.question)}">使用这个问题重试</button>`:`<p class="agent-answer">${esc(r.answer)}</p>${r.artifact?`<div class="artifact-inline"><span class="artifact-inline-icon">▧</span><div><strong>${esc(r.artifact.title)}</strong><small>${r.artifact.content.findings.length} 条洞察 · ${r.artifact.content.facts.length} 条计算事实 · ${r.artifact.content.citations.length} 条引用</small></div><button class="text-link" data-open-report="${esc(r.artifact.id)}">查看报告</button></div><div class="follow-up-list">${r.artifact.content.follow_up_questions.map(q=>`<button class="suggestion" data-research-question="${esc(q)}">${esc(q)}</button>`).join('')}</div>`:'<span class="pill amber">需要补充信息</span>'}`}${r.trace.length?`<details class="trace-details"><summary>分析执行记录 · ${r.trace.filter(t=>t.type==='tool').length} 次工具调用</summary>${traceView(r.trace)}</details>`:''}</div></div></div>`).join('');
}
function traceView(trace){return `<div class="trace-list">${trace.map(t=>t.type==='plan'?`<div class="trace-step"><span class="trace-index">◎</span><div><strong>研究目标</strong><p>${esc(t.objective)}</p></div></div>`:t.type==='validation'?`<div class="trace-step"><span class="trace-index">✓</span><div><strong>引用核验完成</strong><p>${esc(t.note)}</p></div></div>`:`<div class="trace-step"><span class="trace-index">${t.status==='completed'?'✓':'◌'}</span><div><strong>${esc(toolLabels[t.name]||t.name)}</strong><p>${esc(t.purpose)}</p><small>${esc(JSON.stringify(t.arguments))}</small>${t.result?`<p>${num(t.result.sample_size)} 人样本 · ${t.seconds} 秒${t.result.graph?' · '+graphStatus(t.result.graph):''}</p>`:''}</div></div>`).join('')}</div>`;}
function graphStatus(g){return g.status==='live'?`Neo4j 实查 · ${g.verified_paths} 条路径一致`:g.status==='unavailable'?'Neo4j 不可达，使用 SQL 图谱':'SQL 知识图谱';}
function researchSidebar(){
  const artifact=lastArtifact(),latest=research.runs[research.runs.length-1];
  return `<section class="panel"><div class="panel-header"><h2>本轮研究进展</h2></div><div class="panel-body">${latest?.trace.length?traceView(latest.trace):`<div class="agent-workflow"><div><b>理解问题</b><span>确认研究范围与分析目标</span></div><div><b>调用工具</b><span>统计、分群、行为与图谱路径</span></div><div><b>核对证据</b><span>引用只能来自已读取的数据</span></div><div><b>形成报告</b><span>保存事实、假设与验证计划</span></div></div>`}</div></section>${artifact?`<section class="panel section-space"><div class="panel-header"><h2>最近的分析产物</h2></div><div class="panel-body"><h3>${esc(artifact.title)}</h3><p class="form-note section-space">${esc(artifact.content.summary.slice(0,180))}</p><div class="fact-mini-list">${artifact.content.facts.slice(0,4).map(f=>`<div><small>${esc(f.label)}</small><b>${esc(f.value)}<span>${esc(f.unit)}</span></b></div>`).join('')}</div><button class="button primary" data-open-report="${esc(artifact.id)}">打开完整报告</button></div></section>`:''}<p class="agent-safety-note">只读分析工具不会修改消费者事实。模型解释需人工复核；合成数据不能验证真实市场机会。</p>`;
}
function updateResearchUI(){
  if(!currentResearch())return;
  const thread=$('#agent-thread');if(!thread)return;
  const atBottom=thread.scrollHeight-thread.scrollTop-thread.clientHeight<100;
  thread.innerHTML=researchMessages();$('#agent-side').innerHTML=researchSidebar();
  const busy=research.runs.some(r=>['queued','running'].includes(r.status));
  $('#agent-message-form button[type="submit"]').disabled=busy||research.sending||!research.capabilities?.enabled;
  if(atBottom||busy)thread.scrollTop=thread.scrollHeight;
}
function scheduleAgentPoll(){stopAgentPoll();research.pollTimer=setTimeout(pollResearch,1800);}
async function pollResearch(){
  if(!currentResearch()||!research.session)return;
  const tenant=state.tenant,session=research.session;
  try{
    const data=await api('/v1/agent/sessions/'+encodeURIComponent(session));
    if(tenant!==state.tenant||session!==research.session||!currentResearch())return;
    const previous=JSON.stringify(research.runs.map(r=>[r.status,r.trace.length,r.trace.at(-1)?.status]));
    research.runs=data.runs;
    if(previous!==JSON.stringify(data.runs.map(r=>[r.status,r.trace.length,r.trace.at(-1)?.status])))updateResearchUI();
    if(data.runs.some(r=>['queued','running'].includes(r.status)))scheduleAgentPoll();
  }catch(e){if(currentResearch()){error('读取分析进度失败：'+e.message+' 可点击刷新数据重新连接。');scheduleAgentPoll();}}
}
async function submitResearch(question){
  if(research.sending||research.runs.some(r=>['queued','running'].includes(r.status)))return;
  const tenant=state.tenant,version=state.version;
  let sessionId=research.session;
  research.sending=true;$('#global-error').hidden=true;
  const button=$('#agent-message-form button[type="submit"]');if(button)button.disabled=true;
  try{
    if(!sessionId){const s=await api('/v1/agent/sessions',{method:'POST',body:JSON.stringify({title:'新的研究对话'})});if(tenant!==state.tenant||version!==state.version)return;sessionId=s.id;research.session=s.id;sessionStorage.setItem('kg-research-'+tenant,s.id);research.sessions.unshift(s);const select=$('#research-session');if(select){const option=document.createElement('option');option.value=s.id;option.textContent=question.slice(0,60);select.append(option);select.value=s.id;}}
    const requestId=globalThis.crypto?.randomUUID?.()||('request-'+Date.now()+'-'+Math.random().toString(36).slice(2));
    const r=await api('/v1/agent/sessions/'+encodeURIComponent(sessionId)+'/messages',{method:'POST',body:JSON.stringify({question,request_id:requestId})});
    if(tenant!==state.tenant||sessionId!==research.session)return;
    research.drafts[researchKey()]='';
    research.runs.push({id:r.id,question,status:r.status,trace:[],created_at:new Date().toISOString()});
    if(version===state.version&&$('#agent-question'))$('#agent-question').value='';
    updateResearchUI();if(currentResearch())scheduleAgentPoll();
  }catch(e){if(tenant===state.tenant)error(e.message);}
  finally{research.sending=false;if(button&&currentResearch())button.disabled=research.runs.some(r=>['queued','running'].includes(r.status))||!research.capabilities?.enabled;}
}
function factDisplay(f,source){const context={scope:f.scope||source?.scope||{},...(f.comparison_scope||source?.compare_to?{compare_to:f.comparison_scope||source.compare_to}:{}),...f.context};return `<div class="fact-record"><span class="fact-id">${esc(f.id)}</span><div><strong>${esc(f.label)}</strong><small>${f.sample_size===null?'样本量未定义':`样本量 ${num(f.sample_size)}`} · ${esc(toolLabels[f.tool]||f.tool)}</small>${Object.keys(context).length?`<details><summary>计算口径</summary><pre>${esc(JSON.stringify(context,null,2))}</pre></details>`:''}</div><b>${esc(f.value)}<small>${esc(f.unit)}</small></b></div>`;}
function tableView(t){
  if(!t.rows.length)return '';
  const keys=Object.keys(t.rows[0]).filter(k=>!k.endsWith('_id'));
  return `<details class="report-table"><summary>${esc(t.title)} · ${t.rows.length} 行</summary><div class="table-wrap"><table><thead><tr>${keys.map(k=>`<th>${esc(fieldLabels[k]||k)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(r=>`<tr>${keys.map(k=>`<td>${esc(r[k]===null?'不可计算':Array.isArray(r[k])?r[k].join(' – '):k==='need'?translate(r[k]):r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
}
function reportContent(artifact){
  const c=artifact.content;
  return `<article class="panel report-document"><div class="report-document-head"><div class="eyebrow">RESEARCH ARTIFACT</div><h2>${esc(artifact.title)}</h2><p>${researchDate(artifact.created_at)} · ${esc(c.model)} · ${c.elapsed_seconds} 秒 · 引用 ID 已核验</p><div class="report-actions"><button class="button secondary" data-export-report="${esc(artifact.id)}" data-format="markdown">导出 Markdown</button><button class="button secondary" data-export-report="${esc(artifact.id)}" data-format="json">导出 JSON</button><button class="button primary" data-continue-session="${esc(artifact.session_id)}">继续追问</button></div></div><div class="report-document-body">${c.synthetic?'<div class="annotation-note"><strong>合成数据演示报告</strong><br>消费者与产品为虚构，本报告不构成真实市场结论。</div>':''}<div class="report-question"><small>研究问题</small><p>${esc(c.question)}</p></div><h3>研究摘要 <span class="muted">/ 模型解释</span></h3><p class="report-summary">${esc(c.summary)}</p><h3>洞察与判断</h3><div class="findings">${c.findings.map(f=>`<section class="finding ${f.kind}"><span class="pill ${f.kind==='observation'?'blue':f.kind==='hypothesis'?'amber':'teal'}">${kindLabels[f.kind]}</span><h3>${esc(f.title)}</h3><p>${esc(f.interpretation)}</p><div class="finding-refs">${f.fact_ids.map(id=>`<a href="#" data-scroll-fact="${esc(id)}">${esc(id)}</a>`).join('')}${f.evidence_ids.map(id=>evidenceButton(id,'原文证据')).join('')}</div></section>`).join('')}</div><h3>程序计算的事实 <span class="muted">/ ${c.facts.length} 条</span></h3><p class="form-note">数值直接来自工具计算；模型自然语言解释未进行逐句语义核验。</p><div class="report-facts">${c.facts.map(f=>`<div id="report-fact-${esc(f.id)}">${factDisplay(f,c.tool_results.find(r=>r.facts.some(x=>x.id===f.id)))}</div>`).join('')}</div><h3>分析数据表</h3>${c.tool_results.flatMap(r=>r.tables).map(tableView).join('')}<h3>下一步验证计划</h3>${c.next_actions.map((a,i)=>`<div class="next-action"><span>${i+1}</span><div><strong>${esc(a.action)}</strong><p>${esc(a.validation_plan)}</p><small>依据：${a.fact_ids.map(esc).join('、')}</small></div></div>`).join('')||'<p class="form-note">本轮未提出行动建议。</p>'}<h3>引用与原文</h3>${c.citations.map(r=>`<blockquote class="quote">${esc(r.quote)}<div class="citation-meta">${esc(r.source_id)} · ${r.synthetic?'合成':'未标记合成'} · ${esc(r.annotation_type)}</div>${evidenceButton(r.id,'查看完整原文与声明')}</blockquote>`).join('')||'<p class="form-note">本轮未检索到原文引用，请勿将模型解释当作直接访谈证据。</p>'}<h3>限制与研究口径</h3><ul class="report-limits">${c.limitations.map(l=>`<li>${esc(l)}</li>`).join('')}</ul><p class="form-note">模型调用 ${c.usage.model_calls} 次 · Token 用量 ${num(c.usage.total_tokens)} · 产物 ID ${esc(artifact.id)}</p></div></article>`;
}
async function reportsView(){
  const reports=await api('/v1/agent/artifacts');
  if(research.tenant!==state.tenant){research.artifactId=null;research.tenant=state.tenant;research.session=null;research.runs=[];}
  if(research.artifactId){
    try{const report=await api('/v1/agent/artifacts/'+encodeURIComponent(research.artifactId));return `<button class="text-link report-back" id="reports-back">所有洞察报告</button>${reportContent(report)}`;}catch(e){research.artifactId=null;throw e;}
  }
  return `${reports.length?`<div class="report-library">${reports.map(a=>`<article class="panel artifact-card"><div><span class="pill ${a.synthetic?'amber':'blue'}">${a.synthetic?'合成数据演示':'待研究者复核'}</span><small>${researchDate(a.created_at)}</small></div><h2>${esc(a.title)}</h2><p>${esc(a.summary.slice(0,220))}</p><button class="text-link" data-open-report="${esc(a.id)}">打开分析产物</button></article>`).join('')}</div>`:`<article class="panel">${empty('还没有洞察报告','在洞察 Agent 中提出研究问题，完成分析后会自动保存报告。')}<div class="empty-cta"><a class="button primary" href="#agent">开始研究</a></div></article>`}`;
}
async function exportReport(id,format,button){
  button.disabled=true;
  try{
    const response=await fetch(`/v1/agent/artifacts/${encodeURIComponent(id)}/export?format=${format}`,{headers:{'X-Tenant-Id':state.tenant,...(state.key?{'X-API-Key':state.key}:{})}});
    if(!response.ok)throw new Error('导出失败，请检查连接或访问权限。');
    const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=`insight-${id}.${format==='markdown'?'md':'json'}`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
  }catch(e){error(e.message);}finally{button.disabled=false;}
}
document.addEventListener('input',e=>{if(e.target.id==='agent-question')research.drafts[researchKey()]=e.target.value;});
document.addEventListener('change',e=>{if(e.target.id==='research-session'){if(!e.target.value){$('#new-research').click();return;}stopAgentPoll();research.session=e.target.value||null;research.runs=[];if(research.session)sessionStorage.setItem('kg-research-'+state.tenant,research.session);else sessionStorage.removeItem('kg-research-'+state.tenant);render();}});
document.addEventListener('submit',e=>{if(e.target.id==='agent-message-form'){e.preventDefault();const question=$('#agent-question').value.trim();if(question.length>=2)submitResearch(question);}});
document.addEventListener('click',e=>{
  const question=e.target.closest('[data-research-question]');if(question){if($('#agent-question')){$('#agent-question').value=question.dataset.researchQuestion;research.drafts[researchKey()]=question.dataset.researchQuestion;$('#agent-question').focus();}return;}
  if(e.target.closest('#new-research')){if(research.sending)return;const tenant=state.tenant,version=state.version;stopAgentPoll();research.session=null;research.runs=[];sessionStorage.removeItem('kg-research-'+tenant);api('/v1/agent/sessions',{method:'POST',body:JSON.stringify({title:'新的研究对话'})}).then(s=>{if(tenant!==state.tenant||version!==state.version)return;research.session=s.id;sessionStorage.setItem('kg-research-'+tenant,s.id);render();}).catch(e=>error(e.message));return;}
  const report=e.target.closest('[data-open-report]');if(report){research.artifactId=report.dataset.openReport;if(state.view==='reports')render();else location.hash='reports';return;}
  if(e.target.closest('#reports-back')){research.artifactId=null;render();return;}
  const continuation=e.target.closest('[data-continue-session]');if(continuation){research.session=continuation.dataset.continueSession;sessionStorage.setItem('kg-research-'+state.tenant,research.session);location.hash='agent';return;}
  const exporter=e.target.closest('[data-export-report]');if(exporter){exportReport(exporter.dataset.exportReport,exporter.dataset.format,exporter);return;}
  const fact=e.target.closest('[data-scroll-fact]');if(fact){e.preventDefault();$('#report-fact-'+fact.dataset.scrollFact)?.scrollIntoView({behavior:'smooth',block:'center'});}
});
