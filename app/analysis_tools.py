"""Bounded analysis tools. Models choose arguments; never supply SQL or Cypher."""
import math
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func

from app.config import settings
from app.db import SessionLocal
from app.models import Claim, Entity, Evidence, InteractionEvent, Outbox, Relation

Country = Literal['Philippines', 'Indonesia', 'Vietnam', 'Thailand', 'Malaysia', 'Singapore']


class Cohort(BaseModel):
    model_config = ConfigDict(extra='forbid')
    country: Country | None = None
    age_min: int | None = Field(default=None, ge=13, le=110)
    age_max: int | None = Field(default=None, ge=13, le=110)
    occupation: str | None = Field(default=None, max_length=80)
    scenario: str | None = Field(default=None, max_length=80)
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def ordered(self):
        for low, high in ((self.age_min, self.age_max), (self.budget_min, self.budget_max)):
            if low is not None and high is not None and low > high:
                raise ValueError('lower bound exceeds upper bound')
        return self


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cohort: Cohort = Field(default_factory=Cohort)
    compare_to: Cohort | None = None
    need: str | None = Field(default=None, max_length=160, description='Canonical Need name, entity ID, or controlled display name, e.g. Gaming performance / 游戏性能')
    dimension: Literal['country', 'occupation', 'scenario', 'age_band', 'budget_band'] = 'scenario'
    query: str = Field(default='', max_length=120)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['cohort_profile', 'compare_cohorts', 'segment_needs', 'product_paths',
                  'evidence_search', 'behavior_summary']
    purpose: str = Field(min_length=1, max_length=300)
    arguments: ToolArgs = Field(default_factory=ToolArgs)


TOOL_GUIDE = {
    'cohort_profile': 'Describe a cohort, its sample size and top needs. Use before conclusions.',
    'compare_cohorts': 'Compare cohort with compare_to using need shares, differences in percentage points and descriptive Wilson intervals. No causal interpretation.',
    'segment_needs': 'Within cohort, group by dimension (scenario/occupation/country/age_band/budget_band); groups below 5 are omitted.',
    'product_paths': 'Traverse Need <- SUPPORTS - Feature <- HAS_FEATURE - Product, or Product - PROMOTES -> SellingPoint - BASED_ON -> Feature - SUPPORTS -> Need. Supply optional need canonical name. Verify fixed paths in Neo4j if reachable, otherwise explicitly use SQL KG.',
    'evidence_search': 'Retrieve up to 8 cohort-scoped exact interview excerpts. Optional need canonical name and query substring. Need filter uses accepted claims.',
    'behavior_summary': 'Cohort event counts and distinct people, including purchase associations. Not a conversion funnel or purchase causality.'
}


def cohort_consumers(db, tenant, scope):
    query = select(Entity).where(Entity.tenant_id == tenant, Entity.entity_type == 'Consumer')
    if scope.country:
        query = query.where(Entity.attrs['country'].as_string() == scope.country)
    consumers = db.scalars(query).all()
    def matches(e):
        a = e.attrs
        for key, expected in [('occupation', scope.occupation), ('scenario', scope.scenario)]:
            if expected and str(a.get(key, '')).casefold() != expected.casefold():
                return False
        for key, low, high in [('age', scope.age_min, scope.age_max), ('budget_usd', scope.budget_min, scope.budget_max)]:
            value = a.get(key)
            if (low is not None or high is not None) and not isinstance(value, (int, float)):
                return False
            if low is not None and value < low or high is not None and value > high:
                return False
        return True
    return [e for e in consumers if matches(e)]


def needs_for(db, tenant, consumers):
    ids = [e.id for e in consumers]
    if not ids:
        return []
    rows = db.execute(select(Claim, Entity).join(Entity, Entity.id == Claim.object_id).where(
        Claim.tenant_id == tenant, Entity.tenant_id == tenant, Claim.subject_id.in_(ids),
        Claim.status == 'accepted', Claim.predicate == 'HAS_NEED')).all()
    groups = {}
    for c, e in rows:
        g = groups.setdefault(e.id, {'id': e.id, 'name': e.name, 'consumers': set(), 'evidence': set()})
        g['consumers'].add(c.subject_id)
        g['evidence'].add(c.evidence_id)
    return sorted(groups.values(), key=lambda g: (-len(g['consumers']), g['name']))


