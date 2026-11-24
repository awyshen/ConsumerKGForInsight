from app.quality import evaluate

def test_evaluation():
    g = [{"source_id": "x", "language": "tl", "mentions": [{"entity_type": "Need", "canonical_name": "Battery endurance"}]}]
    p = [{"source_id": "x", "mentions": [{"entity_type": "Need", "canonical_name": "Battery endurance"}]}]
    assert evaluate(g, p)["micro"]["f1"] == 1.0

def test_empty_opportunity(client):
    r = client.get("/v1/opportunities?country=PH")
    assert r.status_code == 200
    assert r.json()["sample_size"] == 0

def test_admin_disabled_by_default(client):
    assert client.get("/v1/governance/reviews").status_code == 403

def test_multi_tenant_isolation(client):
    headers = {"x-tenant-id": "a"}
    r = client.post("/v1/entities", json={"entity_type": "Need", "canonical_key": "battery", "name": "Battery"}, headers=headers)
    assert r.status_code == 200
    eid = r.json()["id"]
    assert client.get(f"/v1/entities/{eid}", headers={"x-tenant-id": "b"}).status_code == 404

def test_multi_hop_product_path(client):
    from app.db import SessionLocal
    from app.schemas import EntityIn, RelationIn, EvidenceIn, ClaimIn
    from app.services import entity_upsert, relation_upsert, evidence_upsert, claim_upsert
    from app.opportunity import opportunities
    with SessionLocal() as db, db.begin():
        c = entity_upsert(db, "demo", EntityIn(entity_type="Consumer", canonical_key="c", name="C", attrs={"country": "PH", "age": 28}))
        n = entity_upsert(db, "demo", EntityIn(entity_type="Need", canonical_key="gaming performance", name="Gaming performance"))
        f = entity_upsert(db, "demo", EntityIn(entity_type="Feature", canonical_key="120hz", name="120Hz display"))
        p = entity_upsert(db, "demo", EntityIn(entity_type="ProductModel", canonical_key="fictional", name="Fictional phone"))
        e = evidence_upsert(db, "demo", EvidenceIn(source_id="interview1", excerpt="I need gaming performance", language="en"))
        claim_upsert(db, "demo", ClaimIn(evidence_id=e.id, subject_id=c.id, predicate="HAS_NEED", object_id=n.id, confidence=0.99))
        relation_upsert(db, "demo", RelationIn(src_id=f.id, dst_id=n.id, relation_type="ADDRESSES"))
        relation_upsert(db, "demo", RelationIn(src_id=p.id, dst_id=f.id, relation_type="HAS_FEATURE"))
    r = client.get("/v1/opportunities?country=PH&age_min=26&age_max=30")
    assert r.status_code == 200
    assert r.json()["opportunities"][0]["matching_products"][0]["product"] == "Fictional phone"
    assert r.json()["opportunities"][0]["supporting_evidence"][0]["source_id"] == "interview1"
