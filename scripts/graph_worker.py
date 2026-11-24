import time
import logging
import argparse
from app.graph import drain_outbox
from app.config import settings

logging.basicConfig(level=settings.log_level)
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Project SQL outbox records into Neo4j")
    parser.add_argument("--tenant", default=None, help="Only process this tenant (default: all tenants)")
    parser.add_argument("--batch", type=int, default=100)
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args()
    if args.batch < 1:
        parser.error("--batch must be positive")
    while True:
        try:
            result = drain_outbox(batch=args.batch, tenant=args.tenant)
            if result.get("processed"): logging.info("graph sync: %s", result)
        except Exception: logging.exception("graph sync cycle failed")
        if args.once:
            break
        time.sleep(3)
