"""Back up and atomically reconcile one tenant's managed static Neo4j projection.

SQL registry, claims, evidence, events and analysis artifacts are never deleted.
Usage: python -m scripts.reconcile_static_graph --tenant synthetic-demo
"""
import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.graph import GraphProjector
from app.graph_policy import catalog, storage_description
from app.models import Outbox


def reconcile(tenant, backup_dir=None, dry_run=False):
    with SessionLocal() as db:
        entities, edges = catalog(db, tenant, include_consumers=True)
        pending_ids = list(db.scalars(select(Outbox.id).where(Outbox.tenant_id == tenant, Outbox.processed_at.is_(None))))
        expected = {'nodes': len(entities), 'static_edges': len(edges)}
        if dry_run:
            return {**expected, 'storage': storage_description(), 'dry_run': True}
        if not settings.neo4j_enabled:
            raise RuntimeError('Neo4j is disabled')
        projector = GraphProjector()
        folder = Path(backup_dir) if backup_dir else Path(__file__).resolve().parents[1] / 'data' / 'graph_backups'
        folder.mkdir(parents=True, exist_ok=True)
        with projector.driver.session() as session:
            nodes = session.run('MATCH (n:KGEntity {tenant_id:$t}) RETURN properties(n) AS properties, labels(n) AS labels', t=tenant).data()
            relations = session.run('MATCH (a:KGEntity {tenant_id:$t})-[r]->(b:KGEntity {tenant_id:$t}) RETURN a.id AS source, b.id AS target, type(r) AS type, properties(r) AS properties', t=tenant).data()
        # Use a random local filename; tenant identifiers never become filesystem paths.
        with tempfile.NamedTemporaryFile('w', prefix='consumer-kg-projection-', suffix='.json',
                                          dir=folder, encoding='utf-8', delete=False) as f:
            json.dump({'tenant': tenant, 'created_at': datetime.now(timezone.utc).isoformat(),
                       'nodes': nodes, 'relations': relations}, f, ensure_ascii=False, default=str)
            backup = f.name
        projector.ensure_schema()
        items = [SimpleNamespace(kind='entity', tenant_id=tenant, payload={'id': eid}) for eid in entities]
        items.extend(SimpleNamespace(kind='relation', tenant_id=tenant, payload={'id': e['id']}) for e in edges)
        projector.project_many(db, items, reconcile_tenant=tenant)
        with projector.driver.session() as session:
            actual_nodes = set(session.run('MATCH (n:KGEntity {tenant_id:$t}) RETURN n.id AS id', t=tenant).value('id'))
            actual_edges = set(session.run('MATCH (a:KGEntity {tenant_id:$t})-[r]->(b:KGEntity {tenant_id:$t}) WHERE r.projection_version=$policy RETURN r.id AS id', t=tenant, policy=storage_description()['projection_version']).value('id'))
        if actual_nodes != set(entities) or actual_edges != {e['id'] for e in edges}:
            raise RuntimeError('Projection ID verification failed; SQL data is intact and backup is available at '+backup)
        for item in db.scalars(select(Outbox).where(Outbox.tenant_id == tenant, Outbox.id.in_(pending_ids), Outbox.processed_at.is_(None))):
            item.processed_at, item.last_error = datetime.now(timezone.utc), None
        db.commit()
        return {**expected, 'previous_nodes': len(nodes), 'previous_edges': len(relations),
                'backup': backup, 'verified': True, 'dynamic_data_store': 'PostgreSQL'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--tenant', required=True)
    p.add_argument('--backup-dir')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    print(json.dumps(reconcile(args.tenant, args.backup_dir, args.dry_run), ensure_ascii=False, indent=2))
