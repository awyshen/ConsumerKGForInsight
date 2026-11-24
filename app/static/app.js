'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = n => Number(n || 0).toLocaleString('zh-CN');
const countries = {Philippines:'菲律宾',Indonesia:'印度尼西亚',Vietnam:'越南',Thailand:'泰国',Malaysia:'马来西亚',Singapore:'新加坡'};
const flags = {Philippines:'🇵🇭',Indonesia:'🇮🇩',Vietnam:'🇻🇳',Thailand:'🇹🇭',Malaysia:'🇲🇾',Singapore:'🇸🇬'};
const names = {'Battery endurance':'电池续航','Camera quality':'影像体验','Affordable price':'价格与预算','Gaming performance':'游戏性能','Storage capacity':'存储容量','Charging speed':'充电速度','Durability':'耐用性','Connectivity':'网络连接','Display quality':'屏幕体验','Privacy and security':'隐私与安全','Long-life battery':'长续航电池','Night photography':'夜景摄影','Value for money':'高性价比','High-refresh display':'高刷新率屏幕','Expandable storage':'可扩展存储','Fast charging':'快速充电','Water resistance':'防水能力','5G connectivity':'5G 连接','Outdoor brightness':'户外亮度','Biometric security':'生物识别安全'};
const languageNames = {en:'英语',tl:'菲律宾语',zh:'中文'};
const eventNames = {INTERVIEW:'访谈',PRODUCT_CONSULTATION:'产品咨询',PRODUCT_EXPERIENCE:'产品体验',PRODUCT_COMPARISON:'产品比较',PURCHASE_INTENTION:'购买意向',PURCHASE:'购买',PURCHASE_REJECTION:'放弃购买',POST_PURCHASE_FEEDBACK:'购后反馈'};
const translate = name => names[name] || name;
const state = {tenant:sessionStorage.getItem('kg-tenant') || 'synthetic-demo',key:sessionStorage.getItem('kg-key') || '',summary:null,view:'overview',version:0,opportunities:[],selectedNeed:null,filters:{country:'Philippines',age_min:'26',age_max:'30'},evidence:{q:'',language:'',page:1},consumers:{country:'',page:1}};
const views = {
  graph:['知识图谱','看见实体之间的业务关系。','静态本体与语义关系留在图谱，事实与分析产物按 ID 回溯。'],
  agent:['洞察 Agent','让问题，变成可验证的洞察。','多轮追问 · 分析工具 · 图谱路径 · 可追溯研究产物'],
  reports:['洞察报告','把研究过程，沉淀为分析产物。','回看证据、核对口径，导出结构化报告并继续研究。'],
  overview:['数据概览','每个洞察，都有据可循。','连接消费者声音、产品需求与市场机会。'],
  opportunities:['需求与机会','从消费者需求，发现产品机会。','按国家与年龄筛选样本，追溯需求背后的证据与产品路径。'],
  consumers:['消费者样本','让样本，回到具体的生活。','浏览消费者属性，理解国家、职业、场景与预算。'],
  evidence:['证据库','回到消费者的原话。','检索访谈原文，核对来源、语言与知识声明。'],
  qa:['证据问答','带着问题，找到有依据的答案。','在明确的样本范围内提问，每个回答都保留证据引用。'],
  ingest:['访谈录入','让新的消费者声音，进入图谱。','通过规则或真实 LLM 抽取需求，低置信度内容进入审核。']
};
async function api(path, options={}) {
  const response = await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Tenant-Id':state.tenant,...(state.key?{'X-API-Key':state.key}:{}),...options.headers}});
  let data;
  try { data = await response.json(); } catch { throw new Error(`服务返回异常（HTTP ${response.status}）`); }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
    throw new Error(response.status === 401 ? '访问凭据无效，请在左下角连接设置中填写 API Key。' : `请求失败（${response.status}）：${detail}`);
  }
  return data;
}
function error(message) { const e=$('#global-error');e.textContent=message;e.hidden=false; }
function empty(title,text='请调整筛选条件，或先录入访谈数据。'){return `<div class="empty"><strong>${esc(title)}</strong>${esc(text)}</div>`;}
function options(selected,all=true){return `${all?'<option value="">全部国家</option>':''}${Object.entries(countries).map(([key,value])=>`<option value="${key}" ${key===selected?'selected':''}>${value}</option>`).join('')}`;}
function langTag(lang){return `<span class="pill blue">${esc(languageNames[lang] || lang)}</span>`;}
function evidenceButton(id,label='查看原文'){return `<button class="text-link" data-evidence="${esc(id)}">${esc(label)}</button>`;}
function bars(items,max,geo=false){return items.map(item=>`<div class="bar-row ${geo?'geo-row':''}"><span class="${geo?'country-label':''}">${geo?`<span>${flags[item.name] || '◉'}</span>`:''}${esc(geo?(countries[item.name]||item.name):translate(item.name))}</span><div class="bar-track"><div class="bar-fill" style="width:${max?Math.max(1,item.count/max*100):0}%"></div></div><span class="bar-value">${num(item.count)}</span></div>`).join('');}
function pager(data,scope){const pages=Math.max(1,Math.ceil(data.total/data.page_size));return `<div class="pagination"><span>共 ${num(data.total)} 条</span><button class="button secondary" data-page="${data.page-1}" data-scope="${scope}" ${data.page<=1?'disabled':''}>上一页</button><span>${data.page} / ${pages}</span><button class="button secondary" data-page="${data.page+1}" data-scope="${scope}" ${data.page>=pages?'disabled':''}>下一页</button></div>`;}
function updateWorkspace(){
  $('#tenant-label').textContent=state.tenant;
  $('#workspace-label').textContent=state.tenant==='synthetic-demo'?'合成研究空间':'研究工作空间';
  const synth=state.summary && state.summary.synthetic_consumers>0;
  $('#data-disclosure').textContent=synth?'包含合成数据':'数据口径说明';
  $('#data-disclosure-text').textContent=synth?'合成访谈、事件与产品仅用于验证系统；生成标签不等同于原文明确陈述，不能代表真实市场。':'结果为样本内描述统计，请核对数据来源与抽样口径，不能推断因果或总体市场。';
  $('.disclosure .pill').textContent=synth?'SYNTHETIC':'EVIDENCE';
}
async function render(){
  const version=++state.version;
  state.view=Object.hasOwn(views,location.hash.slice(1))?location.hash.slice(1):'overview';
  const view=state.view,[label,title,description]=views[view];
  document.querySelectorAll('nav a').forEach(a=>{a.classList.toggle('active',a.dataset.view===view);if(a.dataset.view===view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('#breadcrumb-current').textContent=label;$('#page-title').textContent=title;$('#page-description').textContent=description;
  $('#global-error').hidden=true;$('#view').innerHTML='<div class="loading" role="status">正在读取工作空间数据</div>';
  try {
    const summary=await api('/v1/console/summary');
    if(version!==state.version)return;
    state.summary=summary;updateWorkspace();$('#connection').textContent='主库已连接';$('#connection').classList.remove('offline');
    let content;
    if(view==='graph')content=await graphView();
    else if(view==='agent')content=await agentView();
    else if(view==='reports')content=await reportsView();
    else if(view==='overview')content=await overview();
    else if(view==='opportunities')content=await opportunities();
    else if(view==='evidence')content=await evidence();
    else if(view==='consumers')content=await consumers();
    else if(view==='qa')content=qa();
    else content=ingest();
    if(version===state.version){$('#view').innerHTML=content;if(view==='graph')initGraphCanvas();}
  } catch(e){if(version!==state.version)return;$('#view').innerHTML=empty('暂时无法加载数据','请检查服务状态或工作空间连接设置。');error(e.message);$('#connection').textContent='连接异常';$('#connection').classList.add('offline');}
}
async function overview(){
  const s=state.summary;
  const [insights,recent,graph]=await Promise.all([api('/v1/insights/needs?limit=6'),api('/v1/console/evidence?page_size=4'),api('/v1/console/graph')]);
  const metrics=[['消费者样本',s.consumers,'◎',`${s.countries.length} 个国家 · ${num(s.synthetic_consumers)} 位合成消费者`],['访谈证据',s.evidence,'▤',`${s.languages.length} 种语言 · 原文可追溯`],['已接受声明',s.claims,'⌘',`${num(s.needs)} 类需求 · ${num(s.selling_points)} 类卖点`],['交互事件',s.events,'◷',`${num(s.products)} 款产品 · ${s.event_types.length} 类行为`]];
  return `<div class="metrics">${metrics.map(([label,value,icon,note])=>`<article class="metric"><div class="metric-top">${label}<span class="metric-symbol">${icon}</span></div><div class="metric-value">${num(value)}</div><div class="metric-caption">${esc(note)}</div></article>`).join('')}</div>
  <div class="grid-two"><article class="panel"><div class="panel-header"><div><h2>消费者最关注什么？</h2><p>全空间需求排序 · 按去重消费者人数</p></div><a class="text-link" href="#opportunities">探索需求</a></div><div class="panel-body">${insights.needs.length?bars(insights.needs.map(x=>({name:x.name,count:x.consumer_count})),Math.max(...insights.needs.map(x=>x.consumer_count))):empty('暂无需求声明')}<div class="subtle-rule"></div><div class="inline-stats"><span>统计样本 <b>${num(insights.sample_size)} 人</b></span><span>多选需求 · 人数不相加</span></div></div></article>
  <article class="panel"><div class="panel-header"><div><h2>样本来自哪里？</h2><p>按国家划分的消费者样本分布</p></div><span class="pill teal">${s.countries.length} MARKETS</span></div><div class="panel-body">${bars(s.countries,Math.max(1,...s.countries.map(x=>x.count)),true)}<div class="subtle-rule"></div><div class="inline-stats">${s.languages.map(l=>`<span>${esc(languageNames[l.name]||l.name)} <b>${num(l.count)}</b></span>`).join('')}</div></div></article></div>
  <div class="grid-two"><article class="panel"><div class="panel-header"><div><h2>从原文到产品机会</h2><p>以证据为起点，建立可解释的知识链路</p></div></div><div class="panel-body"><div class="pipeline">${[['原始访谈','EVIDENCE',s.evidence],['知识声明','CLAIMS',s.claims],['静态语义关系','GRAPH EDGES',s.static_relations],['产品目录','PRODUCTS',s.products]].map(([label,en,n],i)=>`${i?'<span class="pipeline-connector">·</span>':''}<div class="pipeline-step"><small>${en}</small><strong>${label}</strong><b>${num(n)}</b></div>`).join('')}</div><p class="pipeline-note">PostgreSQL 保存事实与证据，Neo4j 提供异步图谱投影。生成标签属于合成真值，不代表已经由访谈原文逐条验证。</p></div></article>
  <article class="panel"><div class="panel-header"><div><h2>数据处理状态</h2><p>当前租户的任务与人工复核情况</p></div></div><div class="panel-body"><div class="health-row"><span>Neo4j 实时连接</span><span class="pill ${graph.status==='live'?'teal':'amber'}">${graph.status==='live'?'已连接':graph.status==='disabled'?'未启用':'不可达'}</span></div><div class="health-row"><span>待投影任务（含死信）</span><b class="${s.pending_projection?'pending':''}">${num(s.pending_projection)}</b></div><div class="health-row"><span>投影死信</span><b class="${s.dead_projection?'pending':''}">${num(s.dead_projection)}</b></div><div class="health-row"><span>待人工审核</span><b>${num(s.pending_review)}</b></div><p class="pipeline-note section-space">任务数来自主库；连接状态由 Neo4j 实时查询确认。审核管理请使用管理员 API。</p></div></article></div>
  <article class="panel"><div class="panel-header"><div><h2>访谈证据一览</h2><p>每条声明，都能回到原始来源</p></div><a href="#evidence" class="text-link">浏览证据库</a></div>${evidenceTable(recent.items)}</article>`;
}
function filterForm(){return `<form id="opportunity-filter" class="filters"><label>市场<select name="country">${options(state.filters.country)}</select></label><label class="small-input">最小年龄<input name="age_min" type="number" min="0" max="110" value="${esc(state.filters.age_min)}" placeholder="不限"></label><label class="small-input">最大年龄<input name="age_max" type="number" min="0" max="110" value="${esc(state.filters.age_max)}" placeholder="不限"></label><button class="button primary" type="submit">分析样本</button></form>`;}
async function opportunities(){
  const params=new URLSearchParams({limit:'100',evidence_limit:'3'});
  for(const [key,value] of Object.entries(state.filters))if(value!=='')params.set(key,value);
  const data=await api('/v1/opportunities?'+params);
  state.opportunities=data.opportunities;
  if(!data.opportunities.some(x=>x.need_id===state.selectedNeed))state.selectedNeed=data.opportunities[0]?.need_id;
  return `${filterForm()}<p class="sample-note">筛选匹配 <strong>${num(data.sample_size)}</strong> 位消费者 · 需求支持人数去重 · 比例仅为当前样本内占比</p>${!data.opportunities.length?`<div class="panel">${empty(data.sample_size?'样本尚无已接受的需求声明':'暂无匹配样本')}</div>`:`<div class="opportunity-layout"><div class="panel"><div class="panel-header"><h2>需求信号</h2><span class="pill blue">${data.opportunities.length} 类</span></div><div class="need-list">${data.opportunities.map(x=>`<button class="need-choice ${x.need_id===state.selectedNeed?'active':''}" data-need="${esc(x.need_id)}"><span><strong>${esc(translate(x.need))}</strong><small>${(x.share_of_cohort*100).toFixed(1)}% 样本提及</small></span><b>${num(x.consumer_count)}</b></button>`).join('')}</div></div><article class="panel" id="opportunity-detail">${opportunityDetail()}</article></div>`}`;
}
function graph(item){
  const features=item.linked_features.slice(0,3);
  const points=item.linked_selling_points.slice(0,Math.max(0,3-features.length));
  const middle=[...features.map(x=>({...x,kind:'Feature'})),...points.map(x=>({...x,kind:'SellingPoint'}))];
  const products=item.matching_products.slice(0,3);
  if(!middle.length)return '<div class="empty">该需求尚未关联功能或卖点，可使用关系 API 补充经确认的产品路径。</div>';
  const ys=n=>Array.from({length:n},(_,i)=>n===1?117:60+i*115/(n-1));
  const my=ys(middle.length),py=ys(products.length);
  let lines=middle.map((x,i)=>`<path class="graph-edge" d="M190 117 C220 117 220 ${my[i]} 250 ${my[i]}"/>`).join('');
  products.forEach((p,j)=>middle.forEach((m,i)=>{if([...p.features,...p.selling_points].some(x=>x.id===m.id))lines+=`<path class="graph-edge" d="M430 ${my[i]} C460 ${my[i]} 460 ${py[j]} 490 ${py[j]}"/>`;}));
  const node=(x,y,w,title,sub,need=false)=>`<g><rect class="graph-node ${need?'graph-node-need':''}" x="${x}" y="${y-25}" width="${w}" height="50" rx="8"/><text class="graph-label" x="${x+w/2}" y="${y+1}" text-anchor="middle">${esc(title.length>23?title.slice(0,22)+'…':title)}</text><text class="graph-kind" x="${x+w/2}" y="${y+17}" text-anchor="middle">${esc(sub)}</text></g>`;
  return `<div class="graph-area"><svg viewBox="0 0 700 235" role="img" aria-label="${esc(translate(item.need))}与功能、卖点和产品的关联图"><text class="graph-kind" x="110" y="24" text-anchor="middle">消费者需求</text><text class="graph-kind" x="340" y="24" text-anchor="middle">功能 / 卖点</text><text class="graph-kind" x="580" y="24" text-anchor="middle">产品目录</text>${lines}${node(30,117,160,translate(item.need),'Need',true)}${middle.map((m,i)=>node(250,my[i],180,translate(m.name),m.kind)).join('')}${products.map((p,i)=>node(490,py[i],180,p.product,'ProductModel')).join('')}</svg></div>`;
}
function opportunityDetail(){
  const x=state.opportunities.find(x=>x.need_id===state.selectedNeed);if(!x)return '';
  return `<div class="detail-content"><div class="detail-title"><div><h2>${esc(translate(x.need))}</h2><p class="muted" style="font-size:.8rem;margin-top:7px">${esc(x.need)}</p></div><span class="pill blue">需求信号</span></div><div class="detail-count">${num(x.consumer_count)}<small>位消费者 · 样本占比 ${(x.share_of_cohort*100).toFixed(1)}%</small></div>${graph(x)}<h3>匹配的产品路径</h3>${x.matching_products.length?x.matching_products.map(p=>`<div class="product-card"><span class="product-glyph">▯</span><div><h3>${esc(p.product)}</h3><p>${esc([...p.features,...p.selling_points].map(f=>translate(f.name)).join(' · '))}</p><p>基于已登记关系匹配，不代表性能评测或购买推荐。</p></div></div>`).join(''):'<p class="muted section-space">暂无已登记的产品路径。</p>'}<div class="subtle-rule"></div><h3>支持证据 <span class="muted">/ ${x.supporting_evidence.length} 条展示</span></h3>${x.supporting_evidence.map(e=>`<blockquote class="quote">${esc(e.excerpt)}${evidenceButton(e.id,e.source_id+' · 查看完整原文')}</blockquote>`).join('') || '<p class="muted section-space">暂无可展示证据。</p>'}</div>`;
}
function evidenceTable(items){return items.length?`<div class="table-wrap"><table><thead><tr><th>来源编号</th><th>访谈摘录</th><th>语言</th><th>数据来源</th><th>操作</th></tr></thead><tbody>${items.map(e=>`<tr><td class="source-code">${esc(e.source_id)}</td><td><div class="truncate">${esc(e.excerpt)}</div></td><td>${langTag(e.language)}</td><td><span class="pill ${e.metadata.synthetic?'amber':'teal'}">${e.metadata.synthetic?'合成':'未标记合成'}</span></td><td>${evidenceButton(e.id)}</td></tr>`).join('')}</tbody></table></div>`:empty('未找到访谈证据','请调整关键词、语言，或录入新的访谈。');}
async function evidence(){
  const params=new URLSearchParams({page:String(state.evidence.page),page_size:'20',q:state.evidence.q});if(state.evidence.language)params.set('language',state.evidence.language);
  const data=await api('/v1/console/evidence?'+params);
  return `<form id="evidence-filter" class="filters"><label>关键词或来源编号<input name="q" value="${esc(state.evidence.q)}" placeholder="搜索 battery、续航或 SYN-INT…"></label><label class="small-input">访谈语言<select name="language"><option value="">全部语言</option>${Object.entries(languageNames).map(([key,value])=>`<option value="${key}" ${key===state.evidence.language?'selected':''}>${value}</option>`).join('')}</select></label><button class="button primary" type="submit">搜索证据</button></form><article class="panel">${evidenceTable(data.items)}${pager(data,'evidence')}</article>`;
}
async function consumers(){
  const params=new URLSearchParams({page:String(state.consumers.page),page_size:'20'});if(state.consumers.country)params.set('country',state.consumers.country);
  const data=await api('/v1/console/consumers?'+params);
  return `<form id="consumer-filter" class="filters"><label>市场<select name="country">${options(state.consumers.country)}</select></label><button class="button primary" type="submit">筛选样本</button></form><article class="panel"><div class="panel-header"><div><h2>消费者样本档案</h2><p>属性来自原始数据；未知字段保留为空。</p></div><span class="pill blue">${num(data.total)} SAMPLES</span></div>${data.items.length?`<div class="table-wrap"><table><thead><tr><th>消费者</th><th>国家</th><th>年龄</th><th>职业</th><th>使用场景</th><th>预算 / USD</th><th>来源</th></tr></thead><tbody>${data.items.map(c=>`<tr><td class="source-code">${esc(c.key)}</td><td>${esc(countries[c.attrs.country]||c.attrs.country||'—')}</td><td>${esc(c.attrs.age??'—')}</td><td>${esc(c.attrs.occupation||'—')}</td><td>${esc(c.attrs.scenario||'—')}</td><td>${esc(c.attrs.budget_usd??'—')}</td><td><span class="pill ${c.attrs.synthetic?'amber':'teal'}">${c.attrs.synthetic?'合成':'未标记合成'}</span></td></tr>`).join('')}</tbody></table></div>`:empty('暂无消费者样本')}${pager(data,'consumers')}</article>`;
}
function qa(){return `<div class="qa-layout"><div class="qa-intro"><span class="qa-symbol">✧</span><h2>让证据回答你的问题</h2><p>支持六国市场与年龄段筛选，统计需求与明确卖点。</p></div><form id="qa-form" class="panel qa-form"><label for="qa-question" class="muted">研究问题</label><textarea id="qa-question" name="question" required minlength="5" maxlength="500" placeholder="例如：菲律宾26-30岁消费者购机需求是什么？"></textarea><div class="qa-form-bottom"><span>确定性统计问答 · 暂不支持时间、比较或因果分析</span><button class="button primary" type="submit">查询证据</button></div></form><div class="suggestions">${['菲律宾26-30岁消费者购机需求是什么？','印度尼西亚消费者最看重哪些需求？','越南消费者提到了哪些卖点？'].map(q=>`<button class="suggestion" data-question="${esc(q)}">${esc(q)}</button>`).join('')}</div><div id="qa-result"></div></div>`;}
function ingest(){return `<article class="panel"><div class="panel-header"><div><h2>录入一条访谈</h2><p>数据写入当前工作空间：${esc(state.tenant)}。使用真实 LLM 会调用已配置的模型服务。</p></div></div><form id="ingest-form" class="ingest-form"><div class="form-grid"><label>来源编号<input name="source_id" required maxlength="180" placeholder="例如 INT-2026-001"></label><label>消费者编号<input name="consumer_key" required maxlength="180" placeholder="同一消费者请保持相同编号"></label><label>国家<select name="country">${options('Philippines',false)}</select></label><label>年龄<input name="age" type="number" min="13" max="110" required value="28"></label><label>原文语言<select name="language">${Object.entries(languageNames).map(([key,v])=>`<option value="${key}">${v}</option>`).join('')}</select></label><label>抽取方式<select name="mode"><option value="rules">规则抽取 · 无外部调用</option><option value="llm">真实 LLM · 使用服务配置</option></select></label><label class="wide">访谈原文<textarea name="excerpt" required minlength="2" maxlength="20000" placeholder="粘贴完整访谈原文。请先完成脱敏与授权。"></textarea></label><label class="wide check-label"><input type="checkbox" name="synthetic" ${state.tenant==='synthetic-demo'?'checked':''}>这是一条合成或虚构访谈</label><p class="wide form-note">仅通过证据校验与实体归一的正向声明会进入事实库；其他内容进入审核队列。相同消费者编号的已有属性不会被本次录入覆盖。</p><div class="wide"><button class="button primary" type="submit">抽取并保存</button><span class="muted" id="ingest-status" style="margin-left:14px;font-size:.8rem"></span></div></div><div id="ingest-result"></div></form></article>`;}
async function showEvidence(id){
  const dialog=$('#evidence-dialog');$('#evidence-detail').innerHTML='<div class="loading">正在读取原文</div>';if(!dialog.open)dialog.showModal();
  try {
    const e=await api('/v1/console/evidence/'+encodeURIComponent(id));
    $('#evidence-detail').innerHTML=`<span class="source-code">${esc(e.source_id)}</span><div class="detail-meta">${esc(languageNames[e.language]||e.language)} · ${e.metadata.synthetic?'合成访谈':'未标记为合成'}${e.metadata.interviewed_at?' · '+esc(e.metadata.interviewed_at.slice(0,10)):''}</div><blockquote class="quote">${esc(e.excerpt)}</blockquote>${e.metadata.annotation_type==='generated_ground_truth'?'<p class="annotation-note">本条声明来自生成器合成真值，卖点标签可能并未出现在原文中，不应当作原文直接证据。</p>':''}<h3>关联声明</h3>${e.claims.map(c=>`<div class="claim-line"><div>${esc(translate(c.name))}<small>${esc(c.predicate)} · ${esc(c.extractor_version)}</small></div><span class="pill ${c.status==='accepted'?'teal':'amber'}">${esc(c.status)} · ${(c.confidence*100).toFixed(0)}%</span></div>`).join('')||'<p class="muted section-space">暂无关联声明，可能尚待审核。</p>'}`;
  }catch(e){$('#evidence-detail').innerHTML=`<div class="error-banner">${esc(e.message)}</div>`;}
}
document.addEventListener('click',e=>{
  const close=e.target.closest('[data-close]');if(close){$('#'+close.dataset.close).close();return;}
  const evidence=e.target.closest('[data-evidence]');if(evidence){showEvidence(evidence.dataset.evidence);return;}
  const need=e.target.closest('[data-need]');if(need){state.selectedNeed=need.dataset.need;document.querySelectorAll('.need-choice').forEach(b=>b.classList.toggle('active',b.dataset.need===state.selectedNeed));$('#opportunity-detail').innerHTML=opportunityDetail();return;}
  const page=e.target.closest('[data-page]');if(page&&!page.disabled){state[page.dataset.scope].page=Number(page.dataset.page);render();return;}
  const question=e.target.closest('[data-question]');if(question){$('#qa-question').value=question.dataset.question;$('#qa-form').requestSubmit();}
});
function openSettings(){$('#setting-tenant').value=state.tenant;$('#setting-key').value=state.key;$('#settings-dialog').showModal();}
$('#settings-button').addEventListener('click',openSettings);
$('#mobile-settings-button').addEventListener('click',openSettings);
$('#settings-form').addEventListener('submit',e=>{e.preventDefault();const tenant=$('#setting-tenant').value.trim();if(!tenant)return;state.tenant=tenant;state.key=$('#setting-key').value;sessionStorage.setItem('kg-tenant',tenant);sessionStorage.setItem('kg-key',state.key);state.evidence.page=1;state.consumers.page=1;$('#settings-dialog').close();render();});
$('#refresh-button').addEventListener('click',render);
window.addEventListener('hashchange',render);
document.addEventListener('submit',async e=>{
  const form=e.target;if(!['opportunity-filter','evidence-filter','consumer-filter','qa-form','ingest-form'].includes(form.id))return;
  e.preventDefault();const values=Object.fromEntries(new FormData(form));$('#global-error').hidden=true;
  if(form.id==='opportunity-filter'){
    if(values.age_min!==''&&values.age_max!==''&&Number(values.age_min)>Number(values.age_max)){error('最小年龄不能大于最大年龄。');return;}
    state.filters=values;render();return;
  }
  if(form.id==='evidence-filter'){state.evidence={...values,page:1};render();return;}
  if(form.id==='consumer-filter'){state.consumers={...values,page:1};render();return;}
  const button=$('button[type="submit"]',form);button.disabled=true;
  const version=state.version;
  try {
    if(form.id==='qa-form'){
      const target=$('#qa-result');target.innerHTML='<div class="loading">正在汇总声明与证据</div>';
      const d=await api('/v1/qa/ask',{method:'POST',body:JSON.stringify({question:values.question})});
      if(version!==state.version)return;
      target.innerHTML=`<article class="panel"><div class="panel-header"><h2>基于 ${num(d.sample_size)} 位消费者的回答</h2><span class="pill blue">证据统计</span></div><div class="answer-content"><p>${esc(d.answer)}</p><div class="tag-row">${[...d.needs,...d.selling_points].map(n=>`<span class="label-tag">${esc(translate(n.name))} · ${n.consumer_count} 人</span>`).join('')}</div><p class="form-note">已应用条件：${esc(countries[d.filters.country]||d.filters.country||'全部国家')} · 年龄 ${d.filters.age_min??'不限'} 至 ${d.filters.age_max??'不限'}。仅描述样本内统计，不代表市场总体。</p>${Object.values(d.citations).map(c=>`<blockquote class="quote">${esc(c.quote)}${evidenceButton(c.evidence_id,c.source_id+' · 核对原文')}</blockquote>`).join('')}</div></article>`;
    }else{
      $('#ingest-status').textContent=values.mode==='llm'?'正在调用模型，请稍候…':'正在校验证据并写入…';
      const d=await api('/v1/knowledge/interviews',{method:'POST',body:JSON.stringify({...values,age:Number(values.age),synthetic:values.synthetic==='on'})});
      if(version!==state.version)return;
      $('#ingest-result').innerHTML=`<div class="ingest-result"><strong>访谈已保存</strong><p>通过 ${d.accepted} 条 · 待审核 ${d.review.length} 条 · 去重声明 ${d.claim_ids.length} 条</p>${evidenceButton(d.evidence_id,'核对入库原文与声明')}<p class="form-note">Neo4j 投影由 worker 异步执行；审核管理使用管理员 API。</p></div>`;
      $('#ingest-status').textContent='保存完成';
    }
  }catch(err){
    if(version!==state.version)return;
    if(form.id==='qa-form')$('#qa-result').innerHTML=`<div class="error-banner">${esc(err.message)}</div>`;
    else{$('#ingest-status').textContent='保存失败';$('#ingest-result').innerHTML=`<div class="inline-error">${esc(err.message)}</div>`;}
  }finally{button.disabled=false;}
});
window.addEventListener('DOMContentLoaded',render);
