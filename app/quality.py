"""Evaluation for multilingual extraction against manually reviewed JSONL gold labels."""
from collections import Counter
from app.knowledge_pipeline import norm


def evaluate(gold: list[dict], predicted: list[dict]):
    if len(gold) != len(predicted): raise ValueError("gold/prediction length mismatch")
    tp = fp = fn = 0
    by_language = {}
    for g, p in zip(gold, predicted):
        if g.get("source_id") != p.get("source_id"): raise ValueError("source alignment mismatch")
        language = g.get("language", "unknown")
        counts = by_language.setdefault(language, {"tp": 0, "fp": 0, "fn": 0})
        def keys(x):
            return {(m["entity_type"], norm(m["canonical_name"]), m.get("polarity", "positive")) for m in x.get("mentions", [])}
        a, b = keys(g), keys(p)
        t, f, n = len(a & b), len(b-a), len(a-b)
        tp += t; fp += f; fn += n
        counts["tp"] += t; counts["fp"] += f; counts["fn"] += n
    def score(t, f, n):
        precision = t/(t+f) if t+f else 0.0
        recall = t/(t+n) if t+n else 0.0
        return {"precision": round(precision, 4), "recall": round(recall, 4),
                "f1": round(2*precision*recall/(precision+recall), 4) if precision+recall else 0.0,
                "tp": t, "fp": f, "fn": n}
    return {"micro": score(tp, fp, fn), "by_language": {k: score(v["tp"], v["fp"], v["fn"]) for k, v in by_language.items()},
            "note": "synthetic benchmark scores do not establish real-world accuracy"}
