from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.models import Entity, Relation, Evidence, Claim, InteractionEvent, Segment, Outbox
from app.ontology import validate_relation, load_ontology

ONTOLOGY = load_ontology()

def fail(code, message): raise HTTPException(code, detail=message)
def owned(db, cls, tenant, ident):
    obj = db.get(cls, ident)
    if not obj or obj.tenant_id != tenant: fail(404, "resource not found")
    return obj

def entity_upsert(db, tenant, data):
    if data.entity_type not in ONTOLOGY["entity_types"]: fail(422, "unknown entity_type")
    obj = db.scalar(select(Entity).where(Entity.tenant_id == tenant, Entity.entity_type == data.entity_type, Entity.canonical_key == data.canonical_key))
    if obj: return obj
    values = data.model_dump()
    values["attrs"].setdefault("ontology_version", ONTOLOGY["version"])
    values["attrs"].setdefault("status", "ACTIVE")
    obj = Entity(tenant_id=tenant, **values)
    db.add(obj); db.flush()
    from app.graph_policy import entity_allowed
    if entity_allowed(obj):
        db.add(Outbox(tenant_id=tenant, kind="entity", payload={"id": obj.id}))
    return obj

def relation_upsert(db, tenant, data):
    src = owned(db, Entity, tenant, data.src_id)
    dst = owned(db, Entity, tenant, data.dst_id)
    if not validate_relation(ONTOLOGY, src.entity_type, data.relation_type, dst.entity_type): fail(422, "ontology relation domain/range mismatch")
    from app.graph_policy import relation_kind
    canonical = data.relation_type
    aliases = [canonical]
    if src.entity_type == "Feature" and dst.entity_type == "Need" and canonical in ("ADDRESSES", "SUPPORTS"):
        canonical, aliases = "SUPPORTS", ["SUPPORTS", "ADDRESSES"]
    if src.entity_type in ("Product", "ProductModel", "ProductVariant") and canonical in ("COMMUNICATES", "PROMOTES"):
        canonical, aliases = "PROMOTES", ["PROMOTES", "COMMUNICATES"]
    obj = db.scalar(select(Relation).where(Relation.tenant_id == tenant, Relation.src_id == src.id,
                    Relation.dst_id == dst.id, Relation.relation_type.in_(aliases))
                    .order_by((Relation.relation_type == canonical).desc()).limit(1))
    if obj:
        if obj.relation_type != canonical:
            obj.relation_type = canonical
            db.flush()
            if relation_kind(obj, src, dst):
                db.add(Outbox(tenant_id=tenant, kind="relation", payload={"id": obj.id}))
        return obj
    values = data.model_dump()
    values['relation_type'] = canonical
    obj = Relation(tenant_id=tenant, **values); db.add(obj); db.flush()
    if relation_kind(obj, src, dst):
        db.add(Outbox(tenant_id=tenant, kind="relation", payload={"id": obj.id}))
    return obj

def evidence_upsert(db, tenant, data):
    obj = db.scalar(select(Evidence).where(Evidence.tenant_id == tenant, Evidence.source_id == data.source_id, Evidence.excerpt == data.excerpt))
    if obj: return obj
    obj = Evidence(tenant_id=tenant, source_id=data.source_id, source_type=data.source_type, excerpt=data.excerpt, language=data.language, metadata_=data.metadata)
    db.add(obj); db.flush(); return obj

def claim_upsert(db, tenant, data):
    owned(db, Evidence, tenant, data.evidence_id)
    src = owned(db, Entity, tenant, data.subject_id)
    dst = owned(db, Entity, tenant, data.object_id)
    if not validate_relation(ONTOLOGY, src.entity_type, data.predicate, dst.entity_type): fail(422, "invalid claim predicate")
    obj = db.scalar(select(Claim).where(Claim.tenant_id == tenant, Claim.evidence_id == data.evidence_id, Claim.subject_id == src.id, Claim.predicate == data.predicate, Claim.object_id == dst.id))
    if obj: return obj
    obj = Claim(tenant_id=tenant, **data.model_dump()); db.add(obj); db.flush(); return obj

def insights(db, tenant, country=None, age_min=None, age_max=None, min_confidence=0.0, limit=20):
    # SQL source of truth; no graph availability required. Evidence counts are NOT independent consumer counts.
    consumers = db.scalars(select(Entity).where(Entity.tenant_id == tenant, Entity.entity_type == "Consumer")).all()
    allowed = {x.id for x in consumers if (country is None or x.attrs.get("country", "").casefold() == country.casefold()) and (age_min is None or isinstance(x.attrs.get("age"), int) and x.attrs["age"] >= age_min) and (age_max is None or isinstance(x.attrs.get("age"), int) and x.attrs["age"] <= age_max)}
    if not allowed: return {"sample_size": 0, "needs": [], "selling_points": [], "caveat": "descriptive sample, not population inference"}
    rows = db.execute(select(Claim, Entity, Evidence).join(Entity, Claim.object_id == Entity.id).join(Evidence, Claim.evidence_id == Evidence.id).where(Claim.tenant_id == tenant, Claim.subject_id.in_(allowed), Claim.status == "accepted", Claim.confidence >= min_confidence, Claim.predicate.in_(["HAS_NEED", "RESPONDS_TO"]))).all()
    buckets = {"HAS_NEED": {}, "RESPONDS_TO": {}}
    for claim, obj, evidence in rows:
        k = (obj.id, obj.name)
        bucket = buckets[claim.predicate].setdefault(k, {"id": obj.id, "name": obj.name, "consumers": set(), "evidence_ids": set(), "confidence_sum": 0.0, "claim_count": 0})
        bucket["consumers"].add(claim.subject_id); bucket["evidence_ids"].add(evidence.id)
        bucket["confidence_sum"] += claim.confidence; bucket["claim_count"] += 1
    def render(d):
        out = []
        for b in d.values():
            out.append({"id": b["id"], "name": b["name"], "consumer_count": len(b["consumers"]), "evidence_count": len(b["evidence_ids"]), "mean_claim_confidence": round(b["confidence_sum"] / b["claim_count"], 3), "evidence_ids": sorted(b["evidence_ids"])[:20]})
        return sorted(out, key=lambda x: (-x["consumer_count"], x["name"]))[:limit]
    return {"sample_size": len(allowed), "needs": render(buckets["HAS_NEED"]), "selling_points": render(buckets["RESPONDS_TO"]), "caveat": "descriptive sample; multiple claims per consumer are deduplicated; not causal or representative"}
