from sqlalchemy import func, select
from app.db import SessionLocal
from app.graph_policy import entity_allowed, relation_kind, storage_description
from app.models import Claim, Entity, Outbox, Relation
from app.schemas import EntityIn, RelationIn
from app.services import entity_upsert, relation_upsert
from app.catalog_paths import product_paths


def setup_catalog(tenant='a'):
    with SessionLocal() as db, db.begin():
        def node(kind, key, **attrs):
            return entity_upsert(db, tenant, EntityIn(entity_type=kind, canonical_key=key.casefold(), name=key, attrs=attrs))
        brand, product, point = node('Brand','Brand'), node('ProductModel','Phone'), node('SellingPoint','Night photography')
        feature, need = node('Feature','OIS'), node('Need','Camera quality')
        consumer = node('Consumer','PRIVATE-NAME',age=28,country='Philippines',budget_usd=300)
        stable = node('ConsumerSegment','stable',stable_business_definition=True)
        transient = node('ConsumerSegment','dynamic',filters={'age_min':26})
        market = node('Market','Philippines')
        for src, dst, kind in [(brand,product,'OWNS'),(product,feature,'HAS_FEATURE'),
            (product,point,'COMMUNICATES'),(point,feature,'BASED_ON'),(feature,need,'ADDRESSES'),
            (consumer,need,'HAS_NEED'),(consumer,market,'OCCURS_IN'),(product,stable,'TARGETS')]:
            relation_upsert(db,tenant,RelationIn(src_id=src.id,dst_id=dst.id,relation_type=kind))
        return {e.entity_type+('-dynamic' if e.id==transient.id else ''):e.id
                for e in [brand,product,point,feature,need,consumer,stable,transient,market]}


def test_storage_policy_excludes_dynamic_edges_and_uncontrolled_segments(client):
    ids=setup_catalog()
    with SessionLocal() as db:
        dynamic=db.get(Entity,ids['ConsumerSegment-dynamic'])
        assert not entity_allowed(dynamic)
        assert entity_allowed(db.get(Entity,ids['ConsumerSegment']))
        outbox_ids={row['id'] for row in db.scalars(select(Outbox.payload))}
        rows=db.scalars(select(Relation)).all()
        for r in rows:
            if r.relation_type in ('HAS_NEED','TARGETS','OCCURS_IN'):
                assert r.id not in outbox_ids
                assert relation_kind(r,db.get(Entity,r.src_id),db.get(Entity,r.dst_id)) is None
        assert 'ConsumerSegment-dynamic' in ids
        assert ids['ConsumerSegment-dynamic'] not in outbox_ids
        paths=product_paths(db,'a',[ids['Need']])
        assert len(paths)==2
        assert {p['relation'] for p in paths}=={'HAS_FEATURE','PROMOTES/BASED_ON'}
        assert db.scalar(select(Relation).where(Relation.relation_type=='SUPPORTS'))
        assert db.scalar(select(Relation).where(Relation.relation_type=='PROMOTES'))
    policy=storage_description()
    assert not policy['dynamic_relations_projected'] and 'insight artifacts' in policy['postgresql']


def test_explorer_bounds_tenant_filtering_and_anonymous_identity(client):
    ids=setup_catalog()
    headers={'X-Tenant-Id':'a'}
    graph=client.get('/v1/graph/view',headers=headers).json()
    assert graph['source']=='sql_registry_fallback'
    assert len(graph['edges'])==5
    assert all(n['entity_type']!='Consumer' for n in graph['nodes'])
    assert ids['ConsumerSegment-dynamic'] not in {n['id'] for n in graph['nodes']}
    assert {'OWNS','HAS_FEATURE','PROMOTES','BASED_ON','SUPPORTS'}=={e['kind'] for e in graph['edges']}
    limited=client.get('/v1/graph/view?limit=2',headers=headers).json()
    assert len(limited['nodes'])<=2 and limited['truncated']
    focused=client.get('/v1/graph/view',params={'focus_id':ids['Need'],'depth':3},headers=headers).json()
    assert ids['ProductModel'] in {n['id'] for n in focused['nodes']}
    assert client.get('/v1/graph/view?depth=5',headers=headers).status_code==422
    assert client.get('/v1/graph/view?limit=201',headers=headers).status_code==422
    assert client.get('/v1/graph/view?entity_type=InsightArtifact',headers=headers).status_code==422
    assert client.get('/v1/graph/view?relation_type=HAS_NEED',headers=headers).status_code==422
    assert client.get('/v1/graph/nodes/'+ids['Need'],headers={'X-Tenant-Id':'b'}).status_code==404
    assert client.get('/v1/graph/view?focus_id='+ids['Need'],headers={'X-Tenant-Id':'b'}).status_code==404
    assert not client.get('/v1/graph/view',headers={'X-Tenant-Id':'b'}).json()['nodes']
    consumer=client.get('/v1/graph/nodes/'+ids['Consumer'],headers=headers).json()
    assert consumer['node']['name'].startswith('Consumer ')
    assert 'PRIVATE-NAME' not in str(consumer) and 'budget_usd' not in str(consumer)
    assert 'age' not in consumer['properties']
    assert client.post('/v1/entities',headers=headers,json={
        'entity_type':'InsightArtifact','canonical_key':'bad','name':'bad'}).status_code==422



def test_chinese_names_resolve_for_graph_search_and_agent_paths(client):
    from app.analysis_tools import execute_tool, ToolCall
    ids=setup_catalog()
    response=client.get('/v1/graph/view?q=影像',headers={'X-Tenant-Id':'a'}).json()
    assert ids['Need'] in {n['id'] for n in response['nodes']}
    result=execute_tool('a',ToolCall(name='product_paths',purpose='核对中文需求',arguments={
        'cohort':{'country':'Philippines'},'need':'影像体验'}))
    assert result['need_filter_status']=='resolved' and result['resolved_need']=='Camera quality'
    # Add a sourced consumer need before checking the path support.
    client.post('/v1/ingest/interview',headers={'X-Tenant-Id':'a'},json={
        'source_id':'camera-source','consumer_key':'c2','country':'Philippines','age':28,
        'excerpt':'I need better camera quality.','needs':['Camera quality']})
    result=execute_tool('a',ToolCall(name='product_paths',purpose='核对中文需求',arguments={
        'cohort':{'country':'Philippines'},'need':'影像体验'}))
    assert len(result['tables'][0]['rows'])==2
    evidence=execute_tool('a',ToolCall(name='evidence_search',purpose='核对原文',arguments={
        'cohort':{'country':'Philippines'},'need':'影像体验','query':'影像体验'}))
    assert len(evidence['citations'])==1
    unknown=execute_tool('a',ToolCall(name='product_paths',purpose='未知需求',arguments={'need':'a completely unknown need'}))
    assert unknown['need_filter_status']=='unresolved'



def test_overloaded_relationships_preserve_domain_and_range():
    from app.ontology import load_ontology,validate_relation
    ontology=load_ontology()
    assert validate_relation(ontology,'Need','OCCURS_IN','UsageScenario')
    assert validate_relation(ontology,'Consumer','OCCURS_IN','Market')
    assert not validate_relation(ontology,'Need','OCCURS_IN','Market')
    assert not validate_relation(ontology,'Consumer','OCCURS_IN','UsageScenario')
    assert validate_relation(ontology,'Feature','PARENT_OF','Feature')
    assert not validate_relation(ontology,'Need','PARENT_OF','Feature')
