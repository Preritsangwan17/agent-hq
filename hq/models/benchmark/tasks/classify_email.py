"""classify_email: 41 synthetic replies. `accuracy` on the label; `recall` = interview + offer recall
(floor 0.95); lock precision/recall in the details."""
from __future__ import annotations

from typing import Any

from hq.llm.prompts import load_prompt
from hq.models.benchmark.scoring import Metrics, prf
from hq.models.benchmark.tasks import BenchTask, Case
from hq.models.benchmark.tasks._fixtures import jsonl

CRITICAL = {"interview_invite", "offer"}


def cases(quick: bool) -> list[Case]:
    rows = jsonl("emails_synthetic.jsonl")
    if quick:
        rows = [r for r in rows if r["label"] in CRITICAL] + [r for r in rows if r["label"] not in CRITICAL][::3]
    return [Case(r["id"], [{"role": "system", "content": load_prompt("classify_email")},
                           {"role": "user", "content": f"FROM: {r['from']}\nSUBJECT: {r['subject']}\n\n{r['body']}"}],
                 {"label": r["label"], "lock": r["lock_expected"]}, {}) for r in rows]


def score(cs: list[Case], outputs: list[Any]) -> Metrics:
    correct = crit_hit = crit_n = 0
    ltp = lfp = lfn = 0
    per = []
    for c, o in zip(cs, outputs):
        label = o.get("label") if isinstance(o, dict) else None
        lock = bool(o.get("lock")) if isinstance(o, dict) else False
        correct += label == c.gold["label"]
        if c.gold["label"] in CRITICAL:
            crit_n += 1
            crit_hit += label == c.gold["label"]
        if c.gold["lock"] and lock:
            ltp += 1
        elif c.gold["lock"]:
            lfn += 1
        elif lock:
            lfp += 1
        if label != c.gold["label"] or lock != c.gold["lock"]:
            per.append({"id": c.id, "gold": c.gold, "pred": {"label": label, "lock": lock}})
    lp, lr, _ = prf(ltp, lfp, lfn)
    n = len(cs)
    return Metrics(n, accuracy=round(correct / n, 4) if n else 0.0, precision=lp,
                   recall=round(crit_hit / crit_n, 4) if crit_n else None, f1=None,
                   details={"lock_precision": lp, "lock_recall": lr, "errors": per})


TASK = BenchTask("classify_email", "email_class", 200, cases, score)
