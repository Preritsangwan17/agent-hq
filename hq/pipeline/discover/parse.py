"""parse.job (CONTRACT_C §3): posting text → JobParse.

A deterministic pass always runs (pay line, deadline, apply e-mail with its exact sentence, hours/duration/start,
requirement and responsibility sentences as exact quotes). When a parser model is available its answer is merged
in; every quote it returns must be an exact substring of the posting or it is dropped.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateparser

from hq.pipeline.discover.text import sentences
from hq.pipeline.verify.pay import parse_pay

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PAY_HINT = re.compile(r"(₹|rs\.?\s|inr|usd|\$|€|eur|£|gbp|chf|sgd|nt\$|twd|¥|jpy|aed|cad|stipend|salary|"
                      r"compensation|pay(?:s|ment)?\b|per (hour|month|year)|/(hr|hour|month|mo|year|yr)\b)", re.I)
DEADLINE = re.compile(r"(apply by|deadline|last date|applications? (close|due|deadline)|closing date|due date)"
                      r"[^.\n]{0,40}?(\d{1,2}(st|nd|rd|th)?\s+\w+,?\s+\d{4}|\w+\s+\d{1,2}(st|nd|rd|th)?,?\s+\d{4}|"
                      r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})", re.I)
HOURS = re.compile(r"(\d{1,2})\s*(\+|-\s*\d{1,2})?\s*(hours|hrs|h)\s*(per|/|a)\s*week", re.I)
DURATION = re.compile(r"(\d{1,2})\s*(-\s*\d{1,2}\s*)?(months?|weeks?)\b", re.I)
START = re.compile(r"(start(ing)? (date|from|in|on)|joining date|commence)[^.\n]{0,60}", re.I)
REQ = re.compile(r"\b(must|required|requirement|require|pursuing|enrolled|degree|bachelor|master|ph\.?d|"
                 r"graduat\w*|pass-?outs?|batch|semester|final[- ]year|year of study|experience|proficien\w*|"
                 r"knowledge of|familiar\w*|eligib\w*|c?gpa|work authori[sz]ation|authori[sz]ed to work|visa|"
                 r"citizen\w*|sponsor\w*|minimum|at least|qualification\w*|skills?)\b", re.I)
DUTY = re.compile(r"\b(you will|you'll|responsibilit\w*|what you'll do|work on|build|develop|design|help us|"
                  r"collaborate|contribute|intern will|we are looking|looking for|join (our|the))\b", re.I)
CUR = (r"(?:₹|(?<![a-z])(?:rs\.?|inr|usd|eur|gbp|chf|sgd|twd|jpy|aed|cad|aud)(?![a-z])|us\$|s\$|nt\$|c\$|\$|€|£|¥)")
PAY_SPAN = re.compile(
    rf"((?:stipend|salary|compensation|pay|ctc)\s*[:\-–]?\s*)?"
    rf"({CUR}\s?\d[\d,.]*\s*(?:k|lakhs?|lpa|l)?(?:\s*(?:-|–|to)\s*{CUR}?\s?\d[\d,.]*\s*(?:k|lakhs?|lpa|l)?)?"
    rf"(?:\s*(?:/|per|a)\s*(?:month|mo|hour|hr|h|year|yr|annum|week|wk))?"
    rf"|\d[\d,.]*\s*(?:k|lakhs?|lpa)\+?\s*(?:per annum|p\.a\.|annual(?:ly)?|/year|salary|ctc)"
    rf"|\d[\d,.]*\s*(?:-\s*\d[\d,.]*\s*)?lpa\b"
    rf"|\d[\d,.]*\s*{CUR}(?:\s*(?:/|per)\s*(?:month|hour|year))?)", re.I)
APPLY_VERB = re.compile(r"\b(send|email|e-mail|mail|apply|write to|submit|forward)\b", re.I)


@dataclass
class JobParse:
    parse_ok: bool
    company: str | None = None
    title: str | None = None
    kind: str | None = None
    location: dict[str, Any] = field(default_factory=dict)
    pay_raw: str | None = None
    deadline_raw: str | None = None
    deadline_at: str | None = None
    start_raw: str | None = None
    duration_raw: str | None = None
    hours_raw: str | None = None
    hours_per_week: float | None = None
    duration_months: float | None = None
    requirements: list[dict[str, str]] = field(default_factory=list)
    duties: list[str] = field(default_factory=list)
    apply: dict[str, Any] = field(default_factory=dict)
    benefits: dict[str, bool] = field(default_factory=dict)
    method: str = "rules"
    model_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def req_type(s: str) -> str:
    low = s.lower()
    if re.search(r"graduat|pass-?out|batch|class of|20\d\d", low):
        return "year"
    if re.search(r"semester", low):
        return "semester"
    if re.search(r"final[- ]year|year of study|penultimate|pre-final|\b(1st|2nd|3rd|4th|first|second|third|fourth) year", low):
        return "stage"
    if re.search(r"c?gpa|grade point|percentage", low):
        return "cgpa"
    if re.search(r"authori[sz]|visa|citizen|sponsor|clearance", low):
        return "work_auth"
    if re.search(r"ph\.?d|master|bachelor|degree|pursuing|enrolled|b\.?tech|undergraduate", low):
        return "degree"
    if re.search(r"years? of|experience|internship", low):
        return "experience"
    return "skill" if re.search(r"python|sql|java|pytorch|tensorflow|ml|machine learning|data|skills?|knowledge", low) else "other"


def parse_date(raw: str) -> str | None:
    try:
        dt = dateparser.parse(raw, dayfirst=not re.match(r"[A-Za-z]", raw.strip()), fuzzy=True,
                              default=datetime(2026, 1, 1))
    except (ValueError, OverflowError):
        return None
    if dt.year < 2024 or dt.year > 2035:
        return None
    return dt.replace(hour=23, minute=59, tzinfo=None).strftime("%Y-%m-%dT%H:%M:00Z")


def rules_parse(text: str, *, company: str | None = None, title: str | None = None,
                pay_hint: str | None = None) -> JobParse:
    body = (text or "").strip()
    if len(body) < 120 or re.search(r"(sign in|log in|join now) to (view|see|continue)|captcha|access denied|"
                                     r"page not found|this job (is|has been) (no longer|closed)", body[:600], re.I):
        return JobParse(parse_ok=False, company=company, title=title)
    sents = sentences(body)
    p = JobParse(parse_ok=True, company=company, title=title)
    # pay: the first sentence/line that parses as a listed amount
    if pay_hint and parse_pay(pay_hint).status in ("listed", "variable"):
        p.pay_raw = pay_hint
    else:
        for s in sents:
            m = PAY_SPAN.search(s)
            if m:
                span = (m.group(1) or "") + m.group(2)
                if parse_pay(span).status in ("listed", "variable", "fee_required"):
                    p.pay_raw = span.strip()
                    break
            if re.search(r"\b(unpaid|no stipend|without stipend)\b", s, re.I):
                p.pay_raw = s.strip()[:200]
                break
    m = DEADLINE.search(body)
    if m:
        p.deadline_raw = m.group(0).strip()
        p.deadline_at = parse_date(m.group(3))
    m = HOURS.search(body)
    if m:
        p.hours_raw = m.group(0)
        p.hours_per_week = float(m.group(1))
    m = DURATION.search(body)
    if m:
        p.duration_raw = m.group(0)
        n = float(m.group(1))
        p.duration_months = n if m.group(3).lower().startswith("month") else round(n / 4.345, 1)
    m = START.search(body)
    if m:
        p.start_raw = m.group(0).strip()
    for s in sents:
        if len(s) > 400:
            continue
        if REQ.search(s) and len(p.requirements) < 14:
            p.requirements.append({"type": req_type(s), "quote": s})
        elif DUTY.search(s) and len(p.duties) < 10 and len(s) >= 30:
            p.duties.append(s)
    emails = [e for e in EMAIL.findall(body) if not re.search(r"noreply|no-reply|example\.", e, re.I)]
    for e in emails:
        quote = next((s for s in sents if e in s), e)
        if APPLY_VERB.search(quote):
            p.apply = {"channel": "email", "email": e, "email_quote": quote}
            break
    p.benefits = {"housing": bool(re.search(r"\b(accommodation|housing|dorm)\b.{0,40}(provided|covered|free)", body, re.I)),
                  "meals": bool(re.search(r"\b(meals?|food|board)\b.{0,30}(provided|covered|free)", body, re.I)),
                  "travel": bool(re.search(r"\b(travel|airfare|flight)s?\b.{0,40}(covered|reimbursed|provided)", body, re.I))}
    return p


def merge_llm(base: JobParse, llm: dict[str, Any] | None, text: str, model_id: str | None) -> JobParse:
    """Fill gaps from the model's answer; keep only exact-substring quotes."""
    if not isinstance(llm, dict):
        return base
    norm = " ".join(text.split()).lower()

    def exact(q: Any) -> bool:
        return isinstance(q, str) and len(q) >= 8 and " ".join(q.split()).lower() in norm

    if llm.get("parse_ok") is False and not base.requirements:
        base.parse_ok = False
        return base
    for key in ("company", "title", "kind"):
        if not getattr(base, key) and isinstance(llm.get(key), str):
            setattr(base, key, llm[key][:200])
    loc = llm.get("location") or {}
    if isinstance(loc, dict):
        base.location = {k: loc.get(k) for k in ("city", "country_iso2", "work_mode") if loc.get(k)}
    for key in ("pay_raw", "deadline_raw", "start_raw", "duration_raw", "hours_raw"):
        v = llm.get(key)
        if not getattr(base, key) and exact(v):
            setattr(base, key, v)
            if key == "deadline_raw":
                base.deadline_at = parse_date(v)
    reqs = [r for r in llm.get("requirements") or [] if isinstance(r, dict) and exact(r.get("quote"))]
    seen = {" ".join(r["quote"].split()).lower() for r in base.requirements}
    for r in reqs:
        key = " ".join(r["quote"].split()).lower()
        if key not in seen:
            base.requirements.append({"type": str(r.get("type") or req_type(r["quote"])), "quote": r["quote"]})
            seen.add(key)
    ap = llm.get("apply") or {}
    if isinstance(ap, dict) and not base.apply.get("email") and isinstance(ap.get("email"), str) and ap["email"] in text:
        quote = next((s for s in sentences(text) if ap["email"] in s), ap["email"])
        base.apply = {"channel": "email", "email": ap["email"], "email_quote": quote}
    b = llm.get("benefits") or {}
    if isinstance(b, dict):
        for k in ("housing", "meals", "travel"):
            base.benefits[k] = bool(base.benefits.get(k) or b.get(k) is True)
    base.method, base.model_id = "rules+llm", model_id
    return base


def job_quotes(p: JobParse, limit: int = 14) -> list[str]:
    """Quotes the Writer may cite (J1…): requirements first, then duties; all exact substrings."""
    out: list[str] = []
    for q in [r["quote"] for r in p.requirements] + p.duties:
        q = q.strip()
        if 20 <= len(q) <= 320 and q not in out:
            out.append(q)
        if len(out) >= limit:
            break
    return out


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
