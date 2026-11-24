from sqlalchemy import select

from app import graph
from app.config import settings
from app.db import SessionLocal
from app.models import Outbox


def test_failed_projection_stays_pending_and_retry_is_tenant_scoped(client, monkeypatch):
    for tenant in ('a', 'b'):
        response = client.post('/v1/entities', headers={'X-Tenant-Id': tenant},
                               json={'entity_type': 'Need', 'canonical_key': 'battery', 'name': 'Battery'})
        assert response.status_code == 200
    monkeypatch.setattr(settings, 'neo4j_enabled', True)

    class UnavailableProjector:
        def project_many(self, db, items):
            raise RuntimeError('endpoint unavailable')

        def project(self, db, item):
            raise RuntimeError('endpoint unavailable')

        def close(self):
            pass

    monkeypatch.setattr(graph, 'GraphProjector', UnavailableProjector)
    assert graph.drain_outbox(tenant='a') == {'processed': 0, 'errors': 1}
    with SessionLocal() as db:
        a = db.scalar(select(Outbox).where(Outbox.tenant_id == 'a'))
        b = db.scalar(select(Outbox).where(Outbox.tenant_id == 'b'))
        assert a.processed_at is None and a.attempts == 1 and a.last_error
        assert b.processed_at is None and b.attempts == 0

    class RecoveredProjector:
        def project_many(self, db, items):
            assert len(items) == 1 and items[0].tenant_id == 'a'

        def project(self, db, item):
            raise AssertionError('successful batch should not fall back')

        def close(self):
            pass

    monkeypatch.setattr(graph, 'GraphProjector', RecoveredProjector)
    assert graph.drain_outbox(tenant='a') == {'processed': 1, 'errors': 0}
    with SessionLocal() as db:
        a = db.scalar(select(Outbox).where(Outbox.tenant_id == 'a'))
        b = db.scalar(select(Outbox).where(Outbox.tenant_id == 'b'))
        assert a.processed_at is not None and a.last_error is None
        assert b.processed_at is None and b.attempts == 0
