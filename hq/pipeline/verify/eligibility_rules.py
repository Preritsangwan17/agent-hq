"""Deterministic eligibility rules (CONTRACT_C §4). A hard hit decides alone ("ineligible"); everything else is left
to the quoted LLM extraction. Time-aware: Prerit is a 2nd-year B.Tech student in 2026-27 (graduating 2029 unless
he confirms otherwise) and a rising 3rd-year from May 2027, so year/semester rules are evaluated at the role's
start date when it is known.

Skill gaps never make him ineligible — they lower the fit score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

YEAR = r"(20[2-3]\d)"


@dataclass
class Candidate:
    grad_year: int = 2029
    grad_year_confirmed: bool = False
    semester: int | None = None          # confirmed value; otherwise inferred from the date
    cgpa: float | None = None
    citizenship: str = "IN"
    has_internship: bool = False
    degree_completed: bool = False
    enrolment_country: str = "IN"


@dataclass
class RuleHit:
    rule: str
    quote: str
    detail: str
    hard: bool = True


@dataclass
class RulesResult:
    hits: list[RuleHit] = field(default_factory=list)
    needs_info: list[RuleHit] = field(default_factory=list)

    @property
    def ineligible(self) -> bool:
        return any(h.hard for h in self.hits)

    def as_dict(self) -> dict[str, Any]:
        return {"ineligible": self.ineligible,
                "hits": [h.__dict__ for h in self.hits], "needs_info": [h.__dict__ for h in self.needs_info]}


def study_year(on: date, c: Candidate) -> int:
    """1-based year of study on a date (academic year starts in July)."""
    ay_start = on.year if on.month >= 7 else on.year - 1
    return max(1, min(5, 4 - (c.grad_year - 1 - ay_start)))


def semester_on(on: date, c: Candidate) -> int:
    if c.semester and on <= date.today().replace(month=12, day=31):
        return c.semester
    y = study_year(on, c)
    return 2 * y - (1 if on.month >= 7 else 0)


def _sentence(text: str, start: int, end: int) -> str:
    a = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    b_candidates = [i for i in (text.find(".", end), text.find("\n", end)) if i != -1]
    b = min(b_candidates) if b_candidates else len(text)
    return text[a:b + (1 if b < len(text) and text[b] == "." else 0)].strip()


ORDINAL = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "final": 4,
           "pre-final": 3, "prefinal": 3, "penultimate": 3}
SEM_ORD = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7, "8th": 8, "first": 1, "second": 2,
           "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8}


def check(text: str, *, candidate: Candidate | None = None, start: date | None = None,
          remote: bool = False, country_iso2: str | None = None) -> RulesResult:
    c = candidate or Candidate()
    on = start or date.today()
    t = " ".join((text or "").split())
    low = t.lower()
    res = RulesResult()

    def hit(rule: str, m: re.Match, detail: str, hard: bool = True) -> None:
        q = _sentence(t, m.start(), m.end())
        bucket = res.hits if hard else res.needs_info
        if not any(h.rule == rule and h.quote == q for h in bucket):
            bucket.append(RuleHit(rule, q, detail, hard))

    # graduation-year windows: "2026 pass-outs only", "2026/2027 graduates", "batch of 2025", "class of 2027"
    for m in re.finditer(rf"(?:{YEAR}(?:\s*(?:/|,|&|and|or|-)\s*{YEAR})*)\s*(?:pass[- ]?outs?|passing out|graduates?|"
                         rf"graduating|batch|grads)\b|(?:batch|class)\s+of\s+{YEAR}(?:\s*(?:/|,|&|and|or|-)\s*{YEAR})*|"
                         rf"graduat\w*\s+(?:in|by|between)\s+{YEAR}(?:\s*(?:/|,|&|and|or|-)\s*{YEAR})*", low):
        years = {int(y) for y in re.findall(YEAR, m.group(0))}
        if years and c.grad_year not in years and not re.search(r"(or later|and later|onwards|\+)", low[m.end():m.end() + 12]):
            hit("GRAD_YEAR", m, f"accepts {sorted(years)} graduates; Prerit graduates in {c.grad_year}")
        elif years and c.grad_year in years:
            pass
    # final-year / recent graduate only
    for m in re.finditer(r"\b(final[- ]year|last year of (?:study|studies|their degree)|pre-?final[- ]year|penultimate"
                         r"[- ]year|recent(?:ly)? graduat\w*)\b", low):
        window = low[max(0, m.start() - 80):m.end() + 80]
        yr = study_year(on, c)
        if "pre" in m.group(0) or "penultimate" in m.group(0):
            if yr != 3 and not re.search(r"\b(any year|all years|first|second|2nd|1st)\b", window):
                hit("STAGE", m, f"pre-final-year students only; Prerit is in year {yr} then")
        elif not re.search(r"\b(any year|all years|second|2nd|first|1st|currently enrolled students)\b", window):
            hit("STAGE", m, "final-year students or recent graduates only; Prerit is a 2nd-year student")
    # "3rd year students" style
    for m in re.finditer(r"\b(first|1st|second|2nd|third|3rd|fourth|4th)[- ]year (?:b\.?\s?tech |engineering |undergraduate |"
                         r"bachelor'?s? )?students\b", low):
        allowed = {ORDINAL[w] for w in re.findall(r"\b(first|1st|second|2nd|third|3rd|fourth|4th)\b",
                                                   low[max(0, m.start() - 40):m.end()])}
        yr = study_year(on, c)
        if allowed and yr not in allowed:
            hit("STAGE", m, f"year {sorted(allowed)} students; Prerit is in year {yr} then")
    # semester restrictions
    for m in re.finditer(r"\b(1st|2nd|3rd|4th|5th|6th|7th|8th|first|second|third|fourth|fifth|sixth|seventh|eighth)"
                         r"[- ]semester\b|\bsemester\s*([1-8])\b", low):
        n = SEM_ORD.get(m.group(1)) if m.group(1) else int(m.group(2))
        sem = semester_on(on, c)
        window = low[max(0, m.start() - 60):m.end() + 60]
        if n and n != sem and re.search(r"\b(only|students|currently in|enrolled|pursuing|studying in)\b", window):
            hit("SEMESTER", m, f"semester {n} students; Prerit is in semester {sem} then")
    # PhD / Master's only
    for m in re.finditer(r"\b(?:currently\s+)?(?:pursuing|enrolled in)\s+(?:a\s+)?(ph\.?\s?d|doctora\w+|master'?s|m\.?s\.?|"
                         r"m\.?\s?tech|mba)\b", low):
        window = low[max(0, m.start() - 60):m.end() + 100]
        if not re.search(r"\b(bachelor'?s?|b\.?\s?tech|b\.?e\.?|undergrad\w*|or (?:a )?(?:bachelor|b\.tech))\b", window):
            hit("DEGREE_LEVEL", m, f"{m.group(1).upper()} students only")
    # degree already completed
    for m in re.finditer(r"\b(?:must (?:have|hold)|holds?|completed|possess)\s+(?:a\s+|an\s+)?(?:bachelor'?s?|b\.?\s?tech|"
                         r"undergraduate|master'?s?)\s+degree\b|\bdegree holders?\b|\bgraduates? only\b", low):
        window = low[max(0, m.start() - 80):m.end() + 80]
        if not re.search(r"\b(pursuing|or pursuing|currently enrolled|expected|in progress|final year|students?)\b", window):
            hit("DEGREE_COMPLETED", m, "a completed degree is required; Prerit hasn't completed one")
    # CGPA minimum
    for m in re.finditer(r"\b(?:minimum\s+)?c?gpa\s*(?:of\s*)?(?:at least\s*|above\s*|>=?\s*|≥\s*)?(\d(?:\.\d{1,2})?)\s*"
                         r"(?:/\s*10|out of 10)?\s*(?:\+|or above|and above|or more|minimum)?|\bminimum\s+(?:c?gpa|cgpa)\s+(?:of\s+)?"
                         r"(\d(?:\.\d{1,2})?)", low):
        v = float(m.group(1) or m.group(2))
        if v <= 4.0 and "/4" not in low[m.start():m.end() + 6]:
            v = v * 2.5
        if c.cgpa is None:
            hit("CGPA", m, f"asks for CGPA ≥ {v:g}; Prerit hasn't confirmed his CGPA", hard=False)
        elif c.cgpa < v:
            hit("CGPA", m, f"asks for CGPA ≥ {v:g}; Prerit's is {c.cgpa:g}")
    # experience required
    for m in re.finditer(r"\b(\d+)\+?\s*(?:-\s*\d+\s*)?years?\s+of\s+(?:professional\s+|industry\s+|relevant\s+|work\s+|"
                         r"hands-on\s+)?experience\b", low):
        window = low[max(0, m.start() - 60):m.end() + 60]
        if int(m.group(1)) >= 1 and not re.search(r"\b(preferred|nice to have|a plus|bonus|ideally|desirable)\b", window):
            hit("EXPERIENCE", m, f"{m.group(1)}+ years of experience required; Prerit has none")
    for m in re.finditer(r"\b(?:previous|prior)\s+(?:internship|work)\s+experience\b[^.]{0,60}\b(essential|required|mandatory|must)\b|"
                         r"\bmust have (?:completed )?(?:a |an )?(?:previous |prior )?internship\b", low):
        hit("EXPERIENCE", m, "prior internship experience is required; Prerit has none")
    # work authorisation / enrolment country (on-site outside India, or remote restricted to elsewhere)
    outside = country_iso2 not in (None, "IN")
    for m in re.finditer(r"\b(?:must be|should be)\s+(?:legally\s+)?(?:authori[sz]ed|eligible)\s+to\s+work\s+in\s+(?:the\s+)?"
                         r"(us|u\.s\.|united states|uk|united kingdom|canada|eu|europe|germany|australia|singapore)\b|"
                         r"\b(?:us|u\.s\.) citizens? only\b|\bsecurity clearance\b|\b(?:do not|does not|don't|cannot|unable to|"
                         r"will not)\s+(?:offer|provide|sponsor)\s+(?:visa\s+)?sponsorship\b|\bno (?:visa )?sponsorship\b", low):
        if outside or not remote:
            if outside:
                hit("WORK_AUTH", m, "requires existing work authorisation / no sponsorship; Prerit needs a visa")
    for m in re.finditer(r"\b(?:currently\s+)?enrolled\s+(?:at|in)\s+(?:a\s+|an\s+)?(us|u\.s\.|american|uk|british|german|european|"
                         r"swiss|canadian|japanese|singapore\w*|australian)\s+(?:university|institution|college|school)\b", low):
        hit("ENROLMENT", m, f"students of {m.group(1).upper()} universities only")
    if remote:
        for m in re.finditer(r"\b(?:candidates?|applicants?)\s+(?:must\s+be\s+)?(?:based|located|residing)\s+in\s+(?:the\s+)?"
                             r"(us|u\.s\.|usa|united states|uk|europe|eu|canada|latam|americas)\b|\b(us|usa|uk|eu)[- ]only\b", low):
            hit("LOCATION", m, "remote role restricted to a region outside India")
    return res
