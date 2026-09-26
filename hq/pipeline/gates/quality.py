"""Quality gate (PLAN §7, CONTRACT_C §5): names the organisation and cites ≥ 1 verified job quote, zero clichés,
correct length / salutation / sign-off for the document type, a specificity rubric ≥ 3/5 (LLM, scored elsewhere and
passed in) and word-shingle Jaccard < 0.6 against the last 20 letters so letters don't become templates."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from hq import settings as paths
from hq.pipeline.draft.writer_input import doc_rules

JACCARD_MAX = 0.6
RUBRIC_MIN = 3
WORD = re.compile(r"\b\w[\w'-]*\b")
URL = re.compile(r"https?://\S+")


@lru_cache(maxsize=2)
def _cliches(path: str, mtime: float) -> tuple[re.Pattern, ...]:
    items = yaml.safe_load(Path(path).read_text()) or []
    return tuple(re.compile(re.escape(str(c)) if not str(c).startswith("re:") else str(c)[3:], re.IGNORECASE)
                 for c in items)


def cliche_patterns() -> tuple[re.Pattern, ...]:
    p = paths.CONFIG_DIR / "cliches.yaml"
    return _cliches(str(p), p.stat().st_mtime)


def cliche_hits(text: str) -> list[str]:
    t = text.replace("’", "'")
    return [m.group(0) for pat in cliche_patterns() if (m := pat.search(t))]


def words(text: str) -> int:
    return len(WORD.findall(URL.sub(" ", text)))


def shingles(text: str, k: int = 5) -> set[tuple[str, ...]]:
    toks = [w.lower() for w in WORD.findall(URL.sub(" ", text))]
    return {tuple(toks[i:i + k]) for i in range(max(0, len(toks) - k + 1))}


def jaccard(a: str, b: str, k: int = 5) -> float:
    sa, sb = shingles(a, k), shingles(b, k)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class QualityReport:
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)

    def failures(self) -> list[str]:
        return [c["message"] for c in self.checks if not c["passed"]]


def check_quality(sentences: list[dict[str, Any]], *, doc_kind: str, org: str, recent_texts: Iterable[str] = (),
                  rubric_score: float | None = None, recipient: str | None = None) -> QualityReport:
    rules = doc_rules(doc_kind)
    body_sents = [s for s in sentences if s.get("kind") not in ("salutation", "closing")]
    body = " ".join(s["text"] for s in body_sents)
    full = " ".join(s["text"] for s in sentences)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str) -> None:
        checks.append({"check": name, "passed": bool(ok), "message": message})

    org_core = re.sub(r"[^\w& ]", "", re.sub(r"\s*\([^)]*\)", "", org).split(",")[0]).strip().lower()
    add("names_org", bool(org_core) and org_core in full.lower().replace("’", "'"),
        f"Name the organisation ({org.split(',')[0]}) in the text")
    add("job_quote", any(s.get("job_quote_ids") for s in sentences),
        "Refer to at least one verified quote from the posting")
    hits = sorted({h.lower() for s in sentences for h in cliche_hits(s["text"])})
    add("no_cliches", not hits, "Remove clichés: " + ", ".join(hits) if hits else "No clichés")
    n = words(body)
    lo, hi = rules.min_words or 0, rules.max_words or 10 ** 6
    add("length", lo <= n <= hi, f"Body is {n} words; {doc_kind} needs {lo}–{hi}")
    if rules.salutation:
        want = rules.salutation.split("{")[0].strip()
        first = sentences[0]["text"] if sentences else ""
        add("salutation", first.startswith(want), f"Start with '{rules.salutation.format(recipient=recipient or rules.default_recipient)}'")
    else:
        add("salutation", not (sentences and sentences[0].get("kind") == "salutation"), "No salutation for this type")
    signoffs = [s for s in sentences if re.search(r"\b(best regards|sincerely|kind regards|yours)\b", s["text"], re.I)]
    add("signoff", not signoffs, "Leave the sign-off out; HQ adds the fixed one")
    links = len(re.findall(r"github\.com/Preritsangwan17/[\w-]+", full))
    by_repo: dict[str, int] = {}
    for m in re.findall(r"github\.com/Preritsangwan17/([\w-]+)", full):
        by_repo[m] = by_repo.get(m, 0) + 1
    add("repo_links", all(v <= rules.repo_link_max for v in by_repo.values()),
        f"Link each repository at most {rules.repo_link_max} time(s) (found {links})")
    worst = max((jaccard(body, t) for t in recent_texts if t), default=0.0)
    add("not_template", worst < JACCARD_MAX, f"Too similar to a recent letter (Jaccard {worst:.2f} ≥ {JACCARD_MAX})")
    if rubric_score is not None:
        add("specificity", rubric_score >= RUBRIC_MIN,
            f"Specificity {rubric_score:.1f}/5 — add concrete details about this role (needs ≥ {RUBRIC_MIN})")
    return QualityReport(all(c["passed"] for c in checks), checks)
