# V4 工程实施与验收说明

> 本文为早期 V4 交付记录。当前静态图谱与动态数据的分层、真实关系类型、连接修复和前端图谱浏览，以 [README 当前说明](../README.md#按领域设计规范分层与展示图结构) 为准；旧 `KG_REL` 描述不再代表现行投影策略。

## 交付边界

V4 基于 V3 增量扩展：保留原 API、访谈抽取、证据/声明/图谱 outbox、合成数据与问答；新增机会发现、别名治理、审核、审计、图谱重建、语言分组评测、迁移与虚构产品目录。

**状态区分**：本地 SQLite 单元/API 测试通过；未在本次执行中验证真实 PostgreSQL + Neo4j + LLM 端到端、压测、故障注入或真实访谈人工评测。不能将其称为已经验收的生产系统。

## 环境与配置

`.env.example` 列出 `DATABASE_URL`, `NEO4J_ENABLED`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `LLM_ENABLED`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `API_KEY`, `ADMIN_API_KEY`。

生产部署需使用秘密管理服务注入密码、TLS、私网和反向代理；不允许以默认开发密码公开数据库。真实 LLM 接口需要兼容 OpenAI chat completions JSON 输出。

## 首次部署

```bash
cp .env.example .env
# 配置 API_KEY、ADMIN_API_KEY、POSTGRES_PASSWORD、NEO4J_PASSWORD 等
# Docker compose 的 POSTGRES_PASSWORD 和 NEO4J_PASSWORD 从 .env 读取
docker compose up -d --build
# 迁移由 migrate 容器自动运行
# 可选：加载虚构产品目录
docker compose exec api python -m scripts.seed_catalog_v4
# 导入 JSONL，默认规则模式
docker compose exec api python -m scripts.batch_ingest_v4 data/synthetic/interviews.jsonl --mode rules
```

本地：

```bash
pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
python -m scripts.seed_catalog_v4
uvicorn app.main:app --reload
pytest -q
```

## 主要接口

| 接口 | 方法 | 用途 |
|---|---|---|
| `/v1/knowledge/interviews` | POST | 单条访谈抽取与持久化 |
| `/v1/qa/ask` | POST | 有证据的受限问答 |
| `/v1/opportunities?country=PH&age_min=26&age_max=30` | GET | 多跳需求-功能-产品发现 |
| `/v1/governance/reviews` | GET | 待审核抽取 |
| `/v1/governance/reviews/{id}/decision` | POST | 审核批准/拒绝 |
| `/v1/governance/aliases` | POST | 登记实体别名 |
| `/v1/admin/graph/rebuild` | POST | 从 SQL 重排图谱投影任务 |
| `/v1/admin/outbox/stats` | GET | 图谱积压/死信统计 |

普通接口使用 `X-Tenant-Id`、`X-API-Key`；管理员接口额外使用 `X-Admin-Key`。在生产环境需由 API 网关统一做租户身份绑定、OIDC/JWT、限流及访问审计；当前租户头本身不构成可信身份认证。

## 图谱语义

`Consumer -HAS_NEED-> Need <-ADDRESSES- Feature <-HAS_FEATURE- ProductModel`；
`Need <-ADDRESSES- SellingPoint <-COMMUNICATES- ProductModel`。

机会分数使用去重消费者人数与样本内比例，**不是**购买因果效应、需求预测或产品成功概率。产品目录是虚构的，不得作为实际竞品规格。

## 关键限制与下一步生产硬化

1. **数据源**：真实访谈的脱敏、同意与授权、PII 识别、保留期限、删除传播尚需按部署地区落实。
2. **LLM**：接口已预留，未在真实供应商上验证 JSON schema 严格输出、模型变更兼容、长文本切分、速率限制、成本上限、提示注入红队评测。
3. **融合**：当前别名映射是受治理的字典登记；完整跨实体合并/回滚、相似度候选召回与审批工作流尚未实现，不能直接自动合并历史实体。
4. **图谱投影**：使用 SQL Outbox 和 PostgreSQL SKIP LOCKED 领取；需要多 worker 故障注入验证、失败重试退避、告警、投影一致性核对。图关系是统一 `KG_REL` 类型，`kind` 保存语义关系类型。
5. **迁移**：初始 Alembic 迁移适用于新部署；升级已在使用的 V3 PostgreSQL 库前需备份、检查差异并演练迁移。生产环境不允许自动 `create_all`。
6. **权限**：目前 API Key + 管理员 Key 为基础方案，未实现企业 SSO、细粒度 RBAC、请求级审计和数据行级安全策略。
7. **可用性**：尚未进行多实例部署、HA、灾备演练、SLO、负载测试、K8s 配置、TLS 与供应链扫描。
8. **统计**：需引入抽样权重、置信区间、偏差评估、独立真实数据验证，才可支持市场决策。

## 推荐生产验收门槛

- 真实标注集按语言、国家、意图、否定表达分层，评测 Precision/Recall/F1 与误合并率。
- 图谱投影断网恢复、重复消息、并发消费、死信重放、重建一致性全部通过。
- 多租户越权、敏感字段泄露、密钥轮换、提示注入测试通过。
- 在目标部署规模下实测 P95 延迟、吞吐、错误率与成本；设定明确 SLO。
- 完成数据库迁移回滚、备份恢复、日志脱敏及审计追溯。
