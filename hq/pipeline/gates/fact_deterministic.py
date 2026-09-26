"""Deterministic layer of the fact gate (PLAN "Pipeline and gates" §6a, CONTRACT_B §2).

Runs on every outbound string. A sentence is split into clauses; claim rules skip clauses that are negated
("I haven't used SQL yet") or aspirational ("keen to learn PyTorch", "interested in how…"), because those are
honest statements about what Prerit has NOT done or wants to do. Everything else must be backed by the fact
sheet, a confirmed profile field or a verified job quote the sentence cites.

Rules: NUM_NOT_IN_FACTS, URL_NOT_IN_FACTS, BANNED_CLAIM, UNVERIFIABLE_SELF_CLAIM, INVENTED_RESULT, PLURAL_OVERGEN,
FACT_WORDING, ANGLE_LEAK (lexicons in config/banned_claims.yaml), TECH_NOT_WHITELISTED (config/tech_terms.yaml),
WRONG_PROJECT, PROFILE_UNCONFIRMED, and — when the Writer supplies citations — CITATION_MISSING,
UNKNOWN_FACT_ID and JOB_CLAIM_UNQUOTED.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from hq import settings as paths
from hq.profile.facts import Fact, FactSheet, load_facts


@dataclass(frozen=True)
class Violation:
    rule: str
    span: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class CheckContext:
    """What a sentence may lean on besides the fact sheet."""
    previous: str | None = None                      # the previous sentence (project context)
    job_quotes: dict[str, str] = field(default_factory=dict)   # J1 → exact quote from the posting
    confirmed_fields: dict[str, str] = field(default_factory=dict)
    require_citations: bool = False                  # Writer output must cite fact ids on claim sentences
    kind: str | None = None                          # claim|motivation|job_reference|logistics|salutation|closing


# ── lexicons ──────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Lexicon:
    rules: tuple[tuple[str, bool, str, tuple[re.Pattern, ...]], ...]   # (rule, claims_only, message, patterns)
    whitelist: tuple[tuple[str, re.Pattern], ...]
    known_tech: tuple[tuple[str, re.Pattern], ...]


def _compile(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


@lru_cache(maxsize=4)
def _lexicon_cached(config_dir: str, mtimes: tuple[float, ...]) -> Lexicon:
    d = Path(config_dir)
    banned = yaml.safe_load((d / "banned_claims.yaml").read_text()) or {}
    tech = yaml.safe_load((d / "tech_terms.yaml").read_text()) or {}
    rules = tuple((name, bool(spec.get("claims_only", True)), str(spec.get("message", name)),
                   tuple(_compile(p) for p in spec.get("patterns", [])))
                  for name, spec in (banned.get("rules") or {}).items())
    whitelist = tuple((t, _compile(rf"\b{t}\b")) for t in tech.get("whitelist", []))
    known = tuple((t, _compile(rf"(?<![\w-]){t}(?![\w-])")) for t in tech.get("known", []))
    return Lexicon(rules, whitelist, known)


def lexicon(config_dir: Path | None = None) -> Lexicon:
    d = config_dir or paths.CONFIG_DIR
    files = [d / "banned_claims.yaml", d / "tech_terms.yaml"]
    return _lexicon_cached(str(d), tuple(f.stat().st_mtime for f in files))


# ── clause analysis ───────────────────────────────────────────────────────────────────────────────────
NEGATION = re.compile(
    r"\b(not|never|no|none|nor|without|yet to|new to|n't|haven't|hasn't|didn't|don't|isn't|aren't|wasn't|cannot)\b|n't\b",
    re.IGNORECASE)
ASPIRATION = re.compile(
    r"\b(eager|keen|excited|hope|hoping|want|wants|wanting|would like|'d like|would love|'d love|looking forward|"
    r"would welcome|would value|would be glad|glad to|happy to|interested|interest in|drawn to|curious|curiosity|"
    r"explore|exploring|aspire|aim to|aiming to|plan to|intend to|ready to learn|open to|pick (it |them )?up|"
    r"to learn|learn more|learn how|(am|i'm|i am) learning|learning (to|how|about|more|new)|keen on|would bring|"
    r"opportunity to|chance to|goal of|to study|questions i)\b",
    re.IGNORECASE)
CLAUSE_SPLIT = re.compile(r"\s*(?:;|:(?!//)|—|–| - |, and (?=i\b|i'|am\b|my\b)|, but |, while |, which |, so (?=i\b|each)|"
                          r" and am | and i(?=\s)| but i(?=\s))\s*", re.IGNORECASE)
LEADING_SUBORDINATE = re.compile(r"^(while|though|although|even though|since|as)\b[^,]*,", re.IGNORECASE)


def clauses(sentence: str) -> list[str]:
    s = sentence.strip()
    out: list[str] = []
    m = LEADING_SUBORDINATE.match(s)
    if m:
        out.append(m.group(0)[:-1])
        s = s[m.end():]
    out.extend(c for c in CLAUSE_SPLIT.split(s) if c and c.strip())
    return [c.strip() for c in out if c.strip()]


def is_hedged(clause: str) -> bool:
    """Negated or aspirational: honest statements about what Prerit hasn't done or wants to do."""
    return bool(NEGATION.search(clause) or ASPIRATION.search(clause))


