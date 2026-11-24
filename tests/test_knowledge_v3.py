from app.knowledge_pipeline import rule_extract, resolve, verify_extraction, Extraction, Mention

def test_multilingual_and_negation():
    x = rule_extract("I need battery lasts all day. I do not prioritize clear low-light photos.")
    positives = {m.canonical_name for m in x.mentions if m.polarity == 'positive'}
    assert 'Battery endurance' in positives
    assert 'Camera quality' not in positives
    assert any(m.canonical_name == 'Camera quality' and m.polarity == 'negative' for m in x.mentions)
    assert 'Camera quality' in {m.canonical_name for m in rule_extract('我需要夜景拍照清晰', 'zh').mentions}
    assert 'Battery endurance' in {m.canonical_name for m in rule_extract('matagal ang battery', 'tl').mentions}

def test_hallucination_rejected():
    x = Extraction(language='en', mentions=[Mention(entity_type='Need', surface='battery lasts all day', canonical_name='Battery endurance', quote='fake text', confidence=.99)])
    accepted, review = verify_extraction(x, 'I need a phone.')
    assert not accepted and len(review) == 1

def test_pipeline_qa(client):
    p = {"source_id":"s1", "consumer_key":"c1", "country":"Philippines", "age":28,
         "excerpt":"I need battery lasts all day and clear low-light photos.", "language":"en", "synthetic":True}
    a = client.post('/v1/knowledge/interviews', json=p)
    assert a.status_code == 200, a.text
    assert a.json()['accepted'] >= 2
    assert client.post('/v1/knowledge/interviews', json=p).json()['claim_ids'] == a.json()['claim_ids']
    r = client.post('/v1/qa/ask', json={'question':'2026年菲律宾26-30岁消费者购机需求是什么？'})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result['sample_size'] == 1
    assert result['needs'] and result['citations']
    assert result['citations'][next(iter(result['citations']))]['source_id'] == 's1'

def test_unknown_question_rejected(client):
    assert client.post('/v1/qa/ask', json={'question':'告诉我所有市场的全部信息'}).status_code == 422
