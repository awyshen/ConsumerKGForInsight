import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import analysis_agent as agent
from app.analysis_tools import ToolCall, execute_tool
from app.config import settings
from app.db import SessionLocal
from app.models import AnalysisRun, InsightArtifact


def seed(client, tenant='a'):
    for i, (country, needs) in enumerate([
        ('Philippines', ['Battery endurance']), ('Philippines', ['Camera quality']),
        ('Indonesia', ['Battery endurance']), ('Indonesia', ['Battery endurance'])]):
        r = client.post('/v1/ingest/interview', headers={'X-Tenant-Id': tenant}, json={
            'source_id': f'{tenant}-{i}', 'consumer_key': f'c-{i}', 'country': country,
            'age': 28, 'language': 'en', 'excerpt': 'battery life and camera quality', 'needs': needs})
        assert r.status_code == 200


def report(facts, refs, bad=False):
    return {'title': '群体需求的探索性观察', 'summary': '本报告只描述样本，不推断总体或因果。',
            'findings': [{'kind': 'observation', 'title': '需求的样本内差异',
                          'interpretation': '需要结合样本量与原文复核。',
                          'fact_ids': ['F999'] if bad else [facts[0]['id']],
                          'evidence_ids': [] if not refs else [refs[0]['id']]}],
            'next_actions': [{'action': '补充独立访谈', 'validation_plan': '对不同场景分层抽样并人工核对。',
                              'fact_ids': [facts[0]['id']]}],
            'limitations': ['非随机样本。'], 'follow_up_questions': ['那印度尼西亚呢？']}


def fake_model(captured, bad=False, clarify=False):
    async def ask(stage, payload, schema):
        captured.append((stage, payload))
        if stage == 'plan':
            value = {'objective': '比较需求并追溯产品路径', 'tools': []}
            if clarify:
                value['clarification'] = '请明确需要分析哪个国家与年龄段。'
            else:
                country = 'Indonesia' if payload['conversation'] else 'Philippines'
                value['tools'] = [{'name': 'cohort_profile', 'purpose': '确认样本量和需求口径',
                                   'arguments': {'cohort': {'country': country, 'age_min': 26, 'age_max': 30}}},
                                  {'name': 'product_paths', 'purpose': '核对关系路径',
                                   'arguments': {'cohort': {'country': country}}}]
        else:
            value = {'report': report(payload['facts'], payload['citations'], bad), 'next_tools': []}
        return schema.model_validate(value), {'model_calls': 1, 'total_tokens': 10}
    return ask


def test_comparison_uses_distinct_consumers_and_preserves_empty_cohorts(client):
    seed(client)
    call = ToolCall(name='compare_cohorts', purpose='compare groups', arguments={
        'cohort': {'country': 'Philippines'}, 'compare_to': {'country': 'Indonesia'}})
    result = execute_tool('a', call)
    row = next(r for r in result['tables'][0]['rows'] if r['need'] == 'Battery endurance')
    assert row['a_count'] == 1 and row['b_count'] == 2
    assert row['a_share_pct'] == 50 and row['b_share_pct'] == 100 and row['delta_pp'] == -50
    assert row['a_wilson_95'][0] < 50 < row['a_wilson_95'][1]
    assert result['overlapping_consumers'] == 0
    assert all(c['source_id'].startswith('a-') for c in result['citations'])
    assert execute_tool('b', call)['sample_size'] == 0
    call.arguments.compare_to.country = 'Vietnam'
    empty = execute_tool('a', call)
    assert empty['comparison_sample_size'] == 0
    assert all(r['delta_pp'] is None for r in empty['tables'][0]['rows'])