# ── numbers and URLs ──────────────────────────────────────────────────────────────────────────────────
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s?(million|thousand|k)\b)?", re.IGNORECASE)
URL = re.compile(r"https?://[^\s)\]\"'>]+")
YEAR = re.compile(r"^(19|20)\d{2}$")
APPROX = re.compile(r"\b(over|about|around|nearly|almost|roughly|approximately|more than|some|~)\s*$", re.IGNORECASE)
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "hundred": 100}


def _num(token: str, scale: str | None = None) -> float:
    v = float(token.replace(",", ""))
    if scale:
        v *= {"million": 1e6, "thousand": 1e3, "k": 1e3}[scale.lower()]
    return v


def numbers_in(text: str) -> list[tuple[str, float, int]]:
    """(literal, value, start) for every number, skipping the digits inside URLs and ordinals like 2nd."""
    out = []
    masked = URL.sub(lambda m: " " * len(m.group(0)), text)
    for m in NUMBER.finditer(masked):
        tail = masked[m.end(1):m.end(1) + 2].lower()
        if tail in ("st", "nd", "rd", "th"):
            continue
        out.append((m.group(1), _num(m.group(1), m.group(2)), m.start()))
    return out


@dataclass(frozen=True)
class FactIndex:
    numbers: frozenset[float]
    literals: frozenset[str]
    urls: frozenset[str]
    by_project: dict[str, tuple[str, ...]]


def build_index(sheet: FactSheet) -> FactIndex:
    nums: set[float] = set()
    lits: set[str] = set()
    urls: set[str] = set()
    for f in sheet.facts:
        if f.status != "verified":
            continue
        text = f.text + " " + " ".join(f.phrasings)
        for lit, val, _ in numbers_in(text):
            nums.add(val)
            lits.add(lit.replace(",", ""))
        for w, v in WORD_NUMBERS.items():
            if re.search(rf"\b{w}\b", text, re.IGNORECASE):
                nums.add(float(v))
        for u in URL.findall(f.text):
            urls.add(u.rstrip(".,").rstrip("/").lower())
    return FactIndex(frozenset(nums), frozenset(lits), frozenset(urls), {})


# ── project attribution ───────────────────────────────────────────────────────────────────────────────
BOOK_ONLY = re.compile(r"\b(pipeline|yaml|logging|streamlit|k-?nearest|knn|csr|book-crossing|collaborative[- ]filtering|"
                       r"recommend\w*)\b", re.IGNORECASE)
CHURN_ONLY = re.compile(r"\b(random forest|one-hot|tenure|telco|churn)\b", re.IGNORECASE)
NAMES_BOOK = re.compile(r"\b(book|recommend\w*)\b", re.IGNORECASE)
NAMES_CHURN = re.compile(r"\b(churn|telco)\b", re.IGNORECASE)

