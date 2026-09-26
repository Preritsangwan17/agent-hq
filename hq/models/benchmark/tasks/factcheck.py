"""factcheck: 158 labelled sentences (32 unsupported with rule + span, 126 ok) in batches of 8, each with its
previous sentence. `recall` = share of unsupported sentences flagged (floor 0.90); `precision` = share of ok
sentences passed (floor 0.85); `partial` counts as flagged."""
from __future__ import annotations

from typing import Any

from hq.llm.prompts import load_prompt
from hq.models.benchmark.scoring import Metrics, prf
from hq.models.benchmark.tasks import BenchTask, Case
from hq.models.benchmark.tasks._fixtures import jsonl
from hq.pipeline.draft.writer_input import facts_block
from hq.profile.facts import load_facts

BATCH = 8


def cases(quick: bool) -> list[Case]:
    rows = jsonl("factcheck_pairs.jsonl")
    if quick:
        bad = [r for r in rows if r["label"] != "ok"]
        ok = [r for r in rows if r["label"] == "ok"][::4]
        rows = sorted(bad[::2] + ok, key=lambda r: r["id"])
    facts = facts_block(load_facts())
    out = []
    for b in range(0, len(rows), BATCH):
        chunk = rows[b:b + BATCH]
        lines = "\n\n".join(f"[{i}] PREVIOUS: {r['context'] or '(start)'}\n[{i}] SENTENCE: {r['text']}"
                            for i, r in enumerate(chunk))
        out.append(Case(f"batch-{b // BATCH}", [{"role": "system", "content": load_prompt("fact_checker")},
                                                {"role": "user", "content": f"FACTS:\n{facts}\n\nSENTENCES:\n{lines}"}],
                        [r["label"] != "ok" for r in chunk], {"ids": [r["id"] for r in chunk]}))
    return out


def score(cs: list[Case], outputs: list[Any]) -> Metrics:
    tp = fp = fn = tn = 0
    errors = []
    for c, o in zip(cs, outputs):
        got: dict[int, str] = {}
        if isinstance(o, dict):
            for r in o.get("results") or []:
                if isinstance(r, dict) and isinstance(r.get("i"), int):
                    got[r["i"]] = str(r.get("verdict"))
        for i, bad in enumerate(c.gold):
            flagged = got.get(i) in ("unsupported", "partial")
            if bad and flagged:
                tp += 1
            elif bad:
                fn += 1
                errors.append(("missed", c.meta["ids"][i]))
            elif flagged:
                fp += 1
                errors.append(("false_block", c.meta["ids"][i]))
            else:
                tn += 1
    _, recall, f1 = prf(tp, fp, fn)
    ok_precision = round(tn / (tn + fp), 4) if tn + fp else 0.0
    n = tp + fp + fn + tn
    return Metrics(n, accuracy=round((tp + tn) / n, 4) if n else 0.0, precision=ok_precision, recall=recall, f1=f1,
                   details={"tp": tp, "fp": fp, "fn": fn, "tn": tn, "errors": errors[:60]})


TASK = BenchTask("factcheck", "factcheck", 1400, cases, score)
