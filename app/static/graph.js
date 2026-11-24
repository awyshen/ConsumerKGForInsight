'use strict';
const atlasGraph={data:null,schema:null,selected:null,selectedEdge:null,positions:{},camera:{x:0,y:0,scale:1},filters:{q:'',entity_type:'',relation_type:'',depth:'2',limit:'120',include_consumers:false},focus:null,labels:true};
const graphTypeNames={Brand:'品牌',Product:'产品',ProductModel:'产品机型',ProductVariant:'产品配置',Feature:'产品功能',SellingPoint:'产品卖点',Need:'消费者需求',UsageScenario:'使用场景',Market:'市场',Channel:'渠道',Consumer:'匿名消费者身份',ConsumerSegment:'稳定业务群体'};
const graphColors={Brand:'#9361c9',Product:'#416bdd',ProductModel:'#416bdd',ProductVariant:'#416bdd',Feature:'#15948a',SellingPoint:'#d89a33',Need:'#cf6587',UsageScenario:'#789649',Market:'#547eac',Channel:'#8c7658',Consumer:'#7c8ba4',ConsumerSegment:'#79949e'};
const graphRelationNames={OWNS:'品牌拥有产品',HAS_FEATURE:'产品具备功能',PROMOTES:'产品主推卖点',BASED_ON:'卖点由功能支撑',SUPPORTS:'功能支持需求',OCCURS_IN:'需求发生的场景',PARENT_OF:'同类概念层级'};
async function graphView(){
  const tenant=state.tenant,version=state.version;
  if(atlasGraph.tenant!==tenant){atlasGraph.tenant=tenant;atlasGraph.focus=null;atlasGraph.selected=null;atlasGraph.selectedEdge=null;atlasGraph.filters.entity_type='';}
  const params=new URLSearchParams();
  for(const [key,value] of Object.entries(atlasGraph.filters))if(value!==''&&value!==false)params.set(key,String(value));
  if(atlasGraph.focus)params.set('focus_id',atlasGraph.focus);
  const [schema,data]=await Promise.all([api('/v1/graph/schema'),api('/v1/graph/view?'+params)]);
  if(tenant!==state.tenant||version!==state.version)return '';
  atlasGraph.schema=schema;atlasGraph.data=data;atlasGraph.camera={x:0,y:0,scale:1};layoutGraph();
  if(!data.nodes.some(n=>n.id===atlasGraph.selected))atlasGraph.selected=null;
  const f=atlasGraph.filters;
  return `<div class="graph-storage-strip"><div><span class="storage-symbol">⌘</span><span><b>Neo4j · 静态核心图谱</b><small>实体身份、产品、功能、卖点、需求与静态语义关系</small></span></div><div><span class="storage-symbol sql-symbol">▤</span><span><b>PostgreSQL · 事实与分析层</b><small>画像、访谈、声明、事件、动态群体与洞察产物</small></span></div></div>
  <form id="graph-filter" class="filters graph-filters"><label>实体名称 / 标准名<input name="q" value="${esc(f.q)}" placeholder="搜索游戏、Battery、Aster…"></label><label>起点实体类型<select name="entity_type" aria-label="起点实体类型"><option value="">全部业务实体</option>${schema.entity_types.map(t=>`<option value="${esc(t.type)}" ${t.type===f.entity_type?'selected':''}>${esc(graphTypeNames[t.type]||t.type)} · ${num(t.count)}</option>`).join('')}</select></label><label>语义关系<select name="relation_type" aria-label="语义关系"><option value="">全部静态关系</option>${schema.static_relations.map(k=>`<option value="${k}" ${k===f.relation_type?'selected':''}>${k}</option>`).join('')}</select></label><label class="small-input">展开深度<select name="depth" aria-label="展开深度">${[1,2,3,4].map(n=>`<option ${String(n)===f.depth?'selected':''}>${n}</option>`).join('')}</select></label><label class="small-input">节点上限<select name="limit" aria-label="节点上限">${[30,60,120,200].map(n=>`<option ${String(n)===f.limit?'selected':''}>${n}</option>`).join('')}</select></label><button type="submit" class="button primary">查询图谱</button></form>
  <div class="graph-meta"><label class="check-label"><input type="checkbox" id="graph-consumers" ${f.include_consumers?'checked':''}>包含匿名消费者身份</label><span>名称与类型限定起点，再按深度展开；画像与分析结论保留在 PostgreSQL</span>${atlasGraph.focus?'<button class="text-link" id="graph-clear-focus">返回完整范围</button>':''}</div>
  ${data.source!=='neo4j'?'<div class="annotation-note">当前显示 SQL 注册表的静态语义视图；Neo4j 未启用或不可达，此视图不代表实时投影状态。</div>':''}
  ${data.missing_seed_count?`<div class="annotation-note">${data.missing_seed_count} 个起点实体尚未出现在当前版本的 Neo4j 投影中，请检查投影任务。</div>`:''}
  <article class="panel graph-panel"><div class="panel-header"><div><h2>核心知识图谱</h2><p><span id="graph-node-count">${data.nodes.length}</span> 个节点 · ${data.edges.length} 条静态关系 · 本体 v${esc(data.ontology_version)}${data.truncated?' · 已达返回上限，请缩小范围':''}</p></div><div class="graph-source"><span class="pill ${data.source==='neo4j'?'teal':'amber'}">${data.source==='neo4j'?'Neo4j 实时查询':'SQL 注册表回退'}</span><small>${esc(data.projection_version)}</small></div></div>
  <div class="graph-canvas-toolbar"><div><button class="button secondary" data-graph-zoom="1.25" aria-label="放大图谱">＋</button><button class="button secondary" data-graph-zoom="0.8" aria-label="缩小图谱">−</button><button class="button secondary" id="graph-fit">适应画布</button><button class="button secondary" id="graph-layout">重新布局</button></div><label class="check-label"><input type="checkbox" id="graph-labels" ${atlasGraph.labels?'checked':''}>显示关系名称</label></div>
  <div class="graph-canvas" id="graph-canvas">${data.nodes.length?'<svg id="atlas-svg" viewBox="0 0 1100 700" role="group" aria-label="可交互的静态核心知识图谱" tabindex="0"><defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#aabbd0"/></marker></defs><g id="atlas-world"></g></svg>':empty('当前范围暂无已投影实体','请调整筛选条件，或加载静态产品目录并运行投影。')}</div>
  <div class="graph-legend">${[...new Set(data.nodes.map(n=>n.entity_type))].map(t=>`<span><i style="background:${graphColors[t]||'#8c9aaf'}"></i>${esc(graphTypeNames[t]||t)} <b>${data.nodes.filter(n=>n.entity_type===t).length}</b></span>`).join('')}</div><p class="graph-canvas-help">点击节点或连线查看详情 · 拖动节点调整布局 · 拖动画布平移 · Ctrl＋滚轮缩放 · 键盘 Enter 选中节点</p></article>
  <div class="graph-lower"><article class="panel"><div class="panel-header"><h2>实体与关系详情</h2><span class="pill blue">按统一 ID 关联</span></div><div class="panel-body" id="graph-detail">${empty('选择一个节点或关系','原文证据与声明通过 PostgreSQL 按需关联，不会成为静态图节点。')}</div></article><article class="panel"><div class="panel-header"><h2>图谱结构与存储边界</h2></div><div class="panel-body"><div class="semantic-path"><span>Brand</span><small>OWNS</small><span>Product</span><small>HAS_FEATURE</small><span>Feature</span><small>SUPPORTS</small><span>Need</span></div><div class="semantic-path"><span>Product</span><small>PROMOTES</small><span>SellingPoint</span><small>BASED_ON</small><span>Feature</span></div><p class="form-note section-space">本体定义概念；图谱表达静态关系；Claim 保存有来源的事实；Evidence 保存原文；Event 保存业务活动；InsightArtifact 保存分析结论。</p><p class="form-note section-space">动态筛选不会生成群体节点。ConsumerSegment 仅接收经明确标记的稳定业务定义；Consumer 图节点只保留匿名身份。没有产品路径不等于市场需求未被满足。</p></div></article></div>
  <details class="panel graph-node-list"><summary>当前节点列表 · ${data.nodes.length} 个（可通过键盘选择）</summary><div>${data.nodes.map(n=>`<button class="graph-list-node" data-graph-node="${esc(n.id)}"><i style="background:${graphColors[n.entity_type]||'#8c9aaf'}"></i>${esc(n.display_name||translate(n.name))}<small>${esc(graphTypeNames[n.entity_type]||n.entity_type)}</small></button>`).join('')}</div></details>`;
}
function layoutGraph(){
  const columns={Brand:80,Product:300,ProductModel:300,ProductVariant:300,SellingPoint:520,Feature:740,Need:960,UsageScenario:960,Market:80,Channel:300,Consumer:520,ConsumerSegment:740};
  const groups={};
  for(const n of atlasGraph.data.nodes)(groups[n.entity_type]||=[]).push(n);
  atlasGraph.positions={};
  for(const [type,nodes] of Object.entries(groups)){
    nodes.sort((a,b)=>a.name.localeCompare(b.name));
    const rows=Math.min(10,nodes.length),extra=Math.ceil(nodes.length/10);
    nodes.forEach((n,i)=>{const col=Math.floor(i/10),r=i%10;const x=(columns[type]||520)+(col-(extra-1)/2)*175;let y=rows===1?350:70+r*560/(rows-1);if(['UsageScenario','Market','Channel','ConsumerSegment'].includes(type))y+=26;atlasGraph.positions[n.id]={x,y};});
  }
}
function drawAtlas(){
  const world=$('#atlas-world');if(!world)return;
  const data=atlasGraph.data,c=atlasGraph.camera,p=atlasGraph.positions;
  world.setAttribute('transform',`translate(${c.x} ${c.y}) scale(${c.scale})`);
  world.innerHTML=data.edges.map(e=>{
    const a=p[e.source],b=p[e.target];if(!a||!b)return '';
    const direction=b.x>=a.x?1:-1;
    const x1=a.x+direction*78,x2=b.x-direction*84,mx=(x1+x2)/2,my=(a.y+b.y)/2;
    const selected=atlasGraph.selectedEdge===e.id;
    return `<g class="atlas-edge ${selected?'selected':''}"><path data-graph-edge="${esc(e.id)}" d="M${x1},${a.y} C${mx},${a.y} ${mx},${b.y} ${x2},${b.y}" marker-end="url(#graph-arrow)"><title>${esc(e.kind+' · '+(graphRelationNames[e.kind]||''))}</title></path>${atlasGraph.labels?`<text data-graph-edge="${esc(e.id)}" x="${mx}" y="${my-8}" text-anchor="middle">${esc(e.kind)}</text>`:''}</g>`;
  }).join('')+data.nodes.map(n=>{
    const pos=p[n.id],color=graphColors[n.entity_type]||'#8c9aaf',name=n.display_name||translate(n.name),label=name.length>17?name.slice(0,16)+'…':name;
    return `<g class="atlas-node ${atlasGraph.selected===n.id?'selected':''}" transform="translate(${pos.x},${pos.y})" data-graph-node="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc((graphTypeNames[n.entity_type]||n.entity_type)+' '+n.name)}"><title>${esc(n.name+' · '+n.entity_type+' · '+n.id)}</title><rect x="-78" y="-25" width="156" height="50" rx="9" fill="white" stroke="${color}"/><rect x="-78" y="-25" width="5" height="50" rx="2" fill="${color}"/><text text-anchor="middle" y="-1">${esc(label)}</text><text class="atlas-node-type" text-anchor="middle" y="17" fill="${color}">${esc(n.label)}</text></g>`;
  }).join('');
}
function initGraphCanvas(){
  drawAtlas();
  if(atlasGraph.selected)selectAtlasNode(atlasGraph.selected);
  const svg=$('#atlas-svg');if(!svg)return;
  let drag=null;
  const point=e=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());};
  svg.addEventListener('pointerdown',e=>{
    if(e.button!==0)return;
    const node=e.target.closest('[data-graph-node]');const at=point(e);
    drag={id:node?.dataset.graphNode,edge:e.target.closest('[data-graph-edge]')?.dataset.graphEdge,start:at,last:at,moved:false};svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener('pointermove',e=>{
    if(!drag)return;
    const at=point(e),dx=at.x-drag.last.x,dy=at.y-drag.last.y;
    if(Math.hypot(at.x-drag.start.x,at.y-drag.start.y)>5)drag.moved=true;
    if(drag.moved){if(drag.id){const n=atlasGraph.positions[drag.id];n.x+=dx/atlasGraph.camera.scale;n.y+=dy/atlasGraph.camera.scale;}else{atlasGraph.camera.x+=dx;atlasGraph.camera.y+=dy;}drawAtlas();}
    drag.last=at;
  });
  svg.addEventListener('pointerup',e=>{
    if(!drag)return;const moved=drag.moved,node=drag.id,edge=drag.edge;drag=null;svg.releasePointerCapture(e.pointerId);
    if(!moved&&node)selectAtlasNode(node);else if(!moved&&edge)selectAtlasEdge(edge);
  });
  svg.addEventListener('pointercancel',()=>{drag=null;});
  svg.addEventListener('wheel',e=>{if(!e.ctrlKey)return;e.preventDefault();zoomAtlas(e.deltaY<0?1.1:.9,point(e));},{passive:false});
  svg.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.dataset.graphNode){e.preventDefault();selectAtlasNode(e.target.dataset.graphNode);}});
}
function fitAtlas(){const p=Object.values(atlasGraph.positions);if(!p.length)return;const left=Math.min(...p.map(n=>n.x))-100,right=Math.max(...p.map(n=>n.x))+100,top=Math.min(...p.map(n=>n.y))-50,bottom=Math.max(...p.map(n=>n.y))+50;const scale=Math.min(1.5,1000/(right-left),620/(bottom-top));atlasGraph.camera={x:550-(left+right)/2*scale,y:350-(top+bottom)/2*scale,scale};drawAtlas();}
function zoomAtlas(factor,anchor={x:550,y:350}){const c=atlasGraph.camera;const next=Math.min(3,Math.max(.1,c.scale*factor));const ratio=next/c.scale;c.x=anchor.x+(c.x-anchor.x)*ratio;c.y=anchor.y+(c.y-anchor.y)*ratio;c.scale=next;drawAtlas();}
async function selectAtlasNode(id){
  atlasGraph.selected=id;atlasGraph.selectedEdge=null;drawAtlas();
  const detail=$('#graph-detail');if(!detail)return;detail.innerHTML='<div class="loading">正在读取实体与 PostgreSQL 关联</div>';
  const tenant=state.tenant;
  try{
    const d=await api('/v1/graph/nodes/'+encodeURIComponent(id));
    if(state.view!=='graph'||atlasGraph.selected!==id||tenant!==state.tenant)return;
    const n=d.node;
    detail.innerHTML=`<div class="graph-detail-title"><span class="pill blue">${esc(graphTypeNames[n.entity_type]||n.entity_type)}</span><h3>${esc(n.display_name||translate(n.name))}</h3><p>${esc(n.name)}</p></div><dl class="graph-properties"><dt>统一实体 ID</dt><dd class="source-code">${esc(n.id)}</dd><dt>状态 / 本体版本</dt><dd>${esc(n.status)} · ${esc(n.ontology_version)}</dd><dt>图谱层</dt><dd>${n.storage==='core_identity'?'匿名核心身份（画像保存在 PostgreSQL）':'静态业务实体'}</dd>${Object.entries(d.properties).map(([key,val])=>`<dt>${esc(key)}</dt><dd>${esc(val)}</dd>`).join('')}<dt>关联事实（PostgreSQL）</dt><dd>${num(d.sql_context.claim_count)} 条声明</dd></dl><button class="button primary" id="graph-expand" data-node="${esc(id)}">以此节点展开邻居</button><div class="subtle-rule"></div><p class="form-note">${esc(d.sql_context.note)}</p>${d.sql_context.evidence.map(e=>`<div>${evidenceButton(e.id,e.source_id+' · 查看原文')}</div>`).join('')}${n.entity_type==='Consumer'?'<a class="text-link" href="#consumers">浏览 PostgreSQL 消费者画像</a>':''}`;
  }catch(e){if(state.view==='graph'&&atlasGraph.selected===id)detail.innerHTML=`<div class="inline-error">${esc(e.message)}</div>`;}
}
function selectAtlasEdge(id){
  atlasGraph.selectedEdge=id;atlasGraph.selected=null;drawAtlas();
  const e=atlasGraph.data.edges.find(e=>e.id===id);if(!e)return;
  const source=atlasGraph.data.nodes.find(n=>n.id===e.source),target=atlasGraph.data.nodes.find(n=>n.id===e.target);
  $('#graph-detail').innerHTML=`<div class="graph-detail-title"><span class="pill teal">静态语义关系</span><h3>${esc(e.kind)}</h3><p>${esc(graphRelationNames[e.kind]||'')}</p></div><dl class="graph-properties"><dt>起点</dt><dd>${esc(source.display_name||translate(source.name))} · ${esc(source.label)}</dd><dt>终点</dt><dd>${esc(target.display_name||translate(target.name))} · ${esc(target.label)}</dd><dt>关系 ID</dt><dd class="source-code">${esc(e.id)}</dd><dt>本体版本</dt><dd>${esc(e.ontology_version)}</dd></dl><p class="form-note">该边表达静态业务语义，不代表购买因果、需求满足度或群体统计结论。</p>`;
}
document.addEventListener('submit',e=>{if(e.target.id!=='graph-filter')return;e.preventDefault();const values=Object.fromEntries(new FormData(e.target));atlasGraph.filters={...atlasGraph.filters,...values};atlasGraph.focus=null;atlasGraph.selected=null;render();});
document.addEventListener('change',e=>{if(e.target.id==='graph-consumers'){atlasGraph.filters.include_consumers=e.target.checked;atlasGraph.focus=null;render();}if(e.target.id==='graph-labels'){atlasGraph.labels=e.target.checked;drawAtlas();}});
document.addEventListener('click',e=>{
  const zoom=e.target.closest('[data-graph-zoom]');if(zoom){zoomAtlas(Number(zoom.dataset.graphZoom));return;}
  if(e.target.closest('#graph-fit')){fitAtlas();return;}
  if(e.target.closest('#graph-layout')){layoutGraph();atlasGraph.camera={x:0,y:0,scale:1};drawAtlas();return;}
  const expand=e.target.closest('#graph-expand');if(expand){atlasGraph.focus=expand.dataset.node;render();return;}
  if(e.target.closest('#graph-clear-focus')){atlasGraph.focus=null;atlasGraph.selected=null;render();return;}
  const edge=e.target.closest('[data-graph-edge]');if(edge){selectAtlasEdge(edge.dataset.graphEdge);return;}
  const node=e.target.closest('[data-graph-node]');if(node&&!node.closest('svg'))selectAtlasNode(node.dataset.graphNode);
});
