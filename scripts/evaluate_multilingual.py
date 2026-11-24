"""Usage: python -m scripts.evaluate_multilingual gold.jsonl predictions.jsonl"""
import json
import sys
from app.quality import evaluate

def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

if __name__ == "__main__":
    if len(sys.argv) != 3: raise SystemExit("usage: evaluate_multilingual GOLD.jsonl PRED.jsonl")
    print(json.dumps(evaluate(load(sys.argv[1]), load(sys.argv[2])), indent=2, ensure_ascii=False))
