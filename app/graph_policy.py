"""Storage boundary from design V1.0 §§2, 4.3, 5, 7 and 15.1.

SQL owns registry, facts, profiles, events and artifacts. Neo4j projects stable
core identities and a controlled set of semantic edges only.
"""
from sqlalchemy import select, func, or_
from app.models import Entity, Relation
from app.ontology import load_ontology

ONTOLOGY = load_ontology()
VERSION = ONTOLOGY['version']
POLICY_VERSION = ONTOLOGY['projection']['version']
TYPE_LABELS = {t: ('Product' if t in ('ProductModel', 'ProductVariant') else t)
               for t in ONTOLOGY['entity_types']}
STATIC_KINDS = frozenset(ONTOLOGY['projection']['static_relations'])
SQL_ONLY_KINDS = frozenset({'HAS_NEED', 'RESPONDS_TO', 'USES', 'LOCATED_IN', 'USES_IN',
                            'BELONGS_TO', 'TARGETS', 'APPEALS_TO', 'INFLUENCED_BY',
                            'PURCHASED', 'CONSIDERS', 'AVAILABLE_THROUGH'})


def entity_allowed(entity):
    if entity.entity_type not in TYPE_LABELS:
        return False
    if str(entity.attrs.get('status', 'ACTIVE')).upper() not in ('ACTIVE', 'APPROVED'):
        return False
    if entity.entity_type == 'ConsumerSegment':
        return entity.attrs.get('stable_business_definition') is True
    return True


def relation_kind(relation, src, dst):
    if not src or not dst or src.tenant_id != relation.tenant_id or dst.tenant_id != relation.tenant_id:
        return None
    if not entity_allowed(src) or not entity_allowed(dst):
        return None
    kind = relation.relation_type
    if kind == 'ADDRESSES' and src.entity_type == 'Feature' and dst.entity_type == 'Need':
        kind = 'SUPPORTS'
    elif kind == 'COMMUNICATES' and TYPE_LABELS.get(src.entity_type) == 'Product':
        kind = 'PROMOTES'
    domains = {
        'OWNS': ('Brand', 'Product'), 'HAS_FEATURE': ('Product', 'Feature'),
        'PROMOTES': ('Product', 'SellingPoint'), 'BASED_ON': ('SellingPoint', 'Feature'),
        'SUPPORTS': ('Feature', 'Need'), 'OCCURS_IN': ('Need', 'UsageScenario'),
    }
    pair = (TYPE_LABELS.get(src.entity_type), TYPE_LABELS.get(dst.entity_type))
    if kind == 'PARENT_OF':
        return kind if pair[0] == pair[1] and pair[0] in ('Need', 'Feature') else None
    return kind if kind in STATIC_KINDS and domains.get(kind) == pair else None


def node_record(entity):
    consumer = entity.entity_type == 'Consumer'
    return {'id': entity.id, 'entity_id': entity.id, 'tenant': entity.tenant_id,
            'type': entity.entity_type, 'label': TYPE_LABELS[entity.entity_type],
            'name': 'Consumer '+entity.id[:8] if consumer else entity.name,
            'key': entity.id if consumer else entity.canonical_key,
            'status': str(entity.attrs.get('status', 'ACTIVE')).upper(),
            'ontology_version': entity.attrs.get('ontology_version', '1.0.0'),
            'projection_version': POLICY_VERSION, 'synthetic': bool(entity.attrs.get('synthetic')),
            'created_at': entity.created_at.isoformat() if entity.created_at else None}


def edge_record(relation, src, dst):
    kind = relation_kind(relation, src, dst)
    if not kind:
        return None
    return {'id': relation.id, 'tenant': relation.tenant_id, 'src': relation.src_id,
            'dst': relation.dst_id, 'kind': kind, 'source_kind': relation.relation_type,
            'confidence': relation.confidence, 'ontology_version': VERSION,
            'projection_version': POLICY_VERSION, 'source_type': 'registry_semantic_relation'}


def catalog(db, tenant, include_consumers=False):
    query = select(Entity).where(Entity.tenant_id == tenant)
    if not include_consumers:
        query = query.where(Entity.entity_type != 'Consumer')
    entities = {e.id: e for e in db.scalars(query) if entity_allowed(e)}
    candidates = db.scalars(select(Relation).where(Relation.tenant_id == tenant,
        Relation.relation_type.in_(list(STATIC_KINDS) + ['ADDRESSES', 'COMMUNICATES']))).all()
    records = [edge_record(r, entities.get(r.src_id), entities.get(r.dst_id)) for r in candidates]
    return entities, [r for r in records if r]


def storage_description():
    return {'ontology_version': VERSION, 'projection_version': POLICY_VERSION,
        'neo4j': {'entities': list(TYPE_LABELS), 'relations': sorted(STATIC_KINDS),
                  'consumer': 'anonymous identity only', 'segment': 'stable business definitions only'},
        'postgresql': ['entity registry', 'consumer profiles', 'dynamic cohort filters', 'claims/assertions',
                       'evidence', 'events', 'analysis sessions', 'analysis runs', 'insight artifacts'],
        'dynamic_relations_projected': False}


def resolve_need_filter(db, tenant, value):
    """Resolve controlled names/display labels/governed aliases; never create a concept."""
    if not value:
        return None
    from app.models import AliasMapping
    from app.knowledge_pipeline import norm, resolve
    query = norm(value)
    alias = db.scalar(select(AliasMapping).where(AliasMapping.tenant_id == tenant,
        AliasMapping.entity_type == 'Need', AliasMapping.normalized_alias == query))
    if alias:
        entity = db.get(Entity, alias.canonical_entity_id)
        if entity and entity.tenant_id == tenant and entity.entity_type == 'Need':
            return entity.name
    for canonical, display in ONTOLOGY.get('display_names', {}).items():
        if norm(display) == query:
            entity = db.scalar(select(Entity).where(Entity.tenant_id == tenant,
                Entity.entity_type == 'Need', or_(func.lower(Entity.canonical_key) == norm(canonical), func.lower(Entity.name) == norm(canonical))))
            if entity:
                return entity.name
    direct = db.scalar(select(Entity).where(Entity.tenant_id == tenant, Entity.entity_type == 'Need',
        or_(func.lower(Entity.name) == query, func.lower(Entity.canonical_key) == query, Entity.id == value)))
    if direct:
        return direct.name
    canonical, _ = resolve('Need', value)
    return canonical
