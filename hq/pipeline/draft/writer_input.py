"""Build the Writer's messages (CONTRACT_C §5). The Writer sees verified facts with ids, verified job quotes
(J1…), the document rules and two gold exemplars — NEVER the legacy `angle` notes or unconfirmed profile values."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths
from hq.llm.prompts import load_prompt
from hq.profile.facts import FactSheet, load_facts

EXEMPLAR_IDS = ("01-readyly", "06-pharmaand")


@dataclass(frozen=True)
class DocRules:
    kind: str
    min_words: int | None
    max_words: int | None
    paragraphs: tuple[int, int] | None
    salutation: str | None
    default_recipient: str | None
    signoff: bool
    subject: bool
    repo_link_max: int
    job_quote: bool = True      # the quality gate wants ≥ 1 verified posting quote (letters; not follow-ups/replies)


@lru_cache(maxsize=2)
def _doc_types(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def doc_config() -> dict[str, Any]:
    p = paths.CONFIG_DIR / "doc_types.yaml"
    return _doc_types(str(p), p.stat().st_mtime)


def doc_rules(kind: str) -> DocRules:
    t = (doc_config().get("types") or {}).get(kind)
    if t is None:
        raise ValueError(f"unknown document type {kind!r}")
    par = t.get("paragraphs")
    return DocRules(kind, t.get("min_words"), t.get("max_words"), tuple(par) if par else None, t.get("salutation"),
                    t.get("default_recipient"), bool(t.get("signoff")), bool(t.get("subject")),
                    int(t.get("repo_link_max", 1)), bool(t.get("job_quote", True)))


def rules_text(r: DocRules, recipient: str | None = None) -> str:
    lines = [f"Document type: {r.kind}."]
    if r.min_words or r.max_words:
        lines.append(f"Length: {r.min_words or 0}–{r.max_words} words (body only).")
    if r.paragraphs:
        lines.append(f"Paragraphs: {r.paragraphs[0]}–{r.paragraphs[1]}.")
    if r.salutation:
        lines.append("First sentence (kind salutation): " + r.salutation.format(recipient=recipient or r.default_recipient))
    else:
        lines.append("No salutation.")
    lines.append("Do not write a sign-off; it is added automatically." if r.signoff else "No sign-off.")
    if r.subject:
        lines.append('Also return "subject": a plain subject line under 90 characters.')
    lines.append(f"Link each GitHub repository at most {r.repo_link_max} time(s).")
    return "\n".join(lines)


def facts_block(sheet: FactSheet, *, include_contact: bool = False) -> str:
    out = []
    for f in sheet.facts:
        if f.status != "verified":
            continue
        if f.category == "contact" and not include_contact:
            continue
        tag = " (NOT-USED: only negated or aspirational)" if f.category == "not_used" else ""
        out.append(f"{f.id}: {f.text}{tag}")
    return "\n".join(out)


SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def quote_ids(quotes: list[str]) -> dict[str, str]:
    return {f"J{i + 1}": q for i, q in enumerate(quotes)}


def split_quotes(job_text: str, limit: int = 14) -> list[str]:
    """Fallback when no parsed requirements exist: the posting's sentences as quotes (exact substrings)."""
    parts = [p.strip() for p in SENT.split(" ".join(job_text.split())) if 25 <= len(p.strip()) <= 300]
    return parts[:limit]


@lru_cache(maxsize=1)
def exemplars() -> tuple[str, ...]:
    from hq.importer.legacy import load_letters

    try:
        letters = load_letters(paths.ROOT / "legacy" / "applications" / "letters.py")
    except (OSError, ValueError):
        return ()
    out = []
    for lid in EXEMPLAR_IDS:
        text = letters.get(lid)
        if text:
            body = text.split("Best regards,")[0].strip()
            out.append(body.replace("200+", "more than 200").replace("at least 200", "more than 200"))
    return tuple(out)


def writer_messages(*, org: str, role: str, doc_kind: str, job_quotes: dict[str, str], recipient: str | None = None,
                    task: str | None = None, feedback: list[str] | None = None,
                    sheet: FactSheet | None = None) -> list[dict[str, str]]:
    sheet = sheet or load_facts()
    r = doc_rules(doc_kind)
    ex = "\n\n---\n\n".join(exemplars())
    quotes = "\n".join(f"{k}: \"{v}\"" for k, v in job_quotes.items()) or "(none)"
    user = (f"ORGANISATION: {org}\nROLE: {role}\n\nFACTS:\n{facts_block(sheet)}\n\nJOB QUOTES:\n{quotes}\n\n"
            f"DOCUMENT RULES:\n{rules_text(r, recipient)}\n\n"
            f"STYLE EXAMPLES (tone only; do not copy):\n{ex or '(none)'}\n\n"
            f"TASK: {task or f'Write the {doc_kind.replace(chr(95), chr(32))} for this role.'}")
    if feedback:
        user += "\n\nFIX THESE PROBLEMS FROM YOUR LAST DRAFT:\n" + "\n".join(f"- {f}" for f in feedback)
    return [{"role": "system", "content": load_prompt("writer")}, {"role": "user", "content": user}]
