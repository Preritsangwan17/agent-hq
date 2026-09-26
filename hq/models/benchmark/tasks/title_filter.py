"""title_filter: 189 scanned titles (incl. "Internal"/"International" traps), classified in batches of 25."""
from __future__ import annotations

from typing import Any

from hq.llm.prompts import load_prompt
from hq.models.benchmark.scoring import Metrics, prf
from hq.models.benchmark.tasks import BenchTask, Case
from hq.models.benchmark.tasks._fixtures import jsonl

BATCH = 25


def cases(quick: bool) -> list[Case]:
    rows = jsonl("titles_gold.jsonl")
    if quick:
        rows = rows[::3]
    out = []
    for b in range(0, len(rows), BATCH):
        chunk = rows[b:b + BATCH]
        lines = "\n".join(f"{i}. {r['title']} — {r.get('company', '')} ({r.get('location', '')})"
                          for i, r in enumerate(chunk))
        out.append(Case(f"batch-{b // BATCH}", [{"role": "system", "content": load_prompt("title_filter")},
                                                {"role": "user", "content": f"TITLES:\n{lines}"}],
                        [bool(r["target"]) for r in chunk], {"titles": [r["title"] for r in chunk]}))
    return out


def score(cs: list[Case], outputs: list[Any]) -> Metrics:
    tp = fp = fn = tn = 0
    misses = []
    for c, o in zip(cs, outputs):
        got = {}
        if isinstance(o, dict):
            for r in o.get("results") or []:
                if isinstance(r, dict) and isinstance(r.get("i"), int):
                    got[r["i"]] = bool(r.get("target"))
        for i, gold in enumerate(c.gold):
            pred = got.get(i)
            if pred is None:
                pred = False
            if gold and pred:
                tp += 1
            elif gold:
                fn += 1
                misses.append(("missed", c.meta["titles"][i]))
            elif pred:
                fp += 1
                misses.append(("false", c.meta["titles"][i]))
            else:
                tn += 1
    p, r, f = prf(tp, fp, fn)
    n = tp + fp + fn + tn
    return Metrics(n, accuracy=round((tp + tn) / n, 4) if n else 0.0, precision=p, recall=r, f1=f,
                   details={"errors": misses[:60]})


TASK = BenchTask("title_filter", "title_filter", 1200, cases, score)
