# Mobile Consumer Knowledge Graph — V4

基于 V3 的手机消费者知识图谱与洞察工程。核心链路：访谈抽取与证据校验 → PostgreSQL 事实/事件层；实体注册与静态语义关系 → Outbox → Neo4j 核心图谱；SQL 群体统计＋图谱路径 → Agent → PostgreSQL 洞察产物。

## 本次新增

- `app/opportunity.py`：多跳关联，去重消费者人数，证据追溯和产品匹配。
- `app/governance.py`：人工审核、实体别名登记、审计日志、全量图谱重建入队。
- `app/quality.py`：多语言抽取 Precision/Recall/F1。
- `scripts/seed_catalog_v4.py`：虚构机型与功能目录，用于验证产品关联路径。
- `scripts/batch_ingest_v4.py`：JSONL 逐条事务导入。
- `alembic/`：新部署初始迁移。
- `tests/test_v4.py`：新增多跳、隔离、评测、权限测试。

## 快速运行

```bash
python -m pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
python -m scripts.synthetic_pipeline load --tenant synthetic-demo
python -m scripts.seed_catalog_v4 --tenant synthetic-demo
uvicorn app.main:app --reload
pytest -q
```

打开 `http://127.0.0.1:8000/docs`，测试：

```bash
curl 'http://127.0.0.1:8000/v1/opportunities?country=Philippines&age_min=26&age_max=30' \
  -H 'X-Tenant-Id: synthetic-demo'
```

Docker: 先在 `.env` 设置 `API_KEY`、`ADMIN_API_KEY`、`POSTGRES_PASSWORD`、`NEO4J_PASSWORD`，然后 `docker compose up -d --build`。LLM 默认关闭，按需启用。

## 数据与测试

保留 V3 合成消费者数据及原有 SQLite 示例数据库；它们是虚构的，不是实际消费者调研。`data/knowledge_v3.db` 为 V3 数据快照，V4 需要迁移后才能新增审核等表。

**已验证**：38 项 pytest 测试、桌面/手机浏览器交互、PostgreSQL 合成数据导入、Neo4j 全量投影 ID 核对，以及真实 LLM 英文抽取与证据问答链路（Neo4j 使用应用自动管理的 WSL→Windows 通道）。**未验证**：生产性能、并发故障恢复、真实调研质量；中文 LLM 实体归一仍存在已知限制。

详细说明见 [docs/production_v4.md](docs/production_v4.md)。

## 前端工作台与合成数据

运行 `uvicorn app.main:app --reload` 后打开 **http://127.0.0.1:8000/**。
前端和 API 使用同一个服务，无需 Node.js 安装或独立构建。默认空间为 `synthetic-demo`；
桌面左下角或手机顶部的连接设置可切换租户、填写 API Key，凭据只保存于浏览器会话。

工作台包含：

- **数据概览**：样本、证据、声明、事件计数，国家/语言分布与投影积压。
- **需求与机会**：按国家和年龄筛选，展示需求人数、样本内占比、功能/卖点/产品关联图与原文证据。
- **消费者样本**：分页浏览国家、年龄、职业、场景与预算。
- **证据库**：按关键词、来源编号和语言搜索，核对原文、声明及抽取版本。
- **快速统计**：限定国家/年龄的统计问答与可点击引用。
- **洞察 Agent**：多轮研究、工具调用、群体对比、分群与图谱关联。
- **洞察报告**：保存分析产物、回看原文与计算口径、导出 Markdown / JSON。
- **访谈录入**：规则或已配置的真实 LLM 抽取；待复核内容仍由管理员 API 管理。

向 `.env` 指向的数据库导入仓库内完整合成数据（可重复执行，不覆盖其他租户）：

```bash
alembic upgrade head
APP_ENV=production python -m scripts.synthetic_pipeline load --tenant synthetic-demo
python -m scripts.seed_catalog_v4 --tenant synthetic-demo
# 持续处理该租户的图谱任务；需要 Neo4j 地址可从当前运行环境访问
python -m scripts.graph_worker --tenant synthetic-demo --batch 500
# 仅处理一批时加 --once
```

