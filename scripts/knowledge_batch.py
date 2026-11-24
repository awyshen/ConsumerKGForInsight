"""Run: python -m scripts.knowledge_batch --input data/synthetic/interviews.jsonl --limit 1200"""
import argparse
import asyncio
import json
from pathlib import Path
from app.db import Base, engine, SessionLocal
from app.knowledge_pipeline import InterviewJob, process

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/synthetic/interviews.jsonl")
    parser.add_argument("--limit", type=int, default=1200)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--mode", choices=["rules", "llm"], default="rules")
    args = parser.parse_args()
    Base.metadata.create_all(engine)  # Local bootstrap only; use migrations in production.
    counts = {"processed": 0, "accepted": 0, "review": 0, "failed": 0}
    with Path(args.input).open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= args.limit: break
            row = json.loads(line)
            job = InterviewJob(**{k: row[k] for k in ("source_id", "consumer_key", "country", "age", "language", "excerpt", "synthetic")}, mode=args.mode)
            try:
                with SessionLocal() as db:
                    result = await process(db, args.tenant, job)
                counts["processed"] += 1
                counts["accepted"] += result["accepted"]
                counts["review"] += len(result["review"])
            except Exception as exc:
                counts["failed"] += 1
                print(json.dumps({"source_id": job.source_id, "error": str(exc)}, ensure_ascii=False))
    print(json.dumps(counts, ensure_ascii=False))

if __name__ == "__main__": asyncio.run(main())
