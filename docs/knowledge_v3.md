# V3：多语言知识抽取、实体融合、图谱关系与证据问答

## 运行验证

```bash
pip install -e '.[dev]'
pytest -q
DATABASE_URL=sqlite:///./knowledge_v3.db python -m scripts.knowledge_batch --input data/synthetic/interviews.jsonl --limit 1200
DATABASE_URL=sqlite:///./knowledge_v3.db uvicorn app.main:app --port 8000
python -m scripts.evaluate_knowledge
```

已随包提供 `data/knowledge_v3.db`（1200 条合成访谈导入后的数据）。数据库文件中所有消费者均为虚构对象。

## 新接口

### POST /v1/knowledge/interviews

```json
{"source_id":"example-001","consumer_key":"c-001","country":"Philippines","age":28,"language":"en","excerpt":"I need battery lasts all day and clear low-light photos.","synthetic":true,"mode":"rules"}
```

将 `mode` 改为 `llm`，需在 `.env` 中配置 `LLM_ENABLED=true`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。服务应支持 OpenAI 兼容的 `/chat/completions` API。LLM 输出必须通过 Pydantic 结构校验、原文逐字引用检查、闭集实体链接和置信度门槛，才会进入事实表。无法验证的内容返回 `review`，不会自动写入正向关系。LLM 模式尚未在真实服务上验证。

### POST /v1/qa/ask

```json
{"question":"2026年菲律宾26-30岁消费者购机需求是什么？","top_k":5,"evidence_limit":3}
```

响应包含：筛选条件、样本量、需求/卖点去重人数、证据引用 ID、源文、合成数据标志与统计限制。没有充分筛选条件时拒绝自由查询，避免大规模未限定扫描。

## 核心数据链

`interview -> mention -> evidence alignment -> canonical link -> Evidence + Claim + Entity + Relation -> SQL Outbox -> Neo4j projector -> grounded QA`

PostgreSQL/SQLite 为主数据源，Neo4j 是异步投影；即使 Neo4j 不可用，SQL 侧问答仍可运行。现有投影 Worker 是单实例顺序处理实现，不具备多 Worker 的 `SKIP LOCKED`、死信队列与投影重建保证。请勿直接宣称它已满足生产级高可用。

## 关键限制和下一步

1. 当前规则基线使用闭集词典；长访谈、隐喻、复杂否定、多实体指代需真实 LLM 评测和人工标注集。规则会出现上下文误报（如场景描述被当作购机需求）。
2. 目前 canonical linking 是精确别名匹配，未完成向量候选召回、跨语言嵌入、实体合并审批/撤销及别名版本管理。
3. 对同一受访者的冲突声明，当前保留证据但尚无完整的冲突裁决工作流。`quote` 是精确子串，尚未持久化字符偏移。
4. 卖点不从需求自动推断：只有访谈明确提到的卖点才会建 `RESPONDS_TO`，避免把推测误当作事实。因此新抽取数据库中的卖点覆盖率可能很低。
5. 现有问答是限定国家/年龄的确定性统计模板，不是开放域 GraphRAG；复杂多跳问答、时间筛选、跨市场差异及统计显著性仍需后续实现。
6. 生产环境需完成数据库迁移、异步队列与任务幂等、角色权限、敏感信息脱敏、租户隔离审计、可观测性、限流及备份恢复演练。
7. 合成数据不能支持任何真实市场的统计结论；所有测试指标仅针对模板生成数据。

## 合成数据测试结果

`python -m scripts.evaluate_knowledge`：正向需求抽取 TP=2250、FP=217、FN=0，Precision=0.912、Recall=1.0、F1=0.954。该指标仅衡量同分布合成模板，不能外推到真实访谈。