数据集含 **1,200 位消费者、1,200 条访谈、4,425 条事件**，覆盖六个国家和三种语言。
产品目录含 3 款虚构产品。合成真值导入后有 4,141 条声明；这些生成标签不是 LLM 真实抽取评测结果，
尤其卖点标签可能没有在访谈原文中明确出现。证据详情保留该来源说明，不应将演示结果用于真实市场决策。

新增只读接口：`/v1/console/summary`、`/v1/console/consumers`、`/v1/console/evidence`、
`/v1/console/evidence/{id}`，继承现有 API Key 和租户过滤。

若 Neo4j Desktop 运行在 Windows 而 API 在 WSL，`127.0.0.1` 未必互通。
项目会在 WSL 检测 Windows 本地实例并自动建立应用管理的 Bolt 通道；API 与 worker 无需额外手工启动转接。详见下文连接配置。

## 对话式洞察 Agent

打开 **http://127.0.0.1:8000/#agent**，选择或新建研究会话。服务端需要配置真实 LLM；
现有 `/v1/qa/ask` 保留为“快速统计”，Agent 使用独立的规划与工具执行链路。

先运行 `alembic upgrade head`，创建会话、分析任务和报告表。已有消费者事实不变。

推荐的连续分析方式：

1. **确定研究范围**：“分析菲律宾26-30岁消费者的需求，按使用场景细分，并结合产品路径提出待验证的机会。”
2. **比较与找反例**：“与印度尼西亚同年龄消费者相比，哪些需求差异最值得验证？”
3. **深入具体问题**：“对游戏需求进一步按预算分群，核对原文；哪些解释仍然只是研究假设？”
4. **沉淀产物**：在“洞察报告”查看事实、数据表、原文引用、行动验证计划，导出 Markdown / JSON，或回到原会话继续追问。

### 实际执行链路

`多轮上下文 → LLM 研究计划 → 受约束工具 → 可选补充工具 → 结构化报告 → 引用 ID 校验 → 持久化产物`

模型可选择六类只读工具：样本与需求画像、群体对比、按场景/职业/年龄/预算分群、
产品图谱路径、原文检索、行为事件统计。人数按消费者去重；占比、占比差与描述性 Wilson 区间
由程序计算。产品路径优先核对固定的 Neo4j 查询；无法连通时明确展示 SQL 知识图谱回退。
模型不能提交任意 SQL/Cypher、选择其他租户，或修改消费者事实。

每轮分析保存研究问题、工具参数与结果快照、模型、Token 用量、执行耗时和报告。
报告区分 **数据观察 / 待验证假设 / 行动建议**，附程序计算事实、原始证据、样本口径和局限。
不存在的事实 ID 或证据 ID 会触发纠正；纠正失败则该轮失败，不保存为有效报告。
**引用 ID 正确不等于自然语言解释已经逐句核验**；模型解释仍需研究者复核。

### API 与配置

- `POST /v1/agent/sessions`：新建会话。
- `POST /v1/agent/sessions/{id}/messages`：提交 `question` 和唯一 `request_id`，返回任务 ID。
- `GET /v1/agent/runs/{id}`：查看状态、执行记录和产物。
- `GET /v1/agent/sessions`、`GET /v1/agent/sessions/{id}`：恢复会话与追问历史。
- `GET /v1/agent/artifacts`、`GET /v1/agent/artifacts/{id}`：报告库与详情。
- `GET /v1/agent/artifacts/{id}/export?format=markdown`（或 `json`）：导出报告。

接口继承现有 `X-Tenant-Id` / `X-API-Key`。同一会话一次只运行一轮；重复 `request_id`
不会重复执行。最近四轮对话及其分析范围进入模型上下文；更早轮次可在会话/报告中回看，但不保证自动进入模型上下文。

可选环境变量：`AGENT_MAX_TOOL_CALLS=6`（最多六次）、`AGENT_LLM_TIMEOUT_SECONDS=120`。
整轮分析超时为七分钟。当前使用进程内后台任务与数据库任务状态，并非独立持久化任务队列；
浏览器刷新不会中断任务，但服务重启会中断执行，过期任务在十分钟后标记失败，可重新提交。
前端轮询展示执行状态，不展示模型私有推理过程。