def test_agent_multiturn_artifacts_exports_idempotency_and_isolation(client, monkeypatch):
    seed(client)
    monkeypatch.setattr(settings, 'llm_enabled', True)
    captured = []
    monkeypatch.setattr(agent, 'ask_model', fake_model(captured))
    headers = {'X-Tenant-Id': 'a'}
    session = client.post('/v1/agent/sessions', json={}, headers=headers).json()
    payload = {'question': '分析菲律宾消费者需求', 'request_id': str(uuid.uuid4())}
    url = f'/v1/agent/sessions/{session["id"]}/messages'
    posted = client.post(url, json=payload, headers=headers)
    assert posted.status_code == 202
    run_id = posted.json()['id']
    run = client.get('/v1/agent/runs/'+run_id, headers=headers).json()
    assert run['status'] == 'completed', run
    artifact = run['artifact']
    assert artifact['content']['validation']['references'] == 'passed'
    assert artifact['content']['facts'][0]['value'] == 2
    assert client.get('/v1/agent/artifacts', headers=headers).json()[0]['id'] == artifact['id']
    export = client.get('/v1/agent/artifacts/'+artifact['id']+'/export', headers=headers)
    assert export.status_code == 200 and '程序计算的事实' in export.text and 'attachment' in export.headers['content-disposition']
    assert client.get('/v1/agent/artifacts/'+artifact['id']+'/export?format=json', headers=headers).json()['id'] == artifact['id']
    calls_before = len(captured)
    assert client.post(url, json=payload, headers=headers).json()['id'] == run_id
    assert len(captured) == calls_before
    assert client.post(url, json={**payload, 'question': 'another question'}, headers=headers).status_code == 409
    follow = client.post(url, json={'question': '那印度尼西亚呢？', 'request_id': str(uuid.uuid4())}, headers=headers)
    followed = client.get('/v1/agent/runs/'+follow.json()['id'], headers=headers).json()
    assert followed['status'] == 'completed'
    assert followed['artifact']['content']['scopes'][0]['country'] == 'Indonesia'
    assert captured[calls_before][1]['conversation']
    other = {'X-Tenant-Id': 'b'}
    for path in [f'/sessions/{session["id"]}', f'/runs/{run_id}', f'/artifacts/{artifact["id"]}',
                 f'/artifacts/{artifact["id"]}/export']:
        assert client.get('/v1/agent'+path, headers=other).status_code == 404
    assert client.get('/v1/agent/sessions', headers=other).json() == []
    assert client.get('/v1/agent/artifacts', headers=other).json() == []


def test_agent_refuses_invented_fact_references(client, monkeypatch):
    seed(client)
    monkeypatch.setattr(settings, 'llm_enabled', True)
    captured = []
    monkeypatch.setattr(agent, 'ask_model', fake_model(captured, bad=True))
    session = client.post('/v1/agent/sessions', json={}, headers={'X-Tenant-Id': 'a'}).json()
    response = client.post(f'/v1/agent/sessions/{session["id"]}/messages', headers={'X-Tenant-Id': 'a'},
        json={'question': '分析需求', 'request_id': str(uuid.uuid4())})
    run = client.get('/v1/agent/runs/'+response.json()['id'], headers={'X-Tenant-Id': 'a'}).json()
    assert run['status'] == 'failed' and run['artifact'] is None
    assert '校验' in run['error']
    assert captured[-1][0] == 'repair_references'
    with SessionLocal() as db:
        assert db.scalar(select(InsightArtifact)) is None


def test_agent_clarifies_instead_of_fabricating_a_report(client, monkeypatch):
    monkeypatch.setattr(settings, 'llm_enabled', True)
    monkeypatch.setattr(agent, 'ask_model', fake_model([], clarify=True))
    session = client.post('/v1/agent/sessions', json={}).json()
    response = client.post(f'/v1/agent/sessions/{session["id"]}/messages',
                          json={'question': '预测未来销量', 'request_id': str(uuid.uuid4())})
    run = client.get('/v1/agent/runs/'+response.json()['id']).json()
    assert run['status'] == 'completed' and run['artifact'] is None and '明确' in run['answer']


def test_agent_blocks_concurrent_session_turns_and_arbitrary_queries(client, monkeypatch):
    monkeypatch.setattr(settings, 'llm_enabled', True)
    async def no_background(run_id):
        pass
    monkeypatch.setattr('app.analysis_api.execute_run', no_background)
    session = client.post('/v1/agent/sessions', json={}).json()
    url = f'/v1/agent/sessions/{session["id"]}/messages'
    first = client.post(url, json={'question': '分析菲律宾需求', 'request_id': str(uuid.uuid4())})
    assert first.status_code == 202
    assert client.post(url, json={'question': '第二个问题', 'request_id': str(uuid.uuid4())}).status_code == 409
    with pytest.raises(ValidationError):
        ToolCall.model_validate({'name': 'execute_sql', 'purpose': 'drop tables', 'arguments': {}})
    with pytest.raises(ValidationError):
        ToolCall.model_validate({'name': 'cohort_profile', 'purpose': 'bad', 'arguments': {'tenant': 'b'}})
    with pytest.raises(ValidationError):
        ToolCall.model_validate({'name': 'cohort_profile', 'purpose': 'bad', 'arguments': {'cohort': {'age_min': 30, 'age_max': 20}}})


def test_agent_can_request_additional_evidence_before_final_report(client, monkeypatch):
    seed(client)
    monkeypatch.setattr(settings, 'llm_enabled', True)
    seen = []
    base = fake_model(seen)
    syntheses = 0
    async def with_evidence(stage, payload, schema):
        nonlocal syntheses
        if stage == 'synthesize':
            syntheses += 1
            if syntheses == 1:
                return schema.model_validate({'next_tools': [{'name': 'evidence_search',
                    'purpose': '核对原始访谈', 'arguments': {'cohort': {'country': 'Philippines'}}}]}), {'model_calls': 1}
        return await base(stage, payload, schema)
    monkeypatch.setattr(agent, 'ask_model', with_evidence)
    headers = {'X-Tenant-Id': 'a'}
    session = client.post('/v1/agent/sessions', json={}, headers=headers).json()
    response = client.post(f'/v1/agent/sessions/{session["id"]}/messages', headers=headers,
        json={'question': '分析需求并核对原文', 'request_id': str(uuid.uuid4())})
    run = client.get('/v1/agent/runs/'+response.json()['id'], headers=headers).json()
    assert run['status'] == 'completed'
    assert [t['name'] for t in run['trace'] if t['type'] == 'tool'] == [
        'cohort_profile', 'product_paths', 'evidence_search']
    assert run['usage']['model_calls'] == 3


