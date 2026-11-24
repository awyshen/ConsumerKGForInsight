"""Human-in-the-loop review, alias governance and reproducible graph projection."""
from datetime import datetime, timezone
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from app.models import AliasMapping, AuditEvent, Claim, Entity, Outbox, Relation, ReviewTask
from app.knowledge_pipeline import norm
from app.services import owned


def audit(db, tenant, actor, action, target, details=None):
    db.add(AuditEvent(tenant_id=tenant, actor=actor, action=action, target_id=target, details=details or {}))


def set_alias(db, tenant, actor, entity_type, alias, entity_id):
    entity = owned(db, Entity, tenant, entity_id)
    if entity.entity_type != entity_type: raise ValueError("alias target type mismatch")
    key = norm(alias)
    if len(key) < 2: raise ValueError("alias too short")
    row = db.scalar(select(AliasMapping).where(AliasMapping.tenant_id == tenant,
                    AliasMapping.entity_type == entity_type, AliasMapping.normalized_alias == key))
    if row and row.canonical_entity_id != entity_id:
        raise ValueError("alias conflict requires explicit resolution")
    if row: return row
    row = AliasMapping(tenant_id=tenant, entity_type=entity_type, normalized_alias=key,
                       canonical_entity_id=entity_id)
    db.add(row); db.flush()
    audit(db, tenant, actor, "alias.created", row.id, {"entity_id": entity_id, "alias": key})
    return row


def review_decide(db, tenant, actor, review_id, decision):
    task = owned(db, ReviewTask, tenant, review_id)
    if task.status != "pending": raise ValueError("review already decided")
    if decision not in ("approved", "rejected"): raise ValueError("invalid decision")
    # Approval records adjudication; does not fabricate a claim without verified evidence.
    task.status = decision
    task.reviewer = actor
    task.decided_at = datetime.now(timezone.utc)
    audit(db, tenant, actor, "review." + decision, task.id)
    return task


def enqueue_rebuild(db, tenant, actor):
    # Rebuild only the static projection; dynamic facts stay in SQL.
    from app.graph_policy import catalog, entity_allowed
    registry, edges = catalog(db, tenant, include_consumers=True)
    entities = list(registry.values())
    ids = [e["id"] for e in edges]
    relations = db.scalars(select(Relation).where(Relation.tenant_id == tenant, Relation.id.in_(ids))).all()
    for kind, rows in (("entity", entities), ("relation", relations)):
        for row in rows: db.add(Outbox(tenant_id=tenant, kind=kind, payload={"id": row.id}))
    audit(db, tenant, actor, "graph.rebuild.queued", tenant, {"entities": len(entities), "relations": len(relations)})
    return {"entities": len(entities), "relations": len(relations)}