目前支持探索性关联分析，暂不提供销量预测、因果归因、时间趋势、自动产品规格采信或真实市场有效性保证。
合成标签中卖点可能并未出现在原文中，行为事件也不构成完整转化漏斗。


## Neo4j 连接与生成速度

Windows Neo4j Desktop 只监听 `127.0.0.1` 而 API 在 WSL 时，保持 `.env` 中现有连接地址和凭据，
默认 `NEO4J_WSL_BRIDGE=auto` 会在 WSL 本地端口不可达时，利用 Windows PowerShell 建立仅监听
WSL 回环地址的二进制 Bolt 转接。通道由 API/worker 自己管理，启动时按需创建，退出时清理；
密码不进入 PowerShell 命令参数，不需要修改 Windows 防火墙或把数据库暴露到局域网。
Neo4j Desktop 数据库仍需处于 Running 状态，WSL Interop 及 `powershell.exe` 需可用。

- `auto`：仅对 WSL、非 TLS 的本地 `bolt://` / `neo4j://` 地址启用，原地址可直连时保留直连。
- `enabled`：在符合上述本地条件时强制使用 Windows 回环转接。
- `disabled`：禁止转接；Docker / 原生 Linux / 远端 TLS 连接均使用原地址直连。

`GET /v1/console/graph` 返回实时查询状态、连接方式与延迟，不返回密钥；数据概览也显示该状态。
API 与投影 worker 共用同一连接模块，各进程复用自己的 Neo4j 连接池。

