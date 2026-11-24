from app.db import Base, engine, SessionLocal
from app.schemas import InterviewIn, EntityIn, EvidenceIn, ClaimIn, RelationIn
from app.services import entity_upsert, evidence_upsert, claim_upsert, relation_upsert

samples = [
    ("ph-001", 27, "I need long battery life for commuting and mobile games.", ["Long battery life", "Gaming performance"], ["5000mAh battery"]),
    ("ph-002", 29, "I care about camera quality and battery for family photos.", ["Camera quality", "Long battery life"], ["Night photography"]),
    ("ph-003", 25, "I need affordable performance and a good camera.", ["Affordable price", "Camera quality"], ["Value for money"]),
    ("ph-004", 28, "Battery and camera matter most to me.", ["Long battery life", "Camera quality"], ["5000mAh battery"]),
]

def run():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        with db.begin():
            for key, age, excerpt, needs, selling in samples:
                consumer = entity_upsert(db, "demo", EntityIn(entity_type="Consumer", canonical_key=key, name=key, attrs={"country": "Philippines", "age": age}))
                evidence = evidence_upsert(db, "demo", EvidenceIn(source_id="interview-"+key, excerpt=excerpt))
                for kind, names, pred in (("Need", needs, "HAS_NEED"), ("SellingPoint", selling, "RESPONDS_TO")):
                    for name in names:
                        target = entity_upsert(db, "demo", EntityIn(entity_type=kind, canonical_key=name.casefold(), name=name))
                        claim_upsert(db, "demo", ClaimIn(evidence_id=evidence.id, subject_id=consumer.id, predicate=pred, object_id=target.id, confidence=0.95))
                        relation_upsert(db, "demo", RelationIn(src_id=consumer.id, dst_id=target.id, relation_type=pred))
    print("Seeded 4 synthetic Philippine consumer interviews (tenant=demo)")

if __name__ == "__main__": run()
