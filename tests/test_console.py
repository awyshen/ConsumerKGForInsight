from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Claim, Evidence, InteractionEvent
from scripts.synthetic_pipeline import generate, load


def test_console_tenant_scope_search_and_evidence_detail(client):
    payload = {"source_id": "visible-source", "consumer_key": "sample", "country": "Philippines",
               "age": 28, "language": "en", "excerpt": "I need battery life.",
               "synthetic": True, "mode": "rules"}
    first = client.post('/v1/knowledge/interviews', json=payload, headers={'X-Tenant-Id': 'a'})
    assert first.status_code == 200
    evidence_id = first.json()['evidence_id']
    headers = {'X-Tenant-Id': 'a'}
    summary = client.get('/v1/console/summary', headers=headers).json()
    assert summary['consumers'] == summary['evidence'] == summary['claims'] == 1
    assert summary['synthetic_consumers'] == 1
    assert summary['countries'] == [{'name': 'Philippines', 'count': 1}]
    assert client.get('/v1/console/evidence?q=battery', headers=headers).json()['total'] == 1
    assert client.get('/v1/console/evidence?q=%25', headers=headers).json()['total'] == 0
    assert client.get('/v1/console/evidence?language=zh', headers=headers).json()['total'] == 0
    assert client.get('/v1/console/consumers?country=Vietnam', headers=headers).json()['total'] == 0
    assert client.get('/v1/console/evidence?page_size=101', headers=headers).status_code == 422
    detail = client.get('/v1/console/evidence/' + evidence_id, headers=headers).json()
    assert detail['claims'][0]['name'] == 'Battery endurance'
    assert client.get('/v1/console/summary', headers={'X-Tenant-Id': 'b'}).json()['consumers'] == 0
    assert client.get('/v1/console/evidence', headers={'X-Tenant-Id': 'b'}).json()['total'] == 0
    assert client.get('/v1/console/consumers', headers={'X-Tenant-Id': 'b'}).json()['total'] == 0
    assert client.get('/v1/console/evidence/' + evidence_id, headers={'X-Tenant-Id': 'b'}).status_code == 404


def test_console_api_requires_configured_key(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'api_key', 'test-console-key')
    assert client.get('/v1/console/summary').status_code == 401
    assert client.get('/v1/console/summary', headers={'X-API-Key': 'test-console-key'}).status_code == 200
    assert client.get('/').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/static/styles.css').status_code == 200


def test_synthetic_import_replay_preserves_facts_and_annotation_provenance(client, tmp_path):
    generate(5, 17, tmp_path)
    first = load(tmp_path, tenant='synthetic-demo')
    with SessionLocal() as db:
        def counts():
            return [db.scalar(select(func.count()).select_from(m)) for m in (Evidence, Claim, InteractionEvent)]
        before = counts()
    second = load(tmp_path, tenant='synthetic-demo')
    with SessionLocal() as db:
        after = [db.scalar(select(func.count()).select_from(m)) for m in (Evidence, Claim, InteractionEvent)]
        evidence = db.scalar(select(Evidence))
        assert evidence.metadata_['annotation_type'] == 'generated_ground_truth'
    assert before == after
    assert first['interviews'] == second['interviews'] == 5
    assert second.get('events', 0) == 0
