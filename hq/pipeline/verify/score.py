"""Fit score 0–100 (PLAN §4): role relevance 25, skills 20, eligibility confidence 15, pay ratio 15, source prior 10,
deadline 5, location 5, programme benefits 5. Skill gaps lower this score; they never make Prerit ineligible."""
from __future__ import annotations

import re
from typing import Any

from hq.pipeline.gates.fact_deterministic import lexicon

ROLE_POINTS = {"ml": 25, "research": 23, "data": 21, "software": 18, "other": 6}
SOURCE_PRIOR = {"program_page": 10, "greenhouse": 8, "lever": 8, "ashby": 8, "manual": 6, "email_alert": 6, "sim": 7}


def skill_overlap(text: str) -> tuple[int, int, list[str], list[str]]:
    lex = lexicon()
    low = (text or "").lower()
    have = sorted({name for name, p in lex.whitelist if p.search(low)})
    gaps = sorted({term for term, p in lex.known_tech if p.search(low)})
    return len(have), len(gaps), have, gaps


def fit_score(opp: dict[str, Any], *, text: str, eligibility_confidence: float | None,
              eligibility_status: str, deadline: str) -> tuple[int, dict[str, Any]]:
    b: dict[str, Any] = {}
    title = f"{opp.get('title', '')} {opp.get('role_type') or ''}"
    b["role"] = ROLE_POINTS.get(opp.get("role_type") or "other", 6)
    if re.search(r"machine learning|\bml\b|\bai\b|data science|recommend", title, re.I):
        b["role"] = min(25, b["role"] + 2)
    n_have, n_gap, have, gaps = skill_overlap(text)
    b["skills"] = round(min(20, 6 + 3 * n_have) * (1 - min(0.6, 0.12 * n_gap)))
    b["skills_matched"], b["skill_gaps"] = have, gaps
    conf = eligibility_confidence if eligibility_confidence is not None else 0.5
    b["eligibility"] = round(15 * conf * (0.8 if eligibility_status == "eligible_gaps" else 1.0))
    ratio = opp.get("pay_ratio")
    status = opp.get("pay_status")
    benefits = opp.get("benefits") or {}
    if status == "listed" and ratio is not None:
        b["pay"] = 15 if ratio >= 1.5 else 11 if ratio >= 1.0 else 3
    elif benefits.get("housing") and benefits.get("meals"):
        b["pay"] = 12
    else:
        b["pay"] = 5
    kind = (opp.get("canonical_key") or "").split(":", 1)[0]
    b["source"] = SOURCE_PRIOR.get(kind, 6)
    b["deadline"] = {"open": 5, "rolling": 3}.get(deadline, 0)
    mode, country = opp.get("work_mode"), opp.get("country_iso2")
    b["location"] = 5 if mode == "remote" else 4 if country == "IN" else 3
    b["program"] = 5 if opp.get("kind") in ("program", "fellowship", "research_internship") or \
        (benefits.get("housing") or benefits.get("travel")) else 2
    total = sum(v for k, v in b.items() if isinstance(v, (int, float)) and k not in ("skills_matched", "skill_gaps"))
    return int(max(0, min(100, total))), b
