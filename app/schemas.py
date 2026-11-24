from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class EntityIn(BaseModel):
    entity_type: str
    canonical_key: str = Field(min_length=1, max_length=180)
    name: str = Field(min_length=1, max_length=240)
    attrs: dict = Field(default_factory=dict)

class RelationIn(BaseModel):
    src_id: str
    dst_id: str
    relation_type: str
    confidence: float = Field(default=1, ge=0, le=1)

class EvidenceIn(BaseModel):
    source_id: str = Field(min_length=1)
    source_type: str = "interview"
    excerpt: str = Field(min_length=1, max_length=20000)
    language: str = "en"
    metadata: dict = Field(default_factory=dict)

class ClaimIn(BaseModel):
    evidence_id: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: float = Field(ge=0, le=1)
    extractor_version: str = "manual-v1"

class EventIn(BaseModel):
    external_id: str
    consumer_id: str
    event_type: Literal["INTERVIEW", "PRODUCT_EXPERIENCE", "PRODUCT_CONSULTATION", "PRODUCT_COMPARISON", "PURCHASE_INTENTION", "PURCHASE", "PURCHASE_REJECTION", "POST_PURCHASE_FEEDBACK"]
    occurred_at: datetime
    payload: dict = Field(default_factory=dict)

class SegmentIn(BaseModel):
    name: str
    filters: dict
    version: int = Field(default=1, ge=1)

class InterviewIn(BaseModel):
    source_id: str
    consumer_key: str
    country: str
    age: int = Field(ge=13, le=110)
    excerpt: str = Field(min_length=1, max_length=20000)
    language: str = "en"
    needs: list[str] = Field(default_factory=list)
    selling_points: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")
