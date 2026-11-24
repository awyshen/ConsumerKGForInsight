"""Evidence-grounded multi-hop need -> feature -> product discovery.
All traversal edges are asserted relations; no causal effects are inferred.
"""
from collections import defaultdict
from sqlalchemy import select
from app.models import Claim, Entity, Evidence, Relation


def opportunities(db, tenant: str, country=None, age_min=None, age_max=None, limit=10, evidence_limit=3):
    consumers = db.scalars(select(Entity).where(Entity.tenant_id == tenant, Entity.entity_type == "Consumer")).all()
    cohort = {c.id for c in consumers if
              (not country or str(c.attrs.get("country", "")).casefold() == country.casefold()) and
              (age_min is None or isinstance(c.attrs.get("age"), int) and c.attrs["age"] >= age_min) and
              (age_max is None or isinstance(c.attrs.get("age"), int) and c.attrs["age"] <= age_max)}
    if not cohort:
        return {"sample_size": 0, "opportunities": [], "limitations": ["empty cohort"]}
    claims = db.scalars(select(Claim).where(Claim.tenant_id == tenant, Claim.status == "accepted",
                         Claim.predicate == "HAS_NEED", Claim.subject_id.in_(cohort))).all()
    need_support = defaultdict(lambda: {"consumers": set(), "evidence": set()})
    for c in claims:
        need_support[c.object_id]["consumers"].add(c.subject_id)
        need_support[c.object_id]["evidence"].add(c.evidence_id)
    from app.catalog_paths import product_paths
    paths = product_paths(db, tenant, need_support)
    entities = {e.id: e for e in db.scalars(select(Entity).where(Entity.tenant_id == tenant,
                Entity.id.in_(need_support))).all()}
    results = []
    for need_id, support in need_support.items():
        relevant = [p for p in paths if p['need_id'] == need_id]
        features = {p['feature_id']: {'id': p['feature_id'], 'name': p['feature']} for p in relevant}
        points = {p['selling_point_id']: {'id': p['selling_point_id'], 'name': p['selling_point']}
                  for p in relevant if p['selling_point_id']}
        products = {}
        for p in relevant:
            match = products.setdefault(p['product_id'], {'product_id': p['product_id'],
                'product': p['product'], 'features': {}, 'selling_points': {},
                'path': 'Product -HAS_FEATURE-> Feature -SUPPORTS-> Need; Product -PROMOTES-> SellingPoint -BASED_ON-> Feature'})
            match['features'][p['feature_id']] = features[p['feature_id']]
            if p['selling_point_id']:
                match['selling_points'][p['selling_point_id']] = points[p['selling_point_id']]
        matches = [{**p, 'features': list(p['features'].values()), 'selling_points': list(p['selling_points'].values())}
                   for p in products.values()]
        evidence = db.scalars(select(Evidence).where(Evidence.tenant_id == tenant, Evidence.id.in_(support["evidence"])).limit(evidence_limit)).all()
        results.append({"need_id": need_id, "need": entities[need_id].name if need_id in entities else need_id,
                        "consumer_count": len(support["consumers"]), "share_of_cohort": round(len(support["consumers"])/len(cohort), 4),
                        "supporting_evidence": [{"id": e.id, "source_id": e.source_id, "excerpt": e.excerpt[:400]} for e in evidence],
                        "linked_features": list(features.values()),
                        "linked_selling_points": list(points.values()),
                        "matching_products": sorted(matches, key=lambda x: x["product"])})
    results.sort(key=lambda r: (-r["consumer_count"], r["need"]))
    return {"sample_size": len(cohort), "opportunities": results[:limit],
            "limitations": ["descriptive, non-representative cohort", "product paths require curated asserted edges", "absence of a path is not evidence of product inadequacy", "synthetic data must not be used for market decisions"]}
