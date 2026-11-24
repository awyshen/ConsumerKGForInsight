"""Deterministic, explicitly synthetic consumer interviews and graph ingestion.
Usage: python -m scripts.synthetic_pipeline generate --count 1200 --seed 20261118
       python -m scripts.synthetic_pipeline load --database-url sqlite:///./synthetic_demo.db
       python -m scripts.synthetic_pipeline evaluate
"""
import argparse
import csv
import json
import os
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'synthetic'
NEEDS = {
    'Battery endurance': ('battery lasts all day', 'matagal ang battery', '全天续航', 'battery for long shifts'),
    'Camera quality': ('clear low-light photos', 'magandang camera', '夜景拍照清晰', 'camera for family photos'),
    'Affordable price': ('fits my budget', 'sulit sa presyo', '价格实惠', 'affordable monthly payment'),
    'Gaming performance': ('smooth gaming without lag', 'walang lag sa games', '游戏不卡顿', 'high frame rate for games'),
    'Storage capacity': ('enough space for photos and apps', 'malaking storage', '大容量存储', 'storage for offline videos'),
    'Charging speed': ('quick charging before work', 'mabilis mag-charge', '充电速度快', 'fast charge on short breaks'),
    'Durability': ('survives rain and accidental drops', 'matibay na phone', '手机耐用', 'durable for outdoor work'),
    'Connectivity': ('reliable mobile signal', 'malakas ang signal', '网络信号稳定', 'stable data connection'),
    'Display quality': ('bright screen outdoors', 'maliwanag ang screen', '屏幕清晰明亮', 'readable screen in sunlight'),
    'Privacy and security': ('secure mobile banking', 'safe ang personal data', '隐私安全', 'protected banking apps'),
}
POINTS = {
    'Long-life battery': 'Battery endurance', 'Night photography': 'Camera quality',
    'Value for money': 'Affordable price', 'High-refresh display': 'Gaming performance',
    'Expandable storage': 'Storage capacity', 'Fast charging': 'Charging speed',
    'Water resistance': 'Durability', '5G connectivity': 'Connectivity',
    'Outdoor brightness': 'Display quality', 'Biometric security': 'Privacy and security',
}
NEED_TO_POINT = {v:k for k,v in POINTS.items()}
COUNTRIES = [('Philippines', .57), ('Indonesia', .17), ('Vietnam', .10), ('Thailand', .08), ('Malaysia', .05), ('Singapore', .03)]
JOBS = ['student','office worker','retail worker','delivery rider','creator','small business owner','healthcare worker','technician']
SCENARIOS = ['commuting','family photography','mobile gaming','online selling','field work','school','travel','mobile banking']
BRANDS = ['Aster Mobile','NovaCell','Helio Devices','Orion Phone']  # fictitious brands
MODELS = ['Aster One','Nova S','Helio Max','Orion Lite']  # fictitious products
EVENTS = ['INTERVIEW','PRODUCT_CONSULTATION','PRODUCT_EXPERIENCE','PRODUCT_COMPARISON','PURCHASE_INTENTION','PURCHASE','PURCHASE_REJECTION','POST_PURCHASE_FEEDBACK']