def interval(count, n):
    if not n:
        return None
    z = 1.96
    p = count / n
    den = 1 + z*z/n
    mid = (p + z*z/(2*n))/den
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return [round(100*(mid-half), 2), round(100*(mid+half), 2)]


def fact(label, value, unit='', sample_size=None, evidence_ids=None, **context):
    return {'label': label, 'value': value, 'unit': unit, 'sample_size': sample_size,
            'evidence_ids': sorted(evidence_ids or [])[:3], 'context': context}


def citations(db, tenant, ids):
    if not ids:
        return []
    rows = db.scalars(select(Evidence).where(Evidence.tenant_id == tenant, Evidence.id.in_(ids))
                      .order_by(Evidence.source_id).limit(20)).all()
    return [{'id': e.id, 'source_id': e.source_id, 'quote': e.excerpt,
             'language': e.language, 'synthetic': bool(e.metadata_.get('synthetic')),
             'annotation_type': e.metadata_.get('annotation_type', 'extracted_or_manual')}
            for e in rows]


def execute_tool(tenant, call):
    with SessionLocal() as db:
        scope = call.arguments.cohort
        consumers = cohort_consumers(db, tenant, scope)
        ids = {e.id for e in consumers}
        needs = needs_for(db, tenant, consumers)
        synthetic = sum(bool(e.attrs.get('synthetic')) for e in consumers)
        out = {'scope': scope.model_dump(exclude_none=True), 'sample_size': len(consumers),
               'synthetic_consumers': synthetic, 'facts': [], 'tables': [], 'citations': [],
               'limitations': ['Descriptive, unweighted convenience sample; no population or causal inference.',
                               'Wilson intervals describe binomial sampling uncertainty only, not selection bias.',
                               'Generated ground-truth labels may not be explicit statements in the source interview.']}
        if synthetic:
            out['limitations'].append('Synthetic consumers are present; conclusions are demonstration hypotheses, not real-market findings.')
        evidence_ids = set()
        from app.graph_policy import resolve_need_filter
        selected_need = resolve_need_filter(db, tenant, call.arguments.need)
        if call.arguments.need:
            out['resolved_need'] = selected_need
            out['need_filter_status'] = 'resolved' if selected_need else 'unresolved'
            if selected_need is None:
                out['limitations'].append('需求筛选词未链接到受控本体；零返回不表示没有需求或产品能力，请先澄清标准需求名称。')
        if call.name == 'cohort_profile':
            out['facts'].append(fact('消费者样本量', len(consumers), '人', len(consumers)))
            table = []
            for n in needs[:10]:
                count = len(n['consumers'])
                share = round(count/len(consumers)*100, 2)
                out['facts'].append(fact(n['name']+' 样本内提及占比', share, '%', len(consumers), n['evidence'],
                                         consumer_count=count, wilson_95=interval(count, len(consumers))))
                table.append({'need': n['name'], 'consumer_count': count, 'share_pct': share,
                              'wilson_95': interval(count, len(consumers))})
                evidence_ids.update(sorted(n['evidence'])[:2])
            out['tables'].append({'title': '需求分布', 'rows': table})
            for dim in ('country', 'occupation', 'scenario'):
                out['tables'].append({'title': dim, 'rows': [{'name': k, 'count': v} for k, v in
                    Counter(e.attrs.get(dim, 'Unknown') for e in consumers).most_common(12)]})
        elif call.name == 'compare_cohorts':
            if call.arguments.compare_to is None:
                raise ValueError('compare_to is required')
            other = cohort_consumers(db, tenant, call.arguments.compare_to)
            other_ids = {e.id for e in other}
            other_needs = {n['name']: n for n in needs_for(db, tenant, other)}
            left = {n['name']: n for n in needs}
            out.update(compare_to=call.arguments.compare_to.model_dump(exclude_none=True),
                       comparison_sample_size=len(other), overlapping_consumers=len(ids & other_ids))
            out['facts'].extend([fact('A 组消费者样本量', len(consumers), '人', len(consumers)),
                                 fact('B 组消费者样本量', len(other), '人', len(other))])
            rows = []
            for name in sorted(set(left) | set(other_needs)):
                a, b = left.get(name), other_needs.get(name)
                ac, bc = len(a['consumers']) if a else 0, len(b['consumers']) if b else 0
                ashare = round(ac/len(consumers)*100, 2) if consumers else None
                bshare = round(bc/len(other)*100, 2) if other else None
                delta = round(ashare-bshare, 2) if ashare is not None and bshare is not None else None
                refs = (a['evidence'] if a else set()) | (b['evidence'] if b else set())
                if delta is not None:
                    out['facts'].append(fact(name+' 提及占比差（A−B）', delta, '百分点',
                        len(consumers), refs, a_count=ac, b_count=bc, a_n=len(consumers), b_n=len(other),
                        a_share_pct=ashare, b_share_pct=bshare))
                rows.append({'need': name, 'a_count': ac, 'a_n': len(consumers), 'a_share_pct': ashare,
                             'b_count': bc, 'b_n': len(other), 'b_share_pct': bshare, 'delta_pp': delta,
                             'a_wilson_95': interval(ac, len(consumers)), 'b_wilson_95': interval(bc, len(other))})
                evidence_ids.update(sorted(refs)[:1])
            out['tables'].append({'title': '群体需求对比（A−B）', 'rows': rows})
            if not consumers or not other:
                out['limitations'].append('At least one cohort is empty; shares and differences are unavailable, not zero.')
            if ids & other_ids:
                out['limitations'].append('The two cohorts overlap; they are not independent groups.')
            out['synthetic_consumers'] = synthetic + sum(bool(e.attrs.get('synthetic')) for e in other if e.id not in ids)
        elif call.name == 'segment_needs':
            dimension = call.arguments.dimension
            groups = defaultdict(set)
            for e in consumers:
                value = e.attrs.get(dimension)
                if dimension == 'age_band':
                    age = e.attrs.get('age')
                    value = f'{int(age)//10*10}–{int(age)//10*10+9}' if isinstance(age, (int, float)) else 'Unknown'
                if dimension == 'budget_band':
                    budget = e.attrs.get('budget_usd')
                    value = '<220 USD' if isinstance(budget, (int, float)) and budget < 220 else '220–449 USD' if isinstance(budget, (int, float)) and budget < 450 else '>=450 USD' if isinstance(budget, (int, float)) else 'Unknown'
                groups[str(value or 'Unknown')].add(e.id)
            rows = []
            for group, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:15]:
                if len(members) < 5:
                    continue
                ranked = sorted([(n, len(n['consumers'] & members)) for n in needs], key=lambda x: -x[1])
                for n, count in ranked[:3]:
                    share = round(count/len(members)*100, 2)
                    rows.append({'group': group, 'sample_size': len(members), 'need': n['name'],
                                 'consumer_count': count, 'share_pct': share})
                    out['facts'].append(fact(f'{group} / {n["name"]} 提及占比', share, '%', len(members),
                                            consumer_count=count, dimension=dimension))
            out['tables'].append({'title': f'按 {dimension} 分群（组内前三需求）', 'rows': rows})
            out['limitations'].append('Groups below 5 consumers are omitted. Exploratory comparisons are not significance tests.')
        elif call.name == 'evidence_search':
            eligible = select(Claim.evidence_id).where(Claim.tenant_id == tenant,
                Claim.subject_id.in_(ids), Claim.status == 'accepted')
            if call.arguments.need:
                need_ids = [n['id'] for n in needs if selected_need is not None and n['name'].casefold() == selected_need.casefold()]
                eligible = eligible.where(Claim.object_id.in_(need_ids))
            q = select(Evidence).where(Evidence.tenant_id == tenant, Evidence.id.in_(eligible))
            redundant_need_query = bool(call.arguments.need and call.arguments.query and
                resolve_need_filter(db, tenant, call.arguments.query) == selected_need and selected_need is not None)
            if call.arguments.query and not redundant_need_query:
                q = q.where(Evidence.excerpt.icontains(call.arguments.query, autoescape=True))
            evidence_ids = set(db.scalars(q.order_by(Evidence.source_id).limit(8)).all())
            evidence_ids = {e.id for e in evidence_ids}
            out['facts'].append(fact('本次检索展示访谈数（最多八条，不是总匹配数）', len(evidence_ids), '条', len(consumers)))
        elif call.name == 'behavior_summary':
            events = db.scalars(select(InteractionEvent).where(InteractionEvent.tenant_id == tenant,
                                InteractionEvent.consumer_id.in_(ids))).all()
            groups = defaultdict(set)
            counts = Counter()
            for event in events:
                groups[event.event_type].add(event.consumer_id)
                counts[event.event_type] += 1
            rows = []
            for kind, members in sorted(groups.items()):
                rows.append({'event_type': kind, 'events': counts[kind], 'consumers': len(members),
                             'cohort_size': len(consumers)})
                out['facts'].append(fact(kind+' 涉及消费者', len(members), '人', len(consumers), event_count=counts[kind]))
            out['tables'].append({'title': '行为事件（非转化漏斗）', 'rows': rows})
            out['limitations'].append('Events are repeated observations; consumer counts across event types cannot be added. Event associations do not explain purchase causes.')
        elif call.name == 'product_paths':
            selected = [n for n in needs if not call.arguments.need or selected_need is not None and n['name'].casefold() == selected_need.casefold()][:5]
            from app.catalog_paths import product_paths, live_product_paths
            selected_map = {n['id']: n for n in selected}
            for n in selected:
                evidence_ids.update(sorted(n['evidence'])[:2])
            paths = product_paths(db, tenant, selected_map)
            for path in paths:
                path.update(supporting_consumers=len(selected_map[path['need_id']]['consumers']),
                            sample_size=len(consumers))
            out['tables'].append({'title': 'SQL 知识图谱产品路径（最多一百条）', 'rows': paths[:100]})
            out['facts'].append(fact('本次检索展示产品路径数', min(len(paths), 100), '条', len(consumers)))
            out['graph'] = {'source': 'sql_knowledge_graph', 'status': 'disabled', 'verified_paths': 0}
            if settings.neo4j_enabled:
                try:
                    live = live_product_paths(tenant, selected_map)
                    live_ids = {(p['need_id'], p['feature_id'], p['product_id'], p['selling_point_id']) for p in live}
                    sql_ids = {(p['need_id'], p['feature_id'], p['product_id'], p['selling_point_id']) for p in paths[:100]}
                    out['graph'] = {'source': 'neo4j_and_sql', 'status': 'live', 'verified_paths': len(live_ids & sql_ids),
                                    'sql_only_paths': len(sql_ids-live_ids), 'neo4j_only_paths': len(live_ids-sql_ids)}
                except Exception:
                    out['graph'] = {'source': 'sql_knowledge_graph', 'status': 'unavailable', 'verified_paths': 0}
                    out['limitations'].append('Neo4j could not be reached; product paths come from SQL asserted graph relations, not a live Neo4j query.')
            pending = db.scalar(select(func.count()).select_from(Outbox).where(
                Outbox.tenant_id == tenant, Outbox.processed_at.is_(None)))
            out['graph']['pending_projection'] = pending
            out['limitations'].append('Product links are curated assertions, not product performance tests; missing paths do not establish unmet market needs.')
        out['citations'] = citations(db, tenant, evidence_ids)
        return out
