import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import Entity, Relation, Outbox

log = logging.getLogger(__name__)

class GraphProjector:
    def __init__(self):
        from app.neo4j_connection import get_graph_driver
        self.driver = get_graph_driver()

    def close(self):
        # The process-owned connection pool is closed at application/worker shutdown.
        pass

    def ensure_schema(self):
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT kg_entity_id_unique IF NOT EXISTS FOR (n:KGEntity) REQUIRE n.id IS UNIQUE").consume()
            session.run("CREATE INDEX kg_tenant_type IF NOT EXISTS FOR (n:KGEntity) ON (n.tenant_id, n.entity_type)").consume()

    def project_many(self, db, items, reconcile_tenant=None):
        from collections import defaultdict
        from app.graph_policy import entity_allowed, node_record, edge_record
        nodes, edges, excluded = {}, [], []
        for item in items:
            if item.kind == 'entity':
                entity = db.get(Entity, item.payload['id'])
                if entity and entity.tenant_id == item.tenant_id and entity_allowed(entity):
                    nodes[entity.id] = node_record(entity)
            elif item.kind == 'relation':
                relation = db.get(Relation, item.payload['id'])
                if not relation or relation.tenant_id != item.tenant_id:
                    continue
                src, dst = db.get(Entity, relation.src_id), db.get(Entity, relation.dst_id)
                record = edge_record(relation, src, dst)
                if record:
                    edges.append(record)
                    # Endpoint projection is idempotent and avoids multi-worker ordering loss.
                    nodes[src.id], nodes[dst.id] = node_record(src), node_record(dst)
                else:
                    excluded.append({'tenant': item.tenant_id, 'id': relation.id})
        node_groups, edge_groups = defaultdict(list), defaultdict(list)
        for node in nodes.values():
            node_groups[node['label']].append(node)
        for edge in edges:
            edge_groups[edge['kind']].append(edge)
        with self.driver.session() as session, session.begin_transaction() as tx:
            if reconcile_tenant is not None:
                tx.run("MATCH (n:KGEntity {tenant_id:$tenant}) WHERE NOT n.id IN $ids DETACH DELETE n",
                       tenant=reconcile_tenant, ids=list(nodes)).consume()
                tx.run("MATCH (a:KGEntity {tenant_id:$tenant})-[r]->(b:KGEntity {tenant_id:$tenant}) "
                       "WHERE type(r)='KG_REL' OR r.projection_version IS NOT NULL DELETE r",
                       tenant=reconcile_tenant).consume()
            for label, rows in node_groups.items():
                # Label and relationship types come exclusively from graph_policy allowlists.
                tx.run(f"UNWIND $rows AS row MERGE (n:KGEntity {{id:row.id}}) SET n:{label} "
                       "SET n = {id:row.id, entity_id:row.id, tenant_id:row.tenant, entity_type:row.type, "
                       "ontology_type:row.label, name:row.name, canonical_key:row.key, "
                       "status:row.status, ontology_version:row.ontology_version, "
                       "projection_version:row.projection_version, synthetic:row.synthetic, "
                       "created_at:row.created_at}", rows=rows).consume()
            if excluded:
                tx.run("UNWIND $rows AS row MATCH (a:KGEntity {tenant_id:row.tenant})-[r]->"
                       "(b:KGEntity {tenant_id:row.tenant}) WHERE r.id=row.id DELETE r", rows=excluded).consume()
            for kind, rows in edge_groups.items():
                tx.run("UNWIND $rows AS row MATCH (a:KGEntity {tenant_id:row.tenant})-[r:KG_REL]->"
                       "(b:KGEntity {tenant_id:row.tenant}) WHERE r.id=row.id DELETE r", rows=rows).consume()
                result = tx.run("UNWIND $rows AS row MATCH (a:KGEntity {id:row.src, tenant_id:row.tenant}), "
                                "(b:KGEntity {id:row.dst, tenant_id:row.tenant}) "
                                f"MERGE (a)-[r:{kind} {{id:row.id}}]->(b) "
                                "SET r.kind=row.kind, r.source_kind=row.source_kind, r.tenant_id=row.tenant, "
                                "r.confidence=row.confidence, r.ontology_version=row.ontology_version, "
                                "r.projection_version=row.projection_version, r.source_type=row.source_type "
                                "RETURN count(r) AS projected", rows=rows).single()
                if result['projected'] != len(rows):
                    raise RuntimeError('Graph projection is missing relation endpoints')
            tx.commit()

    def project(self, db, item):
        self.project_many(db, [item])


def drain_outbox(batch=100, tenant=None):
    if not settings.neo4j_enabled: return {"status": "disabled", "processed": 0}
    projector = GraphProjector(); count = 0; errors = 0
    try:
        with SessionLocal() as db:
            # Single worker recommended for this minimal projector; production multi-worker requires SKIP LOCKED claiming.
            query = select(Outbox).where(Outbox.processed_at.is_(None), Outbox.attempts < 10)
            if tenant is not None:
                query = query.where(Outbox.tenant_id == tenant)
            items = db.scalars(query.order_by(Outbox.created_at, Outbox.id).limit(batch).with_for_update(skip_locked=True)).all()
            if items:
                try:
                    projector.project_many(db, items)
                    for item in items:
                        item.processed_at = datetime.now(timezone.utc)
                        item.last_error = None
                    db.commit()
                    return {"processed": len(items), "errors": 0}
                except Exception:
                    # Fall back to individual records to isolate a failing task.
                    log.warning("batch projection failed; isolating individual records")
            for item in items:
                try:
                    projector.project(db, item)
                    item.processed_at = datetime.now(timezone.utc); item.last_error = None; count += 1
                except Exception as exc:
                    item.attempts += 1; item.last_error = str(exc)[:2000]; errors += 1
                    log.exception("projection failed for outbox item %s", item.id)
                    # Stop to preserve entity-before-relation ordering.
                    break
            db.commit()
    finally: projector.close()
    return {"processed": count, "errors": errors}