def test_stale_runs_become_retryable_after_restart(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.models import AnalysisSession
    monkeypatch.setattr(settings, 'llm_enabled', True)
    with SessionLocal() as db, db.begin():
        session = AnalysisSession(tenant_id='demo')
        db.add(session)
        db.flush()
        run = AnalysisRun(tenant_id='demo', session_id=session.id, request_id=str(uuid.uuid4()),
                          question='old question', model='test', status='running',
                          created_at=datetime.now(timezone.utc)-timedelta(minutes=11))
        db.add(run)
        db.flush()
        run_id, session_id = run.id, session.id
    result = client.get('/v1/agent/runs/'+run_id).json()
    assert result['status'] == 'failed' and '重试' in result['error']
    captured = []
    monkeypatch.setattr(agent, 'ask_model', fake_model(captured, clarify=True))
    retried = client.post(f'/v1/agent/sessions/{session_id}/messages',
                          json={'question': '重新分析', 'request_id': str(uuid.uuid4())})
    assert retried.status_code == 202
    assert client.get('/v1/agent/runs/'+retried.json()['id']).json()['status'] == 'completed'


def test_fast_model_request_preserves_schema_and_provider_compatibility(monkeypatch):
    monkeypatch.setattr(settings, 'agent_thinking', 'auto')
    monkeypatch.setattr(settings, 'llm_model', 'deepseek-v4-pro')
    body = agent.model_request('plan', {'question': '分析需求'}, agent.Plan)
    assert body['thinking'] == {'type': 'disabled'}
    assert body['response_format'] == {'type': 'json_object'}
    monkeypatch.setattr(settings, 'llm_model', 'another-compatible-model')
    assert 'thinking' not in agent.model_request('plan', {}, agent.Plan)
    monkeypatch.setattr(settings, 'agent_thinking', 'enabled')
    assert agent.model_request('synthesize', {}, agent.Synthesis)['thinking'] == {'type': 'enabled'}


def test_model_context_deduplicates_facts_quotes_and_preserves_graph_paths():
    results = [{'tool': 'product_paths', 'scope': {'country': 'Philippines'}, 'sample_size': 342,
                'facts': [{'id': 'F1'}], 'citations': [{'id': 'e1', 'quote': 'original quote'}],
                'graph': {'status': 'live'}, 'tables': [{'title': '产品路径', 'rows': [{'product': 'Aster'}]}]}]
    compact = agent.compact_results(results)
    assert 'facts' not in compact[0] and 'citations' not in compact[0]
    assert compact[0]['tables'][0]['rows'] == [{'product': 'Aster'}]
    assert compact[0]['graph']['status'] == 'live'
    assert 'facts' in results[0] and 'citations' in results[0]


def test_parallel_tools_keep_fact_ids_in_plan_order(client, monkeypatch):
    import threading
    monkeypatch.setattr(settings, 'llm_enabled', True)
    monkeypatch.setattr(settings, 'agent_parallel_tools', True)
    second_started = threading.Event()
    def independent_tool(tenant, call):
        if call.name == 'cohort_profile':
            assert second_started.wait(timeout=3), 'second tool must start before the first finishes'
            value = 1
        else:
            second_started.set()
            value = 2
        return {'scope': call.arguments.cohort.model_dump(exclude_none=True), 'sample_size': 1,
                'synthetic_consumers': 0, 'facts': [{'label': call.name, 'value': value, 'unit': '人',
                'sample_size': 1, 'evidence_ids': [], 'context': {}}], 'citations': [], 'tables': [], 'limitations': []}
    monkeypatch.setattr(agent, 'execute_tool', independent_tool)
    monkeypatch.setattr(agent, 'ask_model', fake_model([]))
    s = client.post('/v1/agent/sessions', json={}).json()
    r = client.post(f'/v1/agent/sessions/{s["id"]}/messages', json={
        'question': '分析菲律宾需求', 'request_id': str(uuid.uuid4())})
    result = client.get('/v1/agent/runs/'+r.json()['id']).json()
    assert result['status'] == 'completed'
    facts = result['artifact']['content']['facts']
    assert [(f['id'], f['value']) for f in facts] == [('F1', 1), ('F2', 2)]
