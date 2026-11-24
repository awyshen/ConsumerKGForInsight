"""Read-only, tenant-filtered data access for the bundled research console."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Claim, Entity, Evidence, InteractionEvent, Outbox, Relation, ReviewTask
from app.services import owned

STATIC = Path(__file__).parent / "static"


def register_console(app, tenant_auth):
    router = APIRouter(prefix="/v1/console", tags=["Console"])

    @router.get("/graph")
    def graph_health(tenant: str = Depends(tenant_auth)):
        from app.neo4j_connection import graph_status
        return graph_status()

    @router.get("/summary")
    def summary(db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        types = dict(db.execute(select(Entity.entity_type, func.count()).where(
            Entity.tenant_id == tenant).group_by(Entity.entity_type)).all())

        def count(model, *conditions):
            return db.scalar(select(func.count()).select_from(model).where(
                model.tenant_id == tenant, *conditions))

        country = Entity.attrs["country"].as_string()
        countries = db.execute(select(country, func.count()).where(
            Entity.tenant_id == tenant, Entity.entity_type == "Consumer").group_by(country)
            .order_by(func.count().desc())).all()
        languages = db.execute(select(Evidence.language, func.count()).where(
            Evidence.tenant_id == tenant).group_by(Evidence.language).order_by(func.count().desc())).all()
        events = db.execute(select(InteractionEvent.event_type, func.count()).where(
            InteractionEvent.tenant_id == tenant).group_by(InteractionEvent.event_type)
            .order_by(func.count().desc())).all()
        from app.graph_policy import catalog
        _, semantic_edges = catalog(db, tenant)
        return {
            "tenant": tenant,
            "static_relations": len(semantic_edges),
            "consumers": types.get("Consumer", 0),
            "evidence": count(Evidence),
            "claims": count(Claim, Claim.status == "accepted"),
            "relations": count(Relation),
            "events": count(InteractionEvent),
            "products": types.get("ProductModel", 0) + types.get("ProductVariant", 0),
            "needs": types.get("Need", 0),
            "selling_points": types.get("SellingPoint", 0),
            "pending_projection": count(Outbox, Outbox.processed_at.is_(None)),
            "dead_projection": count(Outbox, Outbox.processed_at.is_(None), Outbox.attempts >= 10),
            "pending_review": count(ReviewTask, ReviewTask.status == "pending"),
            "synthetic_consumers": count(Entity, Entity.entity_type == "Consumer",
                                         Entity.attrs["synthetic"].as_boolean().is_(True)),
            "countries": [{"name": name or "Unknown", "count": n} for name, n in countries],
            "languages": [{"name": name, "count": n} for name, n in languages],
            "event_types": [{"name": name, "count": n} for name, n in events],
        }

    @router.get("/evidence")
    def evidence_list(q: str = Query("", max_length=200), language: str | None = None,
                      page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        conditions = [Evidence.tenant_id == tenant]
        if q.strip():
            conditions.append(or_(Evidence.excerpt.icontains(q.strip(), autoescape=True),
                                  Evidence.source_id.icontains(q.strip(), autoescape=True)))
        if language:
            conditions.append(Evidence.language == language)
        total = db.scalar(select(func.count()).select_from(Evidence).where(*conditions))
        rows = db.scalars(select(Evidence).where(*conditions).order_by(Evidence.source_id, Evidence.id)
                          .offset((page - 1) * page_size).limit(page_size)).all()
        return {"total": total, "page": page, "page_size": page_size, "items": [
            {"id": e.id, "source_id": e.source_id, "excerpt": e.excerpt,
             "language": e.language, "metadata": e.metadata_} for e in rows]}

    @router.get("/evidence/{evidence_id}")
    def evidence_detail(evidence_id: str, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        e = owned(db, Evidence, tenant, evidence_id)
        rows = db.execute(select(Claim, Entity).join(Entity, Claim.object_id == Entity.id).where(
            Claim.tenant_id == tenant, Entity.tenant_id == tenant, Claim.evidence_id == e.id)
            .order_by(Claim.predicate, Entity.name)).all()
        return {"id": e.id, "source_id": e.source_id, "excerpt": e.excerpt, "language": e.language,
                "metadata": e.metadata_, "claims": [
                    {"id": c.id, "predicate": c.predicate, "name": n.name, "entity_type": n.entity_type,
                     "confidence": c.confidence, "status": c.status, "extractor_version": c.extractor_version}
                    for c, n in rows]}

    @router.get("/consumers")
    def consumers(country: str | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
                  tenant: str = Depends(tenant_auth)):
        conditions = [Entity.tenant_id == tenant, Entity.entity_type == "Consumer"]
        if country:
            conditions.append(Entity.attrs["country"].as_string() == country)
        total = db.scalar(select(func.count()).select_from(Entity).where(*conditions))
        rows = db.scalars(select(Entity).where(*conditions).order_by(Entity.canonical_key)
                          .offset((page - 1) * page_size).limit(page_size)).all()
        return {"total": total, "page": page, "page_size": page_size,
                "items": [{"id": e.id, "key": e.canonical_key, "name": e.name, "attrs": e.attrs} for e in rows]}

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC), name="console-static")

    @app.get("/", include_in_schema=False)
    def console_index():
        return FileResponse(STATIC / "index.html")