Agent 默认 `AGENT_THINKING=auto`：识别到 DeepSeek 时使用官方 `thinking.type=disabled` 参数，
其他模型保持供应商默认行为。可配置 `enabled` 恢复思考模式（供应商必须支持此参数）。
参数说明参考 [DeepSeek 官方接口文档](https://api-docs.deepseek.com/api/create-chat-completion/)。
`AGENT_PARALLEL_TOOLS=true` 使独立只读工具最多三个并发执行，事实 ID 仍按计划顺序生成。
生成上下文移除了重复事实/引文，完整工具快照仍保存在报告中；结构、引用校验与必要的补充分析保留。
模型格式校验失败时，纠正请求包含具体字段错误，避免反复生成同样的无效结果。

同一研究问题的实测（同一模型、同一数据，非性能 SLA）：

| 问题 | 优化前 | 优化后 |
|---|---:|---:|
| 菲律宾青年消费者场景与产品路径 | 140.92 秒 | 50.60 秒 |
| 菲律宾与印尼同年龄群体连续对比 | 163.97 秒 | 72.06 秒 |
| 下一代手机功能卖点追问（实际 API） | 超时 | 46.80 秒 |

首轮仍保留 37 条程序计算事实与 6 条 Neo4j/SQL 一致的产品路径；两轮均通过引用校验并保存报告。
报告的 `timings` 记录规划、综合等模型阶段耗时，`usage` 记录 Token 与模型调用数。
供应商排队和网络状态会影响实际延迟；当前快速模式的解释质量仍需研究者复核。


## 按领域设计规范分层与展示图结构

本次落实 [领域本体与知识图谱详细设计规范 V1.0](docs/手机消费者洞察系统_领域本体与知识图谱详细设计规范V1.0.md)
第 2、4.3、5、6、7、12.4、15.1 节的存储职责与查询边界。本体配置为 `1.1.0`，投影策略为 `static-core-v1`。
规范文件作为设计依据保留，本次不宣称已完成规范第 17 节列出的全部生产能力。

| 对象 | PostgreSQL | Neo4j |
|---|---|---|
| 统一实体 ID 与登记信息 | 实体注册表 `entities` | 相同 ID 的核心实体节点 |
| 品牌、产品、功能、卖点、需求、市场、场景、渠道 | 登记、治理与来源 | 核心实体及静态语义关系 |
| Consumer | 匿名主键与画像属性 | 仅匿名身份；年龄、职业、预算等不投影 |
| ConsumerSegment | 动态筛选条件 `segments` | 仅 `stable_business_definition=true` 且有效的业务定义实体 |
| 消费者表达与行为 | `claims`、SQL 关系记录、`evidence`、`interaction_events` | 不生成默认永久事实边 |
| Agent 对话、分析过程与报告 | `analysis_sessions`、`analysis_runs`、`insight_artifacts` | 不创建图节点或分析结论边 |

Neo4j 使用 `KGEntity` 统一身份标签，以及 `Brand / Product / Feature / SellingPoint / Need / Consumer` 等业务标签。
`ProductModel`、`ProductVariant` 是产品注册表中的兼容类型，图中统一使用 `Product` 标签。
静态边使用真实关系类型，而不是统一 `KG_REL`：

```text
Brand -OWNS-> Product -HAS_FEATURE-> Feature -SUPPORTS-> Need
Product -PROMOTES-> SellingPoint -BASED_ON-> Feature
Need -OCCURS_IN-> UsageScenario
```

需求和功能各自的 `PARENT_OF` 是分类层级扩展，禁止跨类型连接。
兼容旧 API：Feature `ADDRESSES` Need 归一为 `SUPPORTS`；Product `COMMUNICATES` SellingPoint 归一为 `PROMOTES`。
旧的消费者 `HAS_NEED / RESPONDS_TO` 和分析性的 `TARGETS / APPEALS_TO` 等仍可在 SQL 中保留，
不会直接成为静态图边。历史 SellingPoint `ADDRESSES` Need 关系保留在 SQL，图谱只采用明确的 `BASED_ON` 功能支撑路径。
新洞察产物记录本体版本、分析方法与 PostgreSQL 存储层标识；历史报告快照不被重写。

### 图谱浏览

打开 **http://127.0.0.1:8000/#graph**：

- 查看 Neo4j 实时图结构，按实体名（支持中文展示名和已登记别名）、起点类型、语义关系筛选。
- 点击节点或连线查看语义、统一 ID、本体版本与 SQL 关联事实。
- 以节点展开一至四层邻居，默认最多 120 个节点，上限 200 个节点、600 条边。
- 拖动节点、平移画布、缩放与适应布局；小屏可使用可读的节点列表选择实体。
- 默认不展示大量孤立消费者身份；开启“包含匿名消费者身份”后仍不展示画像属性或访谈事实边。
- Neo4j 不可用时明确标记 SQL 注册表静态视图回退，不冒充实时图谱。

接口：`GET /v1/graph/schema`、`GET /v1/graph/view`、`GET /v1/graph/nodes/{id}`。
使用现有租户与 API Key 校验，不接受任意 Cypher；同名关系的 domain/range 按具体变体校验。

### 升级已有图谱投影

已有 SQL 数据无需删库或重建表。先更新静态目录，再在维护窗口按租户重建投影：

```bash
python -m scripts.seed_catalog_v4 --tenant synthetic-demo
python -m scripts.reconcile_static_graph --tenant synthetic-demo --dry-run
python -m scripts.reconcile_static_graph --tenant synthetic-demo
# 后续持续投影
python -m scripts.graph_worker --tenant synthetic-demo --batch 500
```

重建会先备份该租户的旧 Neo4j 节点与关系到 `data/graph_backups/`（本地文件默认仅当前用户可读写，已忽略 Git），
再以一个 Neo4j 事务替换项目管理的图谱投影，并核对节点和关系 ID。其他租户不受影响。
重建期间请暂停该租户的入库与其他投影 worker，避免并发数据变化导致校验失败。
SQL 中的实体登记、Claim、Evidence、Event 与历史分析报告不会被删除；只有已捕获的 Outbox 任务更新处理状态。

当前合成空间验证：1,229 个核心身份/实体节点（其中 1,200 个匿名消费者身份）、19 条静态语义边；
默认前端显示 29 个业务实体。原 1,200 条访谈、4,141 条声明、4,425 条事件保持不变。
SQL 与 Neo4j 的 8 条产品路径按实体 ID 完全一致。示例目录新增的品牌归属和卖点功能映射均为明确标注的虚构演示数据。

尚未完整实施：独立的 ConsumerProfileSnapshot 历史表、完整双时态事实、独立 InsightEvidence 关系表、
三级需求分类全量字典、pgvector 检索、所有 R14–R18 事件关系的查询接口，以及企业审核与权限治理。
当前 InsightArtifact 保留报告、证据引用与工具快照；这些能力不能等同于规范全部验收完成。