def write_jsonl(path, rows):
    with path.open('w', encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')


def generate(count=1200, seed=20261118, output=OUT):
    if count < 1: raise ValueError('count must be positive')
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    interviews, events, truth = [], [], []
    country_names, country_weights = zip(*COUNTRIES)
    for i in range(count):
        country = rng.choices(country_names, weights=country_weights)[0]
        age = rng.randint(18, 55)
        if country == 'Philippines' and rng.random() < .42: age = rng.randint(26,30)
        job = rng.choice(JOBS)
        scenario = rng.choice(SCENARIOS)
        budget = rng.choice([110, 160, 220, 300, 450, 650, 900])
        weights = [1.0] * len(NEEDS)
        names = list(NEEDS)
        for ix, name in enumerate(names):
            if name == 'Affordable price' and budget <= 220: weights[ix] *= 3.0
            if name == 'Gaming performance' and (age <= 30 or scenario == 'mobile gaming'): weights[ix] *= 2.8
            if name == 'Camera quality' and scenario == 'family photography': weights[ix] *= 3.0
            if name == 'Battery endurance' and job in ('delivery rider','retail worker'): weights[ix] *= 3.2
            if name == 'Privacy and security' and scenario == 'mobile banking': weights[ix] *= 3.0
        picks = []
        while len(picks) < rng.choice([1,2,2,3]):
            pick = rng.choices(names, weights=weights)[0]
            if pick not in picks: picks.append(pick)
        lang = rng.choices(['en','tl','zh'], weights=[.73,.20,.07])[0] if country == 'Philippines' else rng.choices(['en','zh'], weights=[.94,.06])[0]
        lang_index = {'en':0,'tl':1,'zh':2}[lang]
        clauses = [NEEDS[n][lang_index] for n in picks]
        if lang == 'en': excerpt = f"I work as a {job} and use my phone for {scenario}. I need {', '.join(clauses)}. My budget is around USD {budget}."
        elif lang == 'tl': excerpt = f"Para sa {scenario}, importante sa akin ang {', '.join(clauses)}. Budget ko ay around USD {budget}."
        else: excerpt = f"我平时主要用于{scenario}，比较看重{'、'.join(clauses)}，预算约{budget}美元。"
        # Explicit negation is kept separate; never convert it into a positive need.
        negated = rng.choice([n for n in names if n not in picks]) if rng.random() < .13 else None
        if negated: excerpt += f" I do not prioritize {NEEDS[negated][0]}."  # English negation for evaluation
        consumer_key = f'SYN-C-{i+1:06d}'
        source_id = f'SYN-INT-{i+1:06d}'
        date = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=rng.randrange(300), hours=rng.randrange(24))
        points = [NEED_TO_POINT[n] for n in picks if rng.random() < .83]
        row = {'synthetic':True,'synthetic_version':'v2','source_id':source_id,'consumer_key':consumer_key,
               'country':country,'age':age,'language':lang,'excerpt':excerpt,'needs':picks,
               'selling_points':points,'occupation':job,'scenario':scenario,'budget_usd':budget,
               'interviewed_at':date.isoformat(),'negated_need':negated}
        interviews.append(row)
        truth.append({'source_id':source_id,'consumer_key':consumer_key,'needs':picks,'selling_points':points,'negated_need':negated})
        seq = rng.sample(EVENTS[1:6], rng.randint(1,3))
        if rng.random() < .48: seq.append(rng.choice(['PURCHASE','PURCHASE_REJECTION']))
        if 'PURCHASE' in seq and rng.random() < .35: seq.append('POST_PURCHASE_FEEDBACK')
        seq = ['INTERVIEW'] + seq
        for j, typ in enumerate(seq):
            events.append({'synthetic':True,'external_id':f'SYN-E-{i+1:06d}-{j:02d}',
                           'consumer_key':consumer_key,'event_type':typ,
                           'occurred_at':(date+timedelta(days=j*2)).isoformat(),
                           'payload':{'synthetic':True,'scenario':scenario,'budget_usd':budget,
                                      'product_model':rng.choice(MODELS),'channel':rng.choice(['retail','online','operator'])}})
    write_jsonl(output/'interviews.jsonl', interviews)
    write_jsonl(output/'events.jsonl', events)
    write_jsonl(output/'ground_truth.jsonl', truth)
    manifest = {'synthetic':True,'warning':'Entirely fabricated; not collected from real consumers; no market-representativeness claim',
                'seed':seed,'consumers':count,'interviews':len(interviews),'events':len(events),
                'countries':dict(Counter(r['country'] for r in interviews)),
                'languages':dict(Counter(r['language'] for r in interviews)),
                'generated_at_utc':datetime.now(timezone.utc).isoformat(),
                'ontology_needs':list(NEEDS),'ontology_selling_points':list(POINTS)}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),encoding='utf-8')
    with (output/'consumers.csv').open('w',encoding='utf-8',newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['consumer_key','country','age','occupation','scenario','budget_usd'])
        writer.writeheader()
        for r in interviews: writer.writerow({k:r[k] for k in writer.fieldnames})
    return manifest


def read_jsonl(path):
    with path.open(encoding='utf-8') as f:
        for line in f:
            if line.strip(): yield json.loads(line)


def extract_rule_based(excerpt):
    """Baseline only: multilingual phrase matching; negative mentions are excluded."""
    import re
    positive = set()
    text = excerpt.casefold()
    for name, aliases in NEEDS.items():
        for alias in aliases:
            for match in re.finditer(re.escape(alias.casefold()), text):
                prefix = text[max(0, match.start()-25):match.start()]
                if re.search(r'(?:do not prioritize|not interested in|don\'t need)\s*$', prefix): continue
                positive.add(name)
    return sorted(positive)


