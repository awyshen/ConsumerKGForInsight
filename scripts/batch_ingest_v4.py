"""Resumable JSONL ingestion. Usage: python -m scripts.batch_ingest_v4 interviews.jsonl --mode rules.
Each record is validated as InterviewJob. Source ID and claims are idempotent; batch is resumable.
"""
import argparse
import asyncio
import json
import logging
from sqlalchemy import select
from app.db import SessionLocal
from app.models import BatchJob
from app.knowledge_pipeline import InterviewJob, process

log = logging.getLogger(__name__)

async def run(path, tenant, mode, max_records):
    ok = bad = 0
    with open(path, encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            if line_no > max_records: break
            if not line.strip(): continue
            try:
                raw = json.loads(line)
                raw["mode"] = mode
                job = InterviewJob.model_validate(raw)
                with SessionLocal() as db:
                    # Record-level atomicity. Re-running is safe for accepted facts.
                    await process(db, tenant, job)
                ok += 1
            except Exception:
                bad += 1
                log.exception("record %s failed", line_no)
    return {"processed": ok, "failed": bad}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--mode", choices=["rules", "llm"], default="rules")
    parser.add_argument("--max-records", type=int, default=100000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asyncio.run(run(args.file, args.tenant, args.mode, args.max_records))))
