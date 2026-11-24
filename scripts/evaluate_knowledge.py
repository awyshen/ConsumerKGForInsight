"""Compare positive need extraction against synthetic ground truth; not real-world accuracy."""
import json
from pathlib import Path
from app.knowledge_pipeline import rule_extract, verify_extraction
root = Path(__file__).resolve().parents[1] / 'data' / 'synthetic'
truth = {r['source_id']:r for r in map(json.loads, (root/'ground_truth.jsonl').open(encoding='utf8'))}
tp=fp=fn=0
for row in map(json.loads, (root/'interviews.jsonl').open(encoding='utf8')):
    accepted, _ = verify_extraction(rule_extract(row['excerpt'], row['language']), row['excerpt'])
    pred={m.canonical_name for m in accepted if m.entity_type=='Need'}
    gold=set(truth[row['source_id']]['needs'])
    tp+=len(pred & gold); fp+=len(pred-gold); fn+=len(gold-pred)
precision=tp/(tp+fp) if tp+fp else 0
recall=tp/(tp+fn) if tp+fn else 0
print(json.dumps({'synthetic_only':True,'tp':tp,'fp':fp,'fn':fn,'precision':round(precision,4),'recall':round(recall,4),'f1':round(2*precision*recall/(precision+recall),4) if precision+recall else 0},indent=2))