def evaluate(output=OUT):
    totals = Counter()
    examples = []
    for row in read_jsonl(output/'interviews.jsonl'):
        pred = set(extract_rule_based(row['excerpt']))
        expected = set(row['needs'])
        totals['tp'] += len(pred & expected)
        totals['fp'] += len(pred - expected)
        totals['fn'] += len(expected - pred)
        totals['samples'] += 1
        if pred != expected and len(examples) < 10:
            examples.append({'source_id':row['source_id'],'expected':sorted(expected),'predicted':sorted(pred)})
    tp,fp,fn = (totals[k] for k in ('tp','fp','fn'))
    precision = tp/(tp+fp) if tp+fp else 0
    recall = tp/(tp+fn) if tp+fn else 0
    report = {'synthetic_only':True,'evaluation_type':'in-distribution template-based baseline (not real-world accuracy)',
              'samples':totals['samples'],'tp':tp,'fp':fp,'fn':fn,
              'precision':round(precision,4),'recall':round(recall,4),
              'f1':round(2*precision*recall/(precision+recall),4) if precision+recall else 0,
              'errors':examples}
    (output/'baseline_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def load(output=OUT, tenant='synthetic-demo', batch_size=100):
    from sqlalchemy import select
    from app.db import Base, engine, SessionLocal
    from app.config import settings
    from app.models import Entity, InteractionEvent
    from app.schemas import EntityIn, EvidenceIn, ClaimIn, RelationIn
    from app.services import entity_upsert, evidence_upsert, claim_upsert, relation_upsert
    if settings.app_env in ('local', 'test'):
        Base.metadata.create_all(engine)
    counts = Counter()
    with SessionLocal() as db:
        for row in read_jsonl(output/'interviews.jsonl'):
            with db.begin():
                consumer = entity_upsert(db, tenant, EntityIn(entity_type='Consumer',canonical_key=row['consumer_key'],
                    name=row['consumer_key'],attrs={'country':row['country'],'age':row['age'],'occupation':row['occupation'],
                        'scenario':row['scenario'],'budget_usd':row['budget_usd'],'synthetic':True}))
                ev = evidence_upsert(db, tenant, EvidenceIn(source_id=row['source_id'],excerpt=row['excerpt'],
                    language=row['language'],metadata={'synthetic':True,'generator':'synthetic_pipeline_v2',
                        'interviewed_at':row['interviewed_at'], 'consumer_key':row['consumer_key'],
                        'annotation_type':'generated_ground_truth',
                        'annotation_warning':'Generated labels; selling points are not necessarily quoted in the interview.'}))
                for kind, items, predicate in [('Need',row['needs'],'HAS_NEED'),('SellingPoint',row['selling_points'],'RESPONDS_TO')]:
                    for item in items:
                        node = entity_upsert(db,tenant,EntityIn(entity_type=kind,canonical_key=item.casefold(),name=item,attrs={'synthetic_taxonomy':True}))
                        claim_upsert(db,tenant,ClaimIn(evidence_id=ev.id,subject_id=consumer.id,predicate=predicate,
                            object_id=node.id,confidence=1.0,extractor_version='synthetic-ground-truth-v2'))
                        relation_upsert(db,tenant,RelationIn(src_id=consumer.id,dst_id=node.id,relation_type=predicate))
                counts['interviews'] += 1
            if counts['interviews'] % batch_size == 0: print(f"loaded {counts['interviews']} interviews",flush=True)
        consumers = {e.canonical_key:e.id for e in db.scalars(select(Entity).where(Entity.tenant_id==tenant,Entity.entity_type=='Consumer'))}
        db.commit()  # close implicit read transaction before event writes
        for row in read_jsonl(output/'events.jsonl'):
            with db.begin():
                exists = db.scalar(select(InteractionEvent.id).where(InteractionEvent.tenant_id==tenant,InteractionEvent.external_id==row['external_id']))
                if not exists:
                    db.add(InteractionEvent(tenant_id=tenant,external_id=row['external_id'],consumer_id=consumers[row['consumer_key']],
                        event_type=row['event_type'],occurred_at=datetime.fromisoformat(row['occurred_at']),payload=row['payload']))
                    counts['events'] += 1
    return dict(counts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['generate','evaluate','load'])
    parser.add_argument('--count',type=int,default=1200)
    parser.add_argument('--seed',type=int,default=20261118)
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--database-url',default=None)
    parser.add_argument('--tenant',default='synthetic-demo')
    args = parser.parse_args()
    if args.database_url: os.environ['DATABASE_URL'] = args.database_url
    if args.action == 'generate': result=generate(args.count,args.seed,args.output)
    elif args.action == 'evaluate': result=evaluate(args.output)
    else: result=load(args.output,args.tenant)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
