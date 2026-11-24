"""Shared SQL semantic traversal, compatible with legacy aliases and V1.0 paths."""
from collections import defaultdict
from app.graph_policy import catalog


def product_paths(db, tenant, need_ids):
    entities, edges = catalog(db, tenant)
    supports, features, promoted, based = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for e in edges:
        if e['kind'] == 'SUPPORTS': supports[e['dst']].append(e['src'])
        elif e['kind'] == 'HAS_FEATURE': features[e['dst']].append(e['src'])
        elif e['kind'] == 'PROMOTES': promoted[e['dst']].append(e['src'])
        elif e['kind'] == 'BASED_ON': based[e['dst']].append(e['src'])
    paths, seen = [], set()
    for need in need_ids:
        for feature in supports[need]:
            candidates = [(p, None, 'HAS_FEATURE') for p in features[feature]]
            for point in based[feature]:
                candidates.extend((p, point, 'PROMOTES/BASED_ON') for p in promoted[point])
            for product, point, route in candidates:
                key = (need, feature, product, point)
                if key in seen: continue
                seen.add(key)
                paths.append({'need_id': need, 'need': entities[need].name,
                    'feature_id': feature, 'feature': entities[feature].name,
                    'product_id': product, 'product': entities[product].name,
                    'selling_point_id': point, 'selling_point': entities[point].name if point else None,
                    'relation': route})
    return paths


def live_product_paths(tenant, need_ids):
    from neo4j import Query
    from app.neo4j_connection import get_graph_driver
    # Both branches are fixed and at most three hops; no raw query is model-generated.
    query = Query('''
      MATCH (n:KGEntity:Need {tenant_id:$t}) WHERE n.id IN $ids
      CALL (n) {
        MATCH (n)<-[:SUPPORTS]-(f:KGEntity:Feature {tenant_id:$t})
              <-[:HAS_FEATURE]-(p:KGEntity:Product {tenant_id:$t})
        RETURN f.id AS feature_id, p.id AS product_id, null AS selling_point_id
        UNION
        MATCH (n)<-[:SUPPORTS]-(f:KGEntity:Feature {tenant_id:$t})
              <-[:BASED_ON]-(sp:KGEntity:SellingPoint {tenant_id:$t})
              <-[:PROMOTES]-(p:KGEntity:Product {tenant_id:$t})
        RETURN f.id AS feature_id, p.id AS product_id, sp.id AS selling_point_id
      }
      RETURN DISTINCT n.id AS need_id, feature_id, product_id, selling_point_id LIMIT 100
    ''', timeout=5)
    with get_graph_driver().session() as session:
        return session.run(query, t=tenant, ids=list(need_ids)).data()
