"""Golden fact-gate check for the go-live checklist (CONTRACT_D §5): the gold pairs (every bad sentence type
caught at ≥ 80 % recall, zero false blocks on good sentences) plus fixed probes that must always be blocked and
honest sentences that must always pass. Deterministic and fast (< 1 s)."""
from __future__ import annotations

import json
from typing import Any

from hq import settings as paths
from hq.pipeline.gates.fact_deterministic import CheckContext, check_sentence
from hq.util.timeutil import now_iso

GOLD = paths.ROOT / "tests" / "fixtures" / "factcheck_pairs.jsonl"
PROBES = [
    ("I deployed my recommender on AWS.", "BANNED_CLAIM"),
    ("I trained a churn model with 95% accuracy.", "BANNED_CLAIM"),
    ("I have 3 years of Python experience.", "NUM_NOT_IN_FACTS"),
    ("I used PyTorch to build a CNN for image tagging.", "TECH_NOT_WHITELISTED"),
    ("Read more at https://evil.example.com/prerit.", "URL_NOT_IN_FACTS"),
    ("I built several end-to-end ML pipelines.", "PLURAL_OVERGEN"),
    ("My CGPA is 8.9.", "PROFILE_UNCONFIRMED"),
]
HONEST = [
    "I haven't deployed anything to production yet.",
    "My GitHub is https://github.com/Preritsangwan17.",
    "I kept users with more than 200 ratings and books with at least 50 ratings.",
    "The model returns the 5 most similar books.",
]


def run() -> dict[str, Any]:
    rows = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()] if GOLD.exists() else []
    bad = [r for r in rows if r["label"] != "ok"]
    ok = [r for r in rows if r["label"] == "ok"]
    caught = sum(1 for r in bad if check_sentence(r["text"], context=CheckContext(previous=r["context"])))
    false_blocks = [r["text"] for r in ok if check_sentence(r["text"], context=CheckContext(previous=r["context"]))]
    probe_misses = [s for s, rule in PROBES if rule not in {v.rule for v in check_sentence(s)}]
    honest_blocks = [s for s in HONEST if check_sentence(s)]
    recall = caught / len(bad) if bad else 0.0
    passed = bool(rows) and recall >= 0.8 and not false_blocks and not probe_misses and not honest_blocks
    return {"passed": passed, "recall": round(recall, 3), "gold": len(rows), "false_blocks": false_blocks[:5],
            "probe_misses": probe_misses, "honest_blocks": honest_blocks, "ran_at": now_iso()}
