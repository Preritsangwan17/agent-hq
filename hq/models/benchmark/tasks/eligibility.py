"""eligibility: 13 parseable postings with hand-labelled verdicts. A false "eligible" on an ineligible posting
weighs ×3; eligible vs eligible_gaps earns partial credit; quotes must be exact substrings (grounding)."""
from __future__ import annotations

from typing import Any

from hq.llm.prompts import load_prompt
from hq.models.benchmark.scoring import Metrics, grounded
from hq.models.benchmark.tasks import BenchTask, Case
from hq.models.benchmark.tasks._fixtures import job_text, jsonl

GOLD_MAP = {"borderline": "needs_info"}


def cases(quick: bool) -> list[Case]:
    rows = [r for r in jsonl("eligibility_gold.jsonl") if r["verdict"] != "unparseable"]
    if quick:
        rows = rows[:7]
    out = []
    for r in rows:
        text = job_text(r["fixture"])
        out.append(Case(r["fixture"], [{"role": "system", "content": load_prompt("eligibility")},
                                       {"role": "user", "content": f"POSTING:\n{text[:12000]}"}],
                        {"verdict": GOLD_MAP.get(r["verdict"], r["verdict"]), "quotes": r["quotes"]}, {"text": text}))
    return out


def credit(gold: str, pred: str | None) -> float:
    if pred == gold:
        return 1.0
    if {gold, pred} == {"eligible", "eligible_gaps"}:
        return 0.75
    if gold == "needs_info" and pred in ("ineligible", "eligible_gaps"):
        return 0.5
    return 0.0


def score(cs: list[Case], outputs: list[Any]) -> Metrics:
    num = den = 0.0
    q_ok = q_n = 0
    false_eligible = 0
    per = []
    for c, o in zip(cs, outputs):
        gold = c.gold["verdict"]
        pred = o.get("verdict") if isinstance(o, dict) else None
        w = 3.0 if gold == "ineligible" else 1.0
        cr = credit(gold, pred)
        num += w * cr
        den += w
        if gold == "ineligible" and pred in ("eligible", "eligible_gaps"):
            false_eligible += 1
        reqs = [r for r in (o or {}).get("requirements") or [] if isinstance(r, dict)] if isinstance(o, dict) else []
        ok = sum(grounded(r.get("quote"), c.meta["text"]) for r in reqs)
        q_ok += ok
        q_n += len(reqs)
        per.append({"id": c.id, "gold": gold, "pred": pred, "credit": cr, "grounded": f"{ok}/{len(reqs)}",
                    "confidence": (o or {}).get("confidence") if isinstance(o, dict) else None})
    verdict_acc = num / den if den else 0.0
    grounding = q_ok / q_n if q_n else 1.0
    return Metrics(len(cs), accuracy=round(0.85 * verdict_acc + 0.15 * grounding, 4), precision=round(grounding, 4),
                   details={"cases": per, "verdict_weighted_accuracy": round(verdict_acc, 4),
                            "false_eligible": false_eligible})


TASK = BenchTask("eligibility", "eligibility", 700, cases, score)
