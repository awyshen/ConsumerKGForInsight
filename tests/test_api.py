def test_ingest_insight_idempotency_and_evidence(client):
    payload = {"source_id": "interview-1", "consumer_key": "c1", "country": "Philippines", "age": 27, "excerpt": "Need battery", "needs": ["Long battery life"], "selling_points": ["5000mAh battery"]}
    r = client.post("/v1/ingest/interview", json=payload)
    assert r.status_code == 200, r.text
    first = r.json()
    assert len(first["claim_ids"]) == 2
    again = client.post("/v1/ingest/interview", json=payload)
    assert again.status_code == 200
    assert again.json()["claim_ids"] == first["claim_ids"]
    result = client.get("/v1/insights/needs", params={"country": "Philippines", "age_min": 26, "age_max": 30}).json()
    assert result["sample_size"] == 1
    assert result["needs"][0]["consumer_count"] == 1
    assert result["needs"][0]["evidence_ids"] == [first["evidence_id"]]
    assert client.get("/v1/evidence/" + first["evidence_id"]).json()["excerpt"] == "Need battery"

def test_cross_tenant_access_blocked(client):
    a = client.post("/v1/entities", headers={"X-Tenant-Id": "a"}, json={"entity_type": "Need", "canonical_key": "battery", "name": "Battery"}).json()
    assert client.get("/v1/entities/" + a["id"], headers={"X-Tenant-Id": "b"}).status_code == 404

def test_ontology_validation(client):
    a = client.post("/v1/entities", json={"entity_type": "Need", "canonical_key": "battery", "name": "Battery"}).json()
    b = client.post("/v1/entities", json={"entity_type": "Consumer", "canonical_key": "u1", "name": "U1"}).json()
    r = client.post("/v1/relations", json={"src_id": a["id"], "dst_id": b["id"], "relation_type": "HAS_NEED"})
    assert r.status_code == 422

def test_invalid_age_range(client):
    assert client.get("/v1/insights/needs?age_min=40&age_max=20").status_code == 422
