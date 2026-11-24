"""Constrained, evidence-grounded consumer insight QA. No free-form SQL/Cypher generation."""
import re
from sqlalchemy import select
from app.models import Claim, Entity, Evidence
from app.services import insights

COUNTRIES = {"philippines": "Philippines", "菲律宾": "Philippines", "indonesia": "Indonesia", "印度尼西亚": "Indonesia", "vietnam": "Vietnam", "越南": "Vietnam", "thailand": "Thailand", "泰国": "Thailand", "malaysia": "Malaysia", "马来西亚": "Malaysia", "singapore": "Singapore", "新加坡": "Singapore"}


def parse_question(question: str):
    q = question.casefold()
    matches = [name for key, name in COUNTRIES.items() if key in q]
    country = matches[0] if matches else None
    age = re.search(r"(\d{2})\s*(?:[-–—~至到]\s*)(\d{2})\s*(?:岁|years?|yo)?", q)
    if age:
        amin, amax = int(age.group(1)), int(age.group(2))
        if amin > amax or amin < 13 or amax > 110: raise ValueError("invalid age range")
    else: amin = amax = None
    if not country and amin is None:
        raise ValueError("Question must specify a supported country or age range; unrestricted query not allowed")
    return {"country": country, "age_min": amin, "age_max": amax}


def answer(db, tenant: str, question: str, top_k: int = 5, evidence_limit: int = 3):
    filters = parse_question(question)
    report = insights(db, tenant, **filters, limit=top_k)
    result = {"question": question, "filters": filters, "sample_size": report["sample_size"],
              "needs": [], "selling_points": [], "citations": {}, "caveat": report["caveat"],
              "answer": "", "mode": "deterministic_evidence_grounded"}
    for key in ("needs", "selling_points"):
        for item in report[key]:
            ids = item["evidence_ids"][:evidence_limit]
            sources = db.scalars(select(Evidence).where(Evidence.tenant_id == tenant, Evidence.id.in_(ids))).all() if ids else []
            refs = []
            for e in sources:
                refs.append({"evidence_id": e.id, "source_id": e.source_id, "quote": e.excerpt[:500],
                             "language": e.language, "synthetic": bool(e.metadata_.get("synthetic"))})
            item = {k: v for k, v in item.items() if k != "evidence_ids"}
            item["citations"] = [r["evidence_id"] for r in refs]
            result[key].append(item)
            result["citations"].update({r["evidence_id"]: r for r in refs})
    if not report["sample_size"]:
        result["answer"] = "没有匹配的消费者样本，无法形成有证据支持的结论。"
    else:
        names = ", ".join(f'{x["name"]}（{x["consumer_count"]}人）' for x in result["needs"][:3]) or "无已接受需求声明"
        points = ", ".join(f'{x["name"]}（{x["consumer_count"]}人）' for x in result["selling_points"][:3]) or "无明确卖点声明"
        result["answer"] = f'在符合筛选条件的 {report["sample_size"]} 名样本中，主要需求为：{names}；明确提及的卖点为：{points}。以下附有原始证据引用。'
    result["synthetic_warning"] = "Synthetic evidence may be present; do not generalize to real markets."
    return result
