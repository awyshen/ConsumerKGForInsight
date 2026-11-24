"""Bounded graph exploration; SQL facts and artifacts are never returned as graph nodes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.graph_policy import (TYPE_LABELS, STATIC_KINDS, VERSION, POLICY_VERSION, entity_allowed,
                              node_record, edge_record, storage_description, ONTOLOGY)
from app.models import AliasMapping, Claim, Entity, Evidence, Relation
from app.services import owned


EDGE_LIMIT = 600


def public_node(record):
    kind = record.get('type', record.get('entity_type'))
    node_id = record.get('id', record.get('entity_id'))
    name = 'Consumer '+node_id[:8] if kind == 'Consumer' else record.get('name', '')
    return {'display_name': ONTOLOGY.get('display_names', {}).get(name, name), 'id': node_id, 'name': 'Consumer '+node_id[:8] if kind == 'Consumer' else record.get('name', ''),
            'entity_type': kind, 'label': TYPE_LABELS.get(kind, kind),
            'status': record.get('status', 'ACTIVE'),
            'ontology_version': record.get('ontology_version', '1.0.0'),
            'synthetic': bool(record.get('synthetic')), 'storage': 'core_identity' if kind == 'Consumer' else 'static_entity'}


def public_edge(record):
    return {'id': record['id'], 'source': record['src'], 'target': record['dst'],
            'kind': record['kind'], 'ontology_version': record.get('ontology_version', VERSION),
            'layer': 'static_semantic'}


def eligible_query(tenant, include_consumers):
    query = select(Entity).where(Entity.tenant_id == tenant, Entity.entity_type.in_(list(TYPE_LABELS)),
        func.upper(func.coalesce(Entity.attrs['status'].as_string(), 'ACTIVE')).in_(['ACTIVE', 'APPROVED']))
    query = query.where(or_(Entity.entity_type != 'ConsumerSegment',
                           Entity.attrs['stable_business_definition'].as_boolean().is_(True)))
    if not include_consumers:
        query = query.where(Entity.entity_type != 'Consumer')
    return query


def sql_adjacent(db, tenant, frontier, kinds, include_consumers):
    candidates = db.scalars(select(Relation).where(Relation.tenant_id == tenant,
        Relation.relation_type.in_(list(kinds) + ['ADDRESSES', 'COMMUNICATES']),
        or_(Relation.src_id.in_(frontier), Relation.dst_id.in_(frontier)))
        .order_by(Relation.id).limit(EDGE_LIMIT+1)).all()
    ids = {i for r in candidates for i in (r.src_id, r.dst_id)}
    entities = {e.id: e for e in db.scalars(eligible_query(tenant, include_consumers).where(Entity.id.in_(ids)))} if ids else {}
    edges = [edge_record(r, entities.get(r.src_id), entities.get(r.dst_id)) for r in candidates]
    return [r for r in edges if r and r['kind'] in kinds], entities, len(candidates) > EDGE_LIMIT


def explore(db, tenant, q, entity_type, relation_type, focus_id, depth, limit, include_consumers):
    if entity_type and entity_type not in TYPE_LABELS:
        raise HTTPException(422, 'Only core entity types can be explored; artifacts and events live in PostgreSQL')
    if relation_type and relation_type not in STATIC_KINDS:
        raise HTTPException(422, 'Only static semantic relationships are available in the core graph')
    include_consumers = include_consumers or entity_type == 'Consumer'
    if focus_id:
        focus = owned(db, Entity, tenant, focus_id)
        if not entity_allowed(focus):
            raise HTTPException(404, 'entity is not part of the core projection')
        include_consumers = include_consumers or focus.entity_type == 'Consumer'
        seeds = [focus]
        truncated = False
    else:
        query = eligible_query(tenant, include_consumers)
        if q.strip():
            canonical = [name.casefold() for name, label in ONTOLOGY.get('display_names', {}).items() if q.strip().casefold() in label.casefold()]
            aliases = select(AliasMapping.canonical_entity_id).where(AliasMapping.tenant_id == tenant,
                        AliasMapping.normalized_alias.icontains(q.strip().casefold(), autoescape=True))
            query = query.where(or_(Entity.name.icontains(q.strip(), autoescape=True),
                                   Entity.canonical_key.icontains(q.strip(), autoescape=True),
                                   func.lower(Entity.canonical_key).in_(canonical), func.lower(Entity.name).in_(canonical), Entity.id.in_(aliases)))
        if entity_type:
            query = query.where(Entity.entity_type == entity_type)
        seeds = db.scalars(query.order_by(Entity.entity_type == 'Consumer', Entity.entity_type, Entity.name, Entity.id).limit(limit+1)).all()
        truncated = len(seeds) > limit
        seeds = seeds[:limit]
    kinds = [relation_type] if relation_type else sorted(STATIC_KINDS)
    selected = {e.id: public_node(node_record(e)) for e in seeds}
    root_ids = list(selected)
    edges = {}
    source = 'sql_registry_fallback'
    missing = 0
    hops = depth if focus_id or q.strip() or entity_type else 1
    if settings.neo4j_enabled:
        try:
            from neo4j import Query as NeoQuery
            from app.neo4j_connection import get_graph_driver
            with get_graph_driver().session() as session:
                records = session.run(NeoQuery('MATCH (n:KGEntity {tenant_id:$t}) WHERE n.id IN $ids AND n.projection_version=$policy RETURN properties(n) AS node', timeout=5),
                                      t=tenant, ids=root_ids, policy=POLICY_VERSION).data()
                selected = {r['node']['id']: public_node(r['node']) for r in records}
                missing = len(root_ids)-len(selected)
                frontier = list(selected)
                for _ in range(hops):
                    if not frontier:
                        break
                    rows = session.run(NeoQuery('''MATCH (a:KGEntity {tenant_id:$t})-[r]-(b:KGEntity {tenant_id:$t})
                        WHERE a.id IN $frontier AND type(r) IN $kinds
                        AND ($consumers OR b.entity_type <> 'Consumer')
                        AND b.status IN ['ACTIVE','APPROVED'] AND b.projection_version=$policy AND r.projection_version=$policy
                        RETURN DISTINCT properties(a) AS a, properties(b) AS b, r.id AS id,
                        type(r) AS kind, startNode(r).id AS src, endNode(r).id AS dst LIMIT $cap''', timeout=5),
                        t=tenant, frontier=frontier, kinds=kinds, consumers=include_consumers, cap=EDGE_LIMIT+1, policy=POLICY_VERSION).data()
                    truncated = truncated or len(rows) > EDGE_LIMIT
                    next_frontier = []
                    for row in rows[:EDGE_LIMIT]:
                        nodes = [public_node(row['a']), public_node(row['b'])]
                        new = [n for n in nodes if n['id'] not in selected]
                        if len(selected)+len(new) > limit or len(edges) >= EDGE_LIMIT:
                            truncated = True
                            continue
                        for node in new:
                            if node['entity_type'] not in TYPE_LABELS: continue
                            selected[node['id']] = node
                            next_frontier.append(node['id'])
                        if row['src'] in selected and row['dst'] in selected:
                            edges[row['id']] = public_edge(row)
                    frontier = next_frontier
                source = 'neo4j'
        except Exception:
            selected = {e.id: public_node(node_record(e)) for e in seeds}
            source = 'sql_registry_fallback'
    if source != 'neo4j':
        edges = {}
        frontier = list(selected)
        for _ in range(hops):
            if not frontier: break
            rows, entities, cut = sql_adjacent(db, tenant, frontier, kinds, include_consumers)
            truncated = truncated or cut
            next_frontier = []
            for row in rows:
                new = [i for i in (row['src'], row['dst']) if i not in selected]
                if len(selected)+len(new) > limit or len(edges) >= EDGE_LIMIT:
                    truncated = True
                    continue
                for entity_id in new:
                    selected[entity_id] = public_node(node_record(entities[entity_id]))
                    next_frontier.append(entity_id)
                edges[row['id']] = public_edge(row)
            frontier = next_frontier
    return {'nodes': list(selected.values()), 'edges': list(edges.values()), 'source': source,
            'ontology_version': VERSION, 'projection_version': POLICY_VERSION, 'truncated': truncated,
            'missing_seed_count': missing, 'limits': {'nodes': limit, 'edges': EDGE_LIMIT, 'depth': hops},
            'focus_id': focus_id, 'storage': storage_description()}


def register_graph_explorer(app, tenant_auth):
    router = APIRouter(prefix='/v1/graph', tags=['Core Knowledge Graph'])

    @router.get('/schema')
    def schema(db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        eligible = eligible_query(tenant, True).subquery()
        grouped = db.execute(select(eligible.c.entity_type, func.count()).group_by(eligible.c.entity_type)).all()
        return {**storage_description(), 'entity_types': [{'type': t, 'label': TYPE_LABELS.get(t, t),
                'count': count} for t, count in grouped if t in TYPE_LABELS],
                'static_relations': sorted(STATIC_KINDS), 'max_depth': 4, 'max_nodes': 200}

    @router.get('/view')
    def view(q: str = Query('', max_length=120), entity_type: str | None = None,
             relation_type: str | None = None, focus_id: str | None = None,
             depth: int = Query(2, ge=1, le=4), limit: int = Query(120, ge=1, le=200),
             include_consumers: bool = False, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        return explore(db, tenant, q, entity_type, relation_type, focus_id, depth, limit, include_consumers)

    @router.get('/nodes/{entity_id}')
    def node_detail(entity_id: str, db: Session = Depends(get_db), tenant: str = Depends(tenant_auth)):
        entity = owned(db, Entity, tenant, entity_id)
        if not entity_allowed(entity):
            raise HTTPException(404, 'entity is not part of the core projection')
        conditions = [Claim.tenant_id == tenant, or_(Claim.subject_id == entity_id, Claim.object_id == entity_id)]
        claims = db.scalar(select(func.count()).select_from(Claim).where(*conditions))
        refs = db.execute(select(Evidence.id, Evidence.source_id).join(Claim, Claim.evidence_id == Evidence.id)
            .where(*conditions, Evidence.tenant_id == tenant).distinct().order_by(Evidence.source_id).limit(5)).all()
        attrs = {k: entity.attrs[k] for k in ('description', 'category', 'synthetic', 'catalog') if k in entity.attrs}
        return {'node': public_node(node_record(entity)), 'properties': attrs,
                'sql_context': {'claim_count': claims, 'evidence': [{'id': r.id, 'source_id': r.source_id} for r in refs],
                    'note': '事实、证据和画像从 PostgreSQL 读取，不是 Neo4j 节点或永久语义边。'},
                'storage': storage_description()}

    app.include_router(router)