PROFILE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("hours_cap_term", re.compile(r"\b(\d+)\s*(hours|hrs)\s*(per|a|/)\s*week\b", re.IGNORECASE)),
    ("availability_windows", re.compile(r"\bavailable (to (work|start)|from|starting|between|for)\b", re.IGNORECASE)),
    ("cgpa", re.compile(r"\b(c?gpa|grade point)\b", re.IGNORECASE)),
    ("phone", re.compile(r"(\+\d{1,3}[\s-]?)?\b\d{5}[\s-]?\d{5}\b")),
    ("grad_year", re.compile(r"\bgraduat(e|ing|ion) (in|by) (19|20)\d{2}\b", re.IGNORECASE)),
)


def check_sentence(text: str, cited_fact_ids: Iterable[str] = (), facts: FactSheet | None = None, *,
                   context: CheckContext | None = None, config_dir: Path | None = None) -> list[Violation]:
    facts = facts or load_facts()
    ctx = context or CheckContext()
    lex = lexicon(config_dir)
    text = normalize(text)
    index = build_index(facts)
    cited = list(cited_fact_ids)
    by_id = facts.by_id()
    quotes = " ".join(ctx.job_quotes.values())
    out: list[Violation] = []

    def add(rule: str, span: str, message: str) -> None:
        if not any(v.rule == rule and v.span == span for v in out):
            out.append(Violation(rule, span.strip(), message))

    parts = clauses(text)
    claim_parts = [c for c in parts if not is_hedged(c)]

    # lexicon rules
    for rule, claims_only, message, patterns in lex.rules:
        for part in (claim_parts if claims_only else [text]):
            for pat in patterns:
                m = pat.search(part)
                if m and not (quotes and m.group(0).lower() in quotes.lower()):
                    add(rule, m.group(0), message)

    # technology outside the whitelist, stated as something he has done
    for part in claim_parts:
        for term, pat in lex.known_tech:
            m = pat.search(part)
            if m and m.group(0).lower() not in quotes.lower():
                add("TECH_NOT_WHITELISTED", m.group(0), f"'{m.group(0)}' is not in Prerit's code (F-SKILLS)")

    # numbers must come from facts, confirmed fields or cited job quotes
    allowed_nums = set(index.numbers)
    quote_nums = {v for q in ctx.job_quotes.values() for _, v, _ in numbers_in(q)}
    field_nums = {v for f in ctx.confirmed_fields.values() for _, v, _ in numbers_in(str(f))}
    masked = _mask_word_count_notes(text)
    for lit, val, start in numbers_in(masked):
        if val in allowed_nums or val in quote_nums or val in field_nums:
            continue
        if YEAR.match(lit) and 2020 <= val <= 2035:
            continue  # programme years / dates are checked against the posting by the deadline verifier
        if APPROX.search(masked[:start]) and any(n and abs(val - n) / n <= 0.15 for n in allowed_nums | quote_nums):
            continue
        add("NUM_NOT_IN_FACTS", lit, f"{lit} is not in the cited facts or job quotes")

    for u in URL.findall(text):
        norm = u.rstrip(".,").rstrip("/").lower()
        if norm not in index.urls and norm not in quotes.lower():
            add("URL_NOT_IN_FACTS", u, "URL is not in the fact sheet or the posting")

    # book-only / churn-only techniques attributed to the other project
    prev = ctx.previous or ""
    book_terms, churn_terms = BOOK_ONLY.findall(text), CHURN_ONLY.findall(text)
    if book_terms and not NAMES_BOOK.search(text) and CHURN_ONLY.search(prev) and not NAMES_BOOK.search(prev) \
            and not churn_terms:
        add("WRONG_PROJECT", BOOK_ONLY.search(text).group(0), "Book-project technique attributed to the churn project")
    if churn_terms and not NAMES_CHURN.search(text) and BOOK_ONLY.search(prev) and not NAMES_CHURN.search(prev) \
            and not book_terms:
        add("WRONG_PROJECT", CHURN_ONLY.search(text).group(0), "Churn-project technique attributed to the book project")

    # personal details only from confirmed profile fields
    for key, pat in PROFILE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        value = ctx.confirmed_fields.get(key)
        if value and (key != "hours_cap_term" or (m.group(1) and m.group(1) == str(value).split(".")[0])):
            continue
        if key == "availability_windows" and ctx.confirmed_fields.get("availability_windows"):
            continue
        add("PROFILE_UNCONFIRMED", m.group(0), f"Uses '{key}', which Prerit hasn't confirmed in Settings")

    # citation structure (Writer output only)
    if ctx.require_citations:
        unknown = [f for f in cited if f not in by_id]
        for f in unknown:
            add("UNKNOWN_FACT_ID", f, "Cited fact id does not exist")
        retired = [f for f in cited if f in by_id and by_id[f].status != "verified"]
        for f in retired:
            add("UNKNOWN_FACT_ID", f, "Cited fact is not verified")
        if ctx.kind == "claim" and not cited and claim_parts and _mentions_self(text):
            add("CITATION_MISSING", text[:60], "A claim about Prerit must cite at least one fact id")
        if ctx.kind == "job_reference" and not ctx.job_quotes:
            add("JOB_CLAIM_UNQUOTED", text[:60], "A statement about the role must cite a verified job quote")
    return out


