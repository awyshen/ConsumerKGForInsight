import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.config import settings
from app.db import Base, engine, get_db
from app.models import Entity, Evidence, Claim, InteractionEvent, Segment, Outbox
from app.schemas import EntityIn, RelationIn, EvidenceIn, ClaimIn, EventIn, SegmentIn, InterviewIn
from app.services import entity_upsert, relation_upsert, evidence_upsert, claim_upsert, insights, owned, fail
from app.graph import drain_outbox
from app.llm import extract_suggestions

logging.basicConfig(level=settings.log_level)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local bootstrap only; production migrations must be applied before starting API.
    if settings.app_env in ("local", "test"):
        Base.metadata.create_all(engine)
    try:
        yield
    finally:
        from app.neo4j_connection import close_graph_connections
        close_graph_connections()

app = FastAPI(title="Consumer Knowledge Graph API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

def tenant_auth(x_tenant_id: str = Header(default="demo"), x_api_key: str | None = Header(default=None)):
    if not x_tenant_id or len(x_tenant_id) > 80: fail(400, "invalid tenant")
    if settings.api_key and x_api_key != settings.api_key: fail(401, "invalid API key")
    return x_tenant_id

@app.get("/health/live")
def live(): return {"status": "ok"}

@app.get("/health/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok", "graph": "optional-async"}

@app.post("/v1/entities")
def create_entity(payload: EntityIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    with db.begin(): obj = entity_upsert(db, tenant, payload)
    return {"id": obj.id, "entity_type": obj.entity_type, "name": obj.name}

@app.get("/v1/entities/{entity_id}")
def get_entity(entity_id: str, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    e = owned(db, Entity, tenant, entity_id)
    return {"id": e.id, "entity_type": e.entity_type, "name": e.name, "attrs": e.attrs}

@app.post("/v1/relations")
def create_relation(payload: RelationIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    with db.begin(): obj = relation_upsert(db, tenant, payload)
    return {"id": obj.id, "relation_type": obj.relation_type}

@app.post("/v1/evidence")
def create_evidence(payload: EvidenceIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    with db.begin(): obj = evidence_upsert(db, tenant, payload)
    return {"id": obj.id, "source_id": obj.source_id}

@app.get("/v1/evidence/{evidence_id}")
def get_evidence(evidence_id: str, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    e = owned(db, Evidence, tenant, evidence_id)
    return {"id": e.id, "source_id": e.source_id, "excerpt": e.excerpt, "language": e.language, "metadata": e.metadata_}

@app.post("/v1/claims")
def create_claim(payload: ClaimIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    with db.begin(): obj = claim_upsert(db, tenant, payload)
    return {"id": obj.id, "status": obj.status}

@app.post("/v1/events")
def create_event(payload: EventIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    owned(db, Entity, tenant, payload.consumer_id)
    existing = db.scalar(select(InteractionEvent).where(InteractionEvent.tenant_id == tenant, InteractionEvent.external_id == payload.external_id))
    if existing: return {"id": existing.id, "duplicate": True}
    with db.begin_nested():
        obj = InteractionEvent(tenant_id=tenant, **payload.model_dump()); db.add(obj); db.flush()
    db.commit()
    return {"id": obj.id, "duplicate": False}

@app.post("/v1/segments")
def create_segment(payload: SegmentIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    allowed = {"country", "age_min", "age_max"}
    if not set(payload.filters).issubset(allowed): fail(422, "unsupported segment filters")
    obj = db.scalar(select(Segment).where(Segment.tenant_id == tenant, Segment.name == payload.name, Segment.version == payload.version))
    if obj: return {"id": obj.id, "duplicate": True}
    obj = Segment(tenant_id=tenant, **payload.model_dump()); db.add(obj); db.commit()
    return {"id": obj.id, "duplicate": False}

@app.post("/v1/ingest/interview")
def ingest_interview(payload: InterviewIn, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    # Structured, reviewer-supplied labels only; LLM suggestions use a separate endpoint.
    with db.begin():
        consumer = entity_upsert(db, tenant, EntityIn(entity_type="Consumer", canonical_key=payload.consumer_key, name=f"Consumer {payload.consumer_key}", attrs={"country": payload.country, "age": payload.age}))
        evidence = evidence_upsert(db, tenant, EvidenceIn(source_id=payload.source_id, excerpt=payload.excerpt, language=payload.language))
        claims = []
        for kind, names, predicate in (("Need", payload.needs, "HAS_NEED"), ("SellingPoint", payload.selling_points, "RESPONDS_TO")):
            for name in dict.fromkeys(names):
                node = entity_upsert(db, tenant, EntityIn(entity_type=kind, canonical_key=name.strip().casefold(), name=name.strip()))
                claim = claim_upsert(db, tenant, ClaimIn(evidence_id=evidence.id, subject_id=consumer.id, predicate=predicate, object_id=node.id, confidence=1.0, extractor_version="reviewed-input-v1"))
                relation_upsert(db, tenant, RelationIn(src_id=consumer.id, dst_id=node.id, relation_type=predicate))
                claims.append(claim.id)
    return {"consumer_id": consumer.id, "evidence_id": evidence.id, "claim_ids": claims}

@app.post("/v1/extract/suggest")
async def suggest(payload: EvidenceIn, tenant: str = Depends(tenant_auth)):
    return await extract_suggestions(payload.excerpt)

@app.get("/v1/insights/needs")
def get_insights(country: str | None = None, age_min: int | None = Query(None, ge=0), age_max: int | None = Query(None, ge=0), min_confidence: float = Query(0, ge=0, le=1), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    if age_min is not None and age_max is not None and age_min > age_max: fail(422, "age_min > age_max")
    return insights(db, tenant, country, age_min, age_max, min_confidence, limit)

@app.post("/v1/admin/graph/project")
def project(tenant: str = Depends(tenant_auth)):
    # Restrict this endpoint to internal networks and dedicated admin credentials in production.
    if settings.app_env == "production": fail(403, "use dedicated graph worker")
    return drain_outbox()

# Knowledge pipeline V3: strict evidence alignment, canonical entity linking, transactional graph outbox.
from app.knowledge_pipeline import InterviewJob, process
from app.grounded_qa import answer as grounded_answer
from pydantic import BaseModel, Field

class AskRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    evidence_limit: int = Field(default=3, ge=1, le=10)

@app.post("/v1/knowledge/interviews")
async def knowledge_ingest(payload: InterviewJob, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    try:
        return await process(db, tenant, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/v1/qa/ask")
def knowledge_ask(payload: AskRequest, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
    try:
        return grounded_answer(db, tenant, payload.question, payload.top_k, payload.evidence_limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

# V4: governed knowledge linking, explainable multi-hop discovery and graph rebuild.
from app.models import ReviewTask, AliasMapping, AuditEvent
from app.opportunity import opportunities
from app.governance import set_alias, review_decide, enqueue_rebuild
from sqlalchemy import func
from pydantic import field_validator

class AliasRequest(BaseModel):
    entity_type: str = Field(min_length=2, max_length=50)
    alias: str = Field(min_length=2, max_length=200)
    entity_id: str

class ReviewDecision(BaseModel):
    decision: str


def admin_auth(x_admin_key: str | None = Header(default=None), tenant: str = Depends(tenant_auth)):
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(403, "admin key required")
    return tenant

@app.get("/v1/opportunities")
def get_opportunities(country: str | None = None, age_min: int | None = Query(None, ge=0),
                      age_max: int | None = Query(None, ge=0), limit: int = Query(10, ge=1, le=100),
                      evidence_limit: int = Query(3, ge=0, le=10), db: Session = Depends(get_db),
                      tenant: str = Depends(tenant_auth)):
    if age_min is not None and age_max is not None and age_min > age_max:
        raise HTTPException(422, "age_min > age_max")
    return opportunities(db, tenant, country, age_min, age_max, limit, evidence_limit)

@app.get("/v1/governance/reviews")
def list_reviews(status: str = "pending", limit: int = Query(50, ge=1, le=200),
                 db: Session = Depends(get_db), tenant: str = Depends(admin_auth)):
    rows = db.scalars(select(ReviewTask).where(ReviewTask.tenant_id == tenant,
                      ReviewTask.status == status).order_by(ReviewTask.created_at).limit(limit)).all()
    return [{"id": r.id, "source_id": r.source_id, "reason": r.reason,
             "mention": r.mention, "status": r.status} for r in rows]

@app.post("/v1/governance/reviews/{review_id}/decision")
def decide_review(review_id: str, payload: ReviewDecision, x_actor: str = Header(default="admin"),
                  db: Session = Depends(get_db), tenant: str = Depends(admin_auth)):
    try:
        with db.begin(): row = review_decide(db, tenant, x_actor, review_id, payload.decision)
    except ValueError as e: raise HTTPException(409, str(e)) from e
    return {"id": row.id, "status": row.status}

@app.post("/v1/governance/aliases")
def create_alias(payload: AliasRequest, x_actor: str = Header(default="admin"),
                 db: Session = Depends(get_db), tenant: str = Depends(admin_auth)):
    try:
        with db.begin(): row = set_alias(db, tenant, x_actor, payload.entity_type, payload.alias, payload.entity_id)
    except ValueError as e: raise HTTPException(409, str(e)) from e
    return {"id": row.id, "alias": row.normalized_alias, "canonical_entity_id": row.canonical_entity_id}

@app.post("/v1/admin/graph/rebuild")
def rebuild_graph(x_actor: str = Header(default="admin"), db: Session = Depends(get_db),
                  tenant: str = Depends(admin_auth)):
    with db.begin(): return enqueue_rebuild(db, tenant, x_actor)

@app.get("/v1/admin/outbox/stats")
def outbox_stats(db: Session = Depends(get_db), tenant: str = Depends(admin_auth)):
    pending = db.scalar(select(func.count()).select_from(Outbox).where(Outbox.tenant_id == tenant, Outbox.processed_at.is_(None)))
    dead = db.scalar(select(func.count()).select_from(Outbox).where(Outbox.tenant_id == tenant, Outbox.processed_at.is_(None), Outbox.attempts >= 10))
    return {"pending": pending, "dead_letter": dead}

# The bundled console and API share an origin and the same tenant authentication.
from app.console import register_console
register_console(app, tenant_auth)

from app.analysis_api import register_analysis
register_analysis(app, tenant_auth)

from app.graph_explorer import register_graph_explorer
register_graph_explorer(app, tenant_auth)
