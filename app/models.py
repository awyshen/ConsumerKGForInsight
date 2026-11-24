from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, DateTime, Float, ForeignKey, Index, UniqueConstraint, Text, Integer, JSON, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

def uid(): return str(uuid4())
def utcnow(): return datetime.now(timezone.utc)

class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    canonical_key: Mapped[str] = mapped_column(String(180))
    name: Mapped[str] = mapped_column(String(240))
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "entity_type", "canonical_key"),)

class Relation(Base):
    __tablename__ = "relations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    src_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    dst_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(60))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    __table_args__ = (UniqueConstraint("tenant_id", "src_id", "dst_id", "relation_type"), CheckConstraint("confidence >= 0 AND confidence <= 1"),)

class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[str] = mapped_column(String(180))
    source_type: Mapped[str] = mapped_column(String(40), default="interview")
    excerpt: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="en")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "source_id", "excerpt"),)

class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), index=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    predicate: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="accepted", index=True)
    extractor_version: Mapped[str] = mapped_column(String(50), default="manual-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "evidence_id", "subject_id", "predicate", "object_id"), CheckConstraint("confidence >= 0 AND confidence <= 1"),)

class InteractionEvent(Base):
    __tablename__ = "interaction_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    external_id: Mapped[str] = mapped_column(String(180))
    consumer_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)

class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120))
    filters: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("tenant_id", "name", "version"),)

class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_outbox_pending", "processed_at", "created_at"),)

class ReviewTask(Base):
    __tablename__ = "review_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[str] = mapped_column(String(180))
    mention: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewer: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "source_id", "reason", "id"),)

class AliasMapping(Base):
    __tablename__ = "alias_mappings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    normalized_alias: Mapped[str] = mapped_column(String(200))
    canonical_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("tenant_id", "entity_type", "normalized_alias"),)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120))
    target_id: Mapped[str] = mapped_column(String(180))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class BatchJob(Base):
    __tablename__ = "batch_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    external_key: Mapped[str] = mapped_column(String(180))
    state: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "external_key"),)

class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(240), default="新的研究对话")
    messages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("analysis_sessions.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(80))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    trace: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(160))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("session_id", "request_id"),)


class InsightArtifact(Base):
    __tablename__ = "insight_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("analysis_sessions.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), unique=True)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
