"""Illustrative fictional phone catalog. Never represent demo specifications as real products."""
import argparse
from app.db import SessionLocal
from app.schemas import EntityIn, RelationIn
from app.services import entity_upsert, relation_upsert

CATALOG = [
    ("Aster Play X", [("Feature", "120Hz refresh display", "Gaming performance"),
                       ("Feature", "Efficient gaming chipset", "Gaming performance"),
                       ("SellingPoint", "High-refresh display", "Gaming performance")]),
    ("Aster Endure S", [("Feature", "Large battery capacity", "Battery endurance"),
                         ("Feature", "Fast charging support", "Charging speed"),
                         ("SellingPoint", "Fast charging", "Charging speed")]),
    ("Aster Photo M", [("Feature", "Optical image stabilization", "Camera quality"),
                        ("SellingPoint", "Night photography", "Camera quality")]),
]

def seed(tenant):
    with SessionLocal() as db, db.begin():
        created = 0
        brand = entity_upsert(db, tenant, EntityIn(entity_type="Brand", canonical_key="aster mobile",
                              name="Aster Mobile", attrs={"synthetic": True, "catalog": "fictional-v4"}))
        feature_by_need = {}

        for product_name, links in CATALOG:
            product = entity_upsert(db, tenant, EntityIn(entity_type="ProductModel", canonical_key=product_name.casefold(), name=product_name, attrs={"synthetic": True, "catalog": "fictional-v4"}))
            relation_upsert(db, tenant, RelationIn(src_id=brand.id, dst_id=product.id, relation_type="OWNS"))
            for typ, name, need_name in links:
                need = entity_upsert(db, tenant, EntityIn(entity_type="Need", canonical_key=need_name.casefold(), name=need_name))
                target = entity_upsert(db, tenant, EntityIn(entity_type=typ, canonical_key=name.casefold(), name=name, attrs={"synthetic": True}))
                if typ == "Feature":
                    feature_by_need.setdefault(need_name, target.id)
                    relation_upsert(db, tenant, RelationIn(src_id=target.id, dst_id=need.id, relation_type="SUPPORTS", confidence=1))
                else:
                    # Explicitly curated fictitious catalog mappings, never inferred from interviews.
                    relation_upsert(db, tenant, RelationIn(src_id=target.id, dst_id=feature_by_need[need_name], relation_type="BASED_ON"))
                relation_upsert(db, tenant, RelationIn(src_id=product.id, dst_id=target.id,
                                relation_type="HAS_FEATURE" if typ == "Feature" else "PROMOTES", confidence=1))
                created += 1
    return created

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    print({"catalog_links": seed(args.tenant), "fictional": True})
