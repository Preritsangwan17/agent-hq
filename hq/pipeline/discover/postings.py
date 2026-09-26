"""RawPosting: one job read from a source, normalised across ATS vendors, and its opportunity row values."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from hq import settings as paths
from hq.pipeline.discover.location import parse_location
from hq.util.ids import new_id


@dataclass
class RawPosting:
    source_id: str
    source_kind: str               # greenhouse | lever | ashby | program_page | manual | email_alert
    external_id: str
    company: str
    title: str
    url: str
    text: str = ""
    location_raw: str | None = None
    apply_url: str | None = None
    posted_at: str | None = None
    pay_raw: str | None = None
    employment_type: str | None = None
    remote: bool | None = None
    department: str | None = None
    automation: str = "discover_only"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_key(self) -> str:
        return f"{self.source_kind}:{self.source_id.split(':', 1)[-1]}:{self.external_id}"


def kind_for(title: str, employment_type: str | None) -> str:
    t = f"{title} {employment_type or ''}".lower()
    if re.search(r"\bfellow", t):
        return "fellowship"
    if re.search(r"\bresearch\b.*\bintern|\bintern.*\bresearch\b", t):
        return "research_internship"
    if re.search(r"\bintern|co-?op|trainee|werkstudent|working student|apprentice", t):
        return "internship"
    if re.search(r"part[- ]time", t):
        return "part_time"
    if re.search(r"freelance", t):
        return "freelance"
    if re.search(r"contract", t):
        return "contract"
    return "job"


def role_type_for(title: str) -> str:
    t = title.lower()
    if re.search(r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|nlp|computer vision|llm|genai", t):
        return "ml"
    if re.search(r"research", t):
        return "research"
    if re.search(r"data", t):
        return "data"
    if re.search(r"software|engineer|developer|sde|swe|backend|frontend|full[- ]stack|platform", t):
        return "software"
    return "other"


def description_path(opp_id: str, text: str) -> tuple[str, str]:
    d = paths.DATA / "postings"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{opp_id}.txt"
    p.write_text(text)
    return str(p), hashlib.sha256(text.encode()).hexdigest()


def opportunity_values(p: RawPosting, *, source_label: str) -> dict[str, Any]:
    place = parse_location(p.location_raw, remote_flag=p.remote)
    opp_id = new_id()
    path, digest = description_path(opp_id, p.text) if p.text else (None, None)
    return {
        "id": opp_id, "canonical_key": p.canonical_key, "company_name": p.company.strip()[:120],
        "title": p.title.strip()[:200], "kind": kind_for(p.title, p.employment_type), "role_type": role_type_for(p.title),
        "location_raw": (p.location_raw or "")[:200] or None, "city": place.city, "country_iso2": place.country_iso2,
        "lat": place.lat, "lon": place.lon, "work_mode": place.work_mode, "url": p.url, "apply_url": p.apply_url or p.url,
        "apply_channel": "ats_form" if p.source_kind in ("greenhouse", "lever", "ashby") else "manual",
        "posted_at": p.posted_at, "pay_raw": p.pay_raw, "stage": "found", "source_label": source_label,
        "automation": p.automation, "description_path": path, "desc_hash": digest,
    }
