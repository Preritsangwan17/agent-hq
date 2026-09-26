"""Transparent match score 0–100 against Prerit's career plan (config/career.yaml).

Twelve factors, each scored 0–100 with a one-line reason, weighted (weights sum to 100):
skills · projects · education · experience · location · visa · role type · compensation · company · AI/ML
relevance · eligibility probability · career value. The breakdown is stored on the opportunity and shown on its
page, so every decision ("apply", "consider", "skip") can be checked. Hard gates (ineligible, scam, unpaid, closed)
run before this and are never overridden by a high score. Skill gaps lower the score; they never make Prerit
ineligible.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths
from hq.pipeline.gates.fact_deterministic import lexicon

FACTOR_LABELS = {
    "skills": "Skills match", "projects": "Projects match", "education": "Education requirements",
    "experience": "Experience requirements", "location": "Location priority", "visa": "Visa / work authorisation",
    "role_type": "Internship vs full-time", "compensation": "Compensation", "company": "Company quality",
    "ai_relevance": "AI/ML relevance", "eligibility": "Eligibility probability", "career_value": "Career value",
}
DEFAULT_WEIGHTS = {"skills": 12, "projects": 8, "education": 7, "experience": 7, "location": 12, "visa": 9,
                   "role_type": 6, "compensation": 7, "company": 8, "ai_relevance": 12, "eligibility": 6,
                   "career_value": 6}
COUNTRY_NAMES = {"DE": "Germany", "NL": "the Netherlands", "IE": "Ireland", "CH": "Switzerland", "GB": "the UK",
                 "FR": "France", "SE": "Sweden", "FI": "Finland", "DK": "Denmark", "NO": "Norway", "BE": "Belgium",
                 "AT": "Austria", "LU": "Luxembourg", "ES": "Spain", "PT": "Portugal", "IT": "Italy", "PL": "Poland",
                 "CZ": "Czechia", "EE": "Estonia", "RU": "Russia", "CA": "Canada", "AU": "Australia",
                 "NZ": "New Zealand", "IN": "India", "US": "the US", "SG": "Singapore", "JP": "Japan",
                 "TW": "Taiwan", "AE": "the UAE"}

STUDENT_OK = re.compile(
    r"currently (enrolled|pursuing)|undergraduate|bachelor'?s (student|candidates?)|b\.?\s?tech|\bb\.?e\.?\b|"
    r"students? (in|of|pursuing|enrolled)|enrolled (in|at) an?|second[- ]year|2nd[- ]year|any year|pre-?final|"
    r"penultimate|all years|first or second year|university students?", re.I)
NEEDS_POSTGRAD = re.compile(r"\b(master'?s|m\.?\s?s\.? (student|degree)|ph\.?\s?d|doctoral|graduate students?)\b",
                            re.I)
BACHELOR_OR_MASTER = re.compile(r"bachelor'?s,? (or|/) master'?s|bs/ms|b\.?s\.?/m\.?s\.?", re.I)
NEEDS_DEGREE = re.compile(r"(bachelor'?s|b\.?s\.?|university) degree (is )?(required|in)|degree in computer science|"
                          r"recent graduates?|new grad|graduated (in|by)|holds? a degree", re.I)
FINAL_YEAR = re.compile(r"final[- ]year|graduating (in|by) 202[5-7]|class of 202[5-7]|202[5-7] (graduates|pass-?outs)",
                        re.I)
YEARS_EXP = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)\b(?:\s+of)?(?:\s+(?:professional|relevant|"
                       r"industry|hands-on|work))?\s+experience", re.I)
NO_EXP = re.compile(r"no (prior )?experience (is )?(required|needed)|fresher|0\s*-\s*1 years?|entry[- ]level", re.I)
SPONSOR_YES = re.compile(r"visa sponsorship (is )?(available|provided|offered)|(we|will) (can )?sponsor|"
                         r"sponsorship (is )?available|relocation (support|assistance|package)|visa (support|assistance)|"
                         r"help with (your )?visa", re.I)
SPONSOR_NO = re.compile(r"(unable|not able|cannot|can't|do not|don't|will not|won't) (to )?(offer|provide|sponsor)|"
                        r"no (visa )?sponsorship|must (already )?(have|hold) (the )?(right|authori[sz]ation) to work|"
                        r"(legally )?authori[sz]ed to work in", re.I)
MUST_RESIDE = re.compile(r"must (be )?(located|based|resid\w*|live) in|(eu|us|uk) (residents?|citizens?) only|"
                         r"only (open|available) to (candidates|applicants) (in|from|based)", re.I)
JUNIOR = re.compile(r"\b(junior|jr\.?|entry[- ]level|graduate|new[- ]grad|early[- ]career|associate)\b", re.I)
WORKING_STUDENT = re.compile(r"werkstudent|working student", re.I)
MENTOR = re.compile(r"mentor|learning|training|onboarding|supervis", re.I)


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def career(config_dir: Path | None = None) -> dict[str, Any]:
    p = (config_dir or paths.CONFIG_DIR) / "career.yaml"
    return _load(str(p), p.stat().st_mtime) if p.exists() else {}


def _any(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.I)]


def skill_overlap(text: str) -> tuple[int, int, list[str], list[str]]:
    lex = lexicon()
    low = (text or "").lower()
    have = sorted({name for name, p in lex.whitelist if p.search(low)})
    gaps = sorted({term for term, p in lex.known_tech if p.search(low)})
    return len(have), len(gaps), have, gaps


@dataclass
class Factor:
    key: str
    score: int
    why: str

    def as_dict(self, weight: float) -> dict[str, Any]:
        return {"key": self.key, "label": FACTOR_LABELS[self.key], "score": self.score, "weight": weight,
                "points": round(self.score * weight / 100, 1), "why": self.why}


def _clamp(v: float) -> int:
    return int(max(0, min(100, round(v))))


# ── factors ───────────────────────────────────────────────────────────────────────────────────────────
def f_skills(text: str) -> tuple[Factor, list[str], list[str]]:
    n_have, n_gap, have, gaps = skill_overlap(text)
    if not n_have and not n_gap:
        return Factor("skills", 55, "The posting names no specific tools"), have, gaps
    score = min(100, 40 + 12 * n_have) * (1 - min(0.6, 0.1 * n_gap))
    why = (f"Matches {', '.join(have[:5])}" if have else "None of your tools are named")
    if gaps:
        why += f"; not used yet: {', '.join(gaps[:4])}"
    return Factor("skills", _clamp(score), why), have, gaps


def f_projects(text: str, c: dict[str, Any]) -> Factor:
    names = {"book": "book recommender", "churn": "churn predictor"}
    hits = {k: _any(v, text) for k, v in (c.get("project_topics") or {}).items()}
    hits = {k: v for k, v in hits.items() if v}
    if not hits:
        return Factor("projects", 30, "No clear link to your two projects")
    best = max(len(v) for v in hits.values())
    score = {1: 60, 2: 75}.get(best, 90) + (10 if len(hits) > 1 else 0)
    parts = [f"{names.get(k, k)} ({', '.join(v[:3])})" for k, v in hits.items()]
    return Factor("projects", _clamp(score), "Connects to your " + " and ".join(parts))


def f_education(text: str, title: str, kind: str) -> Factor:
    if re.search(r"\b2028\b|\b2029\b", text) and re.search(r"graduat|pass-?out|class of", text, re.I):
        return Factor("education", 100, "Asks for 2028/2029 graduates — your batch")
    if FINAL_YEAR.search(text):
        return Factor("education", 30, f"Wants final-year students or recent graduates (“{FINAL_YEAR.search(text).group(0)}”)")
    if NEEDS_POSTGRAD.search(title) or (NEEDS_POSTGRAD.search(text) and not BACHELOR_OR_MASTER.search(text)
                                         and not STUDENT_OK.search(text)):
        return Factor("education", 25, "Aimed at master's/PhD students")
    if STUDENT_OK.search(text) or BACHELOR_OR_MASTER.search(text):
        return Factor("education", 100, "Open to current undergraduates")
    if NEEDS_DEGREE.search(text):
        return Factor("education", 40, "Seems to expect a completed degree")
    if kind in ("internship", "research_internship", "program", "fellowship"):
        return Factor("education", 75, "Student role; no specific education requirement stated")
    return Factor("education", 60, "No education requirement stated")


def f_experience(text: str, kind: str) -> Factor:
    years = [int(m.group(1)) for m in YEARS_EXP.finditer(text) if int(m.group(1)) < 20]
    if years:
        y = min(years)
        score = {0: 100, 1: 55, 2: 25}.get(y, 5)
        return Factor("experience", score, f"Asks for {y}+ year{'s' if y != 1 else ''} of experience (you have none yet)"
                      if y else "No experience required")
    if NO_EXP.search(text):
        return Factor("experience", 100, "No experience required")
    if kind in ("internship", "research_internship", "program", "fellowship"):
        return Factor("experience", 95, "Internship — no prior experience expected")
    return Factor("experience", 65, "Experience level not stated")


def region_of(country: str | None, c: dict[str, Any]) -> dict[str, Any] | None:
    for r in c.get("regions") or []:
        if country and country in r.get("countries", []):
            return r
    return None


def f_location(opp: dict[str, Any], text: str, c: dict[str, Any]) -> tuple[Factor, dict[str, Any]]:
    country = opp.get("country_iso2")
    mode = opp.get("work_mode") or "unknown"
    raw = (opp.get("location_raw") or "").lower()
    region = region_of(country, c)
    info = {"tier": region["tier"] if region else None, "label": region["label"] if region else None,
            "country": country, "work_mode": mode}
    cname = COUNTRY_NAMES.get(country or "", country or "")
    if mode == "remote" and not region:
        words = c.get("remote_region_words") or {}
        tier = min((t for w, t in words.items() if re.search(rf"\b{w}\b", raw)), default=None)
        info["tier"] = tier
        pts = float(c.get("remote_points", 85)) + (5 if tier == 1 else 0)
        return Factor("location", _clamp(pts), "Remote" + (f" ({raw.strip()})" if raw.strip() else "")), info
    if region:
        pts = float(region.get("points", 100))
        why = f"{cname} — priority {region['tier']} ({region['label']})"
        if region["label"] == "Europe":
            within = float((c.get("europe_country_points") or {}).get(country, 85))
            pts = pts * within / 100
            why += f", country rank {within:.0f}/100 within Europe"
        if mode == "remote":
            pts = min(100, pts + 5)
            why += ", remote"
        return Factor("location", _clamp(pts), why), info
    if not country:
        return Factor("location", 50, "Location unclear"), info
    return Factor("location", _clamp(float(c.get("other_region_points", 40))),
                  f"{cname} — outside your priority regions (kept only if unusually relevant)"), info


def f_visa(opp: dict[str, Any], text: str, programme: bool) -> Factor:
    country, mode = opp.get("country_iso2"), opp.get("work_mode") or "unknown"
    if country == "IN" and mode != "remote":
        return Factor("visa", 100, "In India — no visa needed")
    if mode == "remote":
        m = MUST_RESIDE.search(text)
        if m:
            return Factor("visa", 35, f"Remote, but “{m.group(0)}”")
        return Factor("visa", 90, "Remote — no relocation or visa needed")
    m = SPONSOR_NO.search(text)
    if m:
        return Factor("visa", 5, f"“{m.group(0)}” — you'd need a visa")
    m = SPONSOR_YES.search(text)
    if m:
        return Factor("visa", 95, f"Visa help offered (“{m.group(0)}”)")
    if programme:
        return Factor("visa", 90, "Funded programme — these normally arrange the visa")
    if not country:
        return Factor("visa", 55, "Location unclear, so visa needs are unknown")
    return Factor("visa", 40, f"On-site in {COUNTRY_NAMES.get(country, country)}; sponsorship not mentioned")


def f_role_type(opp: dict[str, Any], title: str, text: str) -> Factor:
    kind = opp.get("kind") or "internship"
    if WORKING_STUDENT.search(title):
        return Factor("role_type", 40, "Working-student role: usually needs enrolment at a local university")
    if kind in ("internship", "research_internship"):
        return Factor("role_type", 100, "Internship — the right step now")
    if kind in ("program", "fellowship"):
        return Factor("role_type", 100, "Funded programme — the right step now")
    if kind == "part_time":
        return Factor("role_type", 75, "Part-time — can fit around term")
    if kind in ("contract", "freelance"):
        return Factor("role_type", 60, f"{kind.title()} work")
    if JUNIOR.search(title):
        return Factor("role_type", 40, "Full-time entry-level job — usually needs a finished degree")
    return Factor("role_type", 20, "Full-time job — a later step in your plan")


def f_compensation(opp: dict[str, Any]) -> Factor:
    status, ratio = opp.get("pay_status"), opp.get("pay_ratio")
    benefits = opp.get("benefits") or {}
    inr = opp.get("pay_monthly_inr_min")
    if status == "listed" and ratio is not None:
        score = 100 if ratio >= 1.5 else 85 if ratio >= 1.2 else 70 if ratio >= 1.0 else 25
        money = f"₹{inr:,.0f}/month, " if inr else ""
        return Factor("compensation", score, f"{money}{ratio:.2f}× living cost")
    if benefits.get("housing") and benefits.get("meals"):
        return Factor("compensation", 90, "Funded: housing and meals covered")
    if status == "variable":
        return Factor("compensation", 55, "Pay varies (hourly, hours not stated)")
    return Factor("compensation", 50, "Pay not stated")


def f_company(opp: dict[str, Any], text: str, c: dict[str, Any], programme: bool) -> tuple[Factor, str | None]:
    name = (opp.get("company_name") or "").lower()
    pts = c.get("company_points") or {}
    if opp.get("known_mill"):
        return Factor("company", 0, "Known internship mill"), None
    for tier in ("a", "b"):
        for comp in (c.get("companies") or {}).get(tier, []):
            if re.search(rf"(^|\W){re.escape(comp.lower())}(\W|$)", name):
                label = "Top AI employer / programme" if tier == "a" else "Strong tech employer"
                return Factor("company", _clamp(pts.get(tier, 100 if tier == "a" else 80)), f"{label} ({comp})"), tier
    if programme:
        return Factor("company", 95, "Recognised research / funded programme"), "a"
    kind = (opp.get("canonical_key") or "").split(":", 1)[0]
    if kind in ("greenhouse", "lever", "ashby"):
        return Factor("company", _clamp(pts.get("ats_listed", 60)), "Established company (public job board)"), None
    return Factor("company", _clamp(pts.get("unknown", 55)), "Company not on your target lists"), None


def track_of(title: str, c: dict[str, Any]) -> tuple[str, list[str]]:
    tracks = c.get("tracks") or {}
    for key in ("core", "stepping_stone"):
        hits = _any((tracks.get(key) or {}).get("title_patterns", []), title)
        if hits:
            return key, hits
    return "other", []


def f_ai_relevance(title: str, text: str, c: dict[str, Any], company_tier: str | None) -> tuple[Factor, str]:
    track, _ = track_of(title, c)
    base = {"core": 80, "stepping_stone": 50}.get(track, 15)
    body = _any(c.get("ai_body_terms") or [], text)
    score = base + min(20, 4 * len(body)) + (10 if track != "core" and company_tier == "a" else 0)
    label = ((c.get("tracks") or {}).get(track) or {}).get("label", track)
    why = f"{label} role" + (f"; the work mentions {', '.join(body[:4])}" if body else "")
    return Factor("ai_relevance", _clamp(score), why), track


def f_eligibility(status: str, confidence: float | None) -> Factor:
    conf = confidence if confidence is not None else 0.7
    if status == "eligible":
        return Factor("eligibility", _clamp(100 * conf), f"Eligible (confidence {conf:.2f})")
    if status == "eligible_gaps":
        return Factor("eligibility", _clamp(85 * conf), f"Eligible with skill gaps (confidence {conf:.2f})")
    if status == "needs_info":
        return Factor("eligibility", 50, "You confirmed eligibility; the posting was unclear")
    return Factor("eligibility", 50, "Eligibility not fully checked")


def f_career_value(track: str, company_tier: str | None, programme: bool, region: dict[str, Any],
                   text: str) -> Factor:
    score = {"core": 70, "stepping_stone": 50}.get(track, 15)
    why = [{"core": "direct AI/ML experience", "stepping_stone": "adjacent experience"}.get(track, "off your path")]
    if company_tier == "a":
        score += 20
        why.append("a name that opens doors")
    elif company_tier == "b":
        score += 10
        why.append("a strong employer")
    if programme:
        score += 15
        why.append("research exposure")
    if region.get("tier") == 1:
        score += 10
        why.append("in a priority region")
    if MENTOR.search(text):
        score += 5
        why.append("mentoring/training mentioned")
    text_why = "; ".join(why)
    return Factor("career_value", _clamp(score), text_why[:1].upper() + text_why[1:])


# ── total ─────────────────────────────────────────────────────────────────────────────────────────────
def match_score(opp: dict[str, Any], *, text: str, eligibility_confidence: float | None, eligibility_status: str,
                deadline: str = "open", draft_threshold: int = 60,
                config_dir: Path | None = None) -> tuple[int, dict[str, Any]]:
    c = career(config_dir)
    weights = {**DEFAULT_WEIGHTS, **(c.get("weights") or {})}
    title = opp.get("title") or ""
    body = f"{title}\n{text or ''}"
    programme = bool(_any(c.get("programme_words") or [], f"{title} {opp.get('company_name', '')} {text or ''}")) \
        or opp.get("kind") in ("program", "fellowship")
    skills, have, gaps = f_skills(body)
    loc, region = f_location(opp, body, c)
    company, tier = f_company(opp, body, c, programme)
    ai, track = f_ai_relevance(title, body, c, tier)
    career_v = f_career_value(track, tier, programme, region, body)
    factors = [skills, f_projects(body, c), f_education(body, title, opp.get("kind") or "internship"),
               f_experience(body, opp.get("kind") or "internship"), loc, f_visa(opp, body, programme),
               f_role_type(opp, title, body), f_compensation(opp), company, ai,
               f_eligibility(eligibility_status, eligibility_confidence), career_v]
    exception = None
    g = c.get("global_exception") or {}
    if region.get("tier") is None and loc.score < int(g.get("location_floor", 70)) and \
            ai.score >= int(g.get("min_ai_relevance", 90)) and career_v.score >= int(g.get("min_career_value", 80)):
        loc.score = int(g.get("location_floor", 70))
        loc.why += " — unusually relevant, so HQ keeps it anyway"
        exception = "Outside your priority regions but unusually relevant"
    total_w = sum(float(weights.get(f.key, 0)) for f in factors) or 100.0
    rows = [f.as_dict(round(100 * float(weights.get(f.key, 0)) / total_w, 2)) for f in factors]
    total = _clamp(sum(r["points"] for r in rows))
    floor = int(c.get("consider_floor", 45))
    verdict = "apply" if total >= draft_threshold else "consider" if total >= floor else "skip"
    tracks = c.get("tracks") or {}
    ordered = sorted(rows, key=lambda r: -r["points"])
    return total, {
        "version": 2, "total": total, "verdict": verdict,
        "verdict_why": {"apply": f"{total} ≥ {draft_threshold}: worth an application",
                        "consider": f"{total} is between {floor} and {draft_threshold}: parked — one click applies anyway",
                        "skip": f"{total} < {floor}: not a good use of an application"}[verdict],
        "track": track, "track_label": (tracks.get(track) or {}).get("label", track),
        "stepping_stone_why": (tracks.get("stepping_stone") or {}).get("why") if track == "stepping_stone" else None,
        "region": region, "exception": exception, "factors": rows,
        "skills_matched": have, "skill_gaps": gaps,
        "highlights": [r["why"] for r in ordered if r["score"] >= 80][:4],
        "concerns": [r["why"] for r in sorted(rows, key=lambda r: r["score"]) if r["score"] <= 40][:4],
    }


def fit_score(opp: dict[str, Any], *, text: str, eligibility_confidence: float | None, eligibility_status: str,
              deadline: str, draft_threshold: int = 60) -> tuple[int, dict[str, Any]]:
    """Kept name for callers: the match score."""
    return match_score(opp, text=text, eligibility_confidence=eligibility_confidence,
                       eligibility_status=eligibility_status, deadline=deadline, draft_threshold=draft_threshold)


def simulated_breakdown(total: int, seed: str, draft_threshold: int = 60) -> dict[str, Any]:
    """Demo data for simulated opportunities: plausible factors around the simulated total (marked simulated)."""
    rng = random.Random(seed)
    weights = DEFAULT_WEIGHTS
    rows = []
    for key, w in weights.items():
        sc = _clamp(total + rng.randint(-18, 18))
        rows.append({"key": key, "label": FACTOR_LABELS[key], "score": sc, "weight": float(w),
                     "points": round(sc * w / 100, 1), "why": "Simulated opportunity (demo data)"})
    verdict = "apply" if total >= draft_threshold else "consider" if total >= 45 else "skip"
    return {"version": 2, "total": total, "verdict": verdict, "verdict_why": "Simulated", "simulated": True,
            "track": "core", "track_label": "Core AI/ML", "region": {}, "exception": None, "factors": rows,
            "skills_matched": [], "skill_gaps": [], "highlights": [], "concerns": []}
