"""write_paragraph: 5 real targets (Readyly, Stripe, pharma&, EPFL, TEEP-CCU) built from facts.yaml and the job
text only. Score = 0.7 × share of sentences with zero deterministic fact-gate violations + 0.2 × word-count
compliance + 0.1 × no clichés."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hq import settings as paths
from hq.models.benchmark.scoring import Metrics
from hq.models.benchmark.tasks import BenchTask, Case
from hq.models.benchmark.tasks._fixtures import job_text
from hq.pipeline.draft.writer_input import doc_rules, split_quotes, writer_messages
from hq.pipeline.gates.fact_deterministic import check_document
from hq.pipeline.gates.quality import cliche_hits

TARGETS = ("01-readyly", "05-stripe", "06-pharmaand", "10-epfl", "07-nccu-teep")
FIXTURE_TEXT = {"01-readyly": "jobs/linkedin_4468467368.txt", "06-pharmaand": "jobs/linkedin_4469849859.txt"}


def _items() -> dict[str, dict[str, Any]]:
    from hq.importer.legacy import load_items

    return {i["id"]: i for i in load_items(paths.ROOT / "legacy" / "applications")}


def cases(quick: bool) -> list[Case]:
    items = _items()
    ids = TARGETS[:3] if quick else TARGETS
    out = []
    for lid in ids:
        it = items[lid]
        text = job_text(FIXTURE_TEXT[lid]) if lid in FIXTURE_TEXT else f"{it['role']}. {it.get('about', '')}"
        quotes = {f"J{i + 1}": q for i, q in enumerate(split_quotes(text, 10))}
        msgs = writer_messages(org=it["company"], role=it["role"], doc_kind="paragraph", job_quotes=quotes,
                               task="Write one paragraph explaining why Prerit is a good match for this role.")
        out.append(Case(lid, msgs, None, {"quotes": quotes}))
    return out


def score(cs: list[Case], outputs: list[Any]) -> Metrics:
    r = doc_rules("paragraph")
    per = []
    total_s = clean_s = 0
    for c, o in zip(cs, outputs):
        sents = [s for s in (o or {}).get("sentences", []) if isinstance(s, dict) and s.get("text")] \
            if isinstance(o, dict) else []
        if not sents:
            per.append({"id": c.id, "score": 0.0, "error": "no sentences"})
            continue
        report = check_document(sents, job_quotes=c.meta["quotes"], require_citations=True)
        clean = sum(1 for s in report.sentences if s["passed"])
        words = len(re.findall(r"\b\w[\w'-]*\b", " ".join(s["text"] for s in sents)))
        length_ok = (r.min_words or 0) <= words <= (r.max_words or 10 ** 6)
        cliches = sum(len(cliche_hits(s["text"])) for s in sents)
        s = 0.7 * clean / len(sents) + 0.2 * length_ok + 0.1 * (cliches == 0)
        total_s += len(sents)
        clean_s += clean
        per.append({"id": c.id, "score": round(s, 3), "sentences": len(sents), "clean": clean, "words": words,
                    "cliches": cliches, "violations": report.violations[:10]})
    acc = sum(p["score"] for p in per) / len(per) if per else 0.0
    return Metrics(len(cs), accuracy=round(acc, 4), precision=round(clean_s / total_s, 4) if total_s else None,
                   details={"cases": per})


TASK = BenchTask("write_paragraph", "draft", 900, cases, score)