def normalize(text: str) -> str:
    """Straight quotes and apostrophes, so "haven’t" reads as a negation."""
    return text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')


SELF = re.compile(r"\b(i|i'm|i've|my|me|mine)\b", re.IGNORECASE)


def _mentions_self(text: str) -> bool:
    return bool(SELF.search(text))


WORD_COUNT_NOTE = re.compile(r"\([^)]*\bwords?\b[^)]*\)", re.IGNORECASE)


def _mask_word_count_notes(text: str) -> str:
    """'(about 220 words; the form asks for 150-250)' is a length note for Prerit, not a claim."""
    return WORD_COUNT_NOTE.sub(lambda m: " " * len(m.group(0)), text)


# ── documents ─────────────────────────────────────────────────────────────────────────────────────────
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")


def split_sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = " ".join(para.split())
        if para:
            out.extend(s for s in SENTENCE_END.split(para) if s.strip())
    return out


@dataclass
class DocumentReport:
    passed: bool
    sentences: list[dict[str, Any]]

    @property
    def violations(self) -> list[dict[str, Any]]:
        return [v | {"sentence_idx": s["idx"]} for s in self.sentences for v in s["violations"]]


def check_document(sentences: list[dict[str, Any]] | list[str], facts: FactSheet | None = None, *,
                   job_quotes: dict[str, str] | None = None, confirmed_fields: dict[str, str] | None = None,
                   require_citations: bool = False) -> DocumentReport:
    """`sentences` = Writer output entries {text, kind, fact_ids, job_quote_ids} or plain strings."""
    facts = facts or load_facts()
    rows: list[dict[str, Any]] = []
    prev: str | None = None
    for i, s in enumerate(sentences):
        entry = {"text": s} if isinstance(s, str) else dict(s)
        quotes = {q: (job_quotes or {})[q] for q in entry.get("job_quote_ids") or [] if q in (job_quotes or {})}
        ctx = CheckContext(previous=prev, job_quotes=quotes, confirmed_fields=confirmed_fields or {},
                           require_citations=require_citations, kind=entry.get("kind"))
        v = check_sentence(entry["text"], entry.get("fact_ids") or [], facts, context=ctx)
        rows.append({"idx": i, "text": entry["text"], "kind": entry.get("kind"), "fact_ids": entry.get("fact_ids") or [],
                     "violations": [x.as_dict() for x in v], "passed": not v})
        prev = entry["text"]
    return DocumentReport(passed=all(r["passed"] for r in rows), sentences=rows)


def fact_texts(facts: FactSheet, ids: Iterable[str]) -> list[Fact]:
    by = facts.by_id()
    return [by[i] for i in ids if i in by]
