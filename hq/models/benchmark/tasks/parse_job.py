"""parse_job: the 14 saved LinkedIn postings (offline). Scores company, title, city, the unparseable page and
the share of requirement quotes that are exact substrings of the posting."""
from __future__ import annotations

from typing import Any

from hq.llm.prompts import load_prompt
from hq.models.benchmark.scoring import Metrics, grounded, similar
from hq.models.benchmark.tasks import BenchTask, Case
from hq.models.benchmark.tasks._fixtures import job_header, job_text, jsonl


def cases(quick: bool) -> list[Case]:
    rows = jsonl("eligibility_gold.jsonl")
    if quick:
        rows = rows[:6] + [r for r in rows if r["verdict"] == "unparseable"]
    out = []
    for r in rows:
        text = job_text(r["fixture"])
        head = job_header(text)
        city = (head.get("location") or "").split(",")[0].strip() or None
        if city == "India":
            city = None
        out.append(Case(r["fixture"], [{"role": "system", "content": load_prompt("parse_job")},
                                       {"role": "user", "content": f"POSTING:\n{text[:12000]}"}],
                        {"company": head.get("company") or None, "title": head.get("title") or None, "city": city,
                         "parse_ok": r["verdict"] != "unparseable"}, {"text": text}))
    return out


def score(cs: list[Case], outputs: list[Any]) -> Metrics:
    per, quotes_ok, quotes_n = [], 0, 0
    for c, o in zip(cs, outputs):
        g = c.gold
        if not isinstance(o, dict):
            per.append({"id": c.id, "score": 0.0, "error": "no output"})
            continue
        if not g["parse_ok"]:
            s = 1.0 if o.get("parse_ok") is False else 0.0
            per.append({"id": c.id, "score": s, "parse_ok": o.get("parse_ok")})
            continue
        checks = [bool(o.get("parse_ok", True)), similar(o.get("company"), g["company"], 90),
                  similar(o.get("title"), g["title"], 85)]
        if g["city"]:
            checks.append(similar((o.get("location") or {}).get("city"), g["city"], 85))
        reqs = [r for r in o.get("requirements") or [] if isinstance(r, dict)]
        q_ok = sum(grounded(r.get("quote"), c.meta["text"]) for r in reqs)
        quotes_ok += q_ok
        quotes_n += len(reqs)
        ground = q_ok / len(reqs) if reqs else 1.0
        s = 0.8 * sum(checks) / len(checks) + 0.2 * ground
        per.append({"id": c.id, "score": round(s, 3), "checks": checks, "grounding": round(ground, 3)})
    acc = sum(p["score"] for p in per) / len(per) if per else 0.0
    return Metrics(len(cs), accuracy=round(acc, 4),
                   precision=round(quotes_ok / quotes_n, 4) if quotes_n else None,
                   details={"cases": per, "quote_grounding": quotes_ok / quotes_n if quotes_n else None})


TASK = BenchTask("parse_job", "job_parse", 900, cases, score)
