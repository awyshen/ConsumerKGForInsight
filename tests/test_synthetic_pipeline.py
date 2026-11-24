from scripts.synthetic_pipeline import generate, evaluate, extract_rule_based, read_jsonl

def test_deterministic(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b'
    generate(30,17,a); generate(30,17,b)
    assert (a/'interviews.jsonl').read_bytes()==(b/'interviews.jsonl').read_bytes()
    assert (a/'events.jsonl').read_bytes()==(b/'events.jsonl').read_bytes()

def test_provenance_and_no_real_personal_info(tmp_path):
    generate(25,9,tmp_path)
    rows=list(read_jsonl(tmp_path/'interviews.jsonl'))
    assert all(r['synthetic'] and r['consumer_key'].startswith('SYN-C-') for r in rows)
    assert len({r['source_id'] for r in rows})==25

def test_negation():
    assert extract_rule_based('I need battery lasts all day. I do not prioritize clear low-light photos.') == ['Battery endurance']

def test_baseline_eval(tmp_path):
    generate(40,21,tmp_path)
    r=evaluate(tmp_path)
    assert r['samples']==40 and r['f1']==1
