"""Job-alert emails (CONTRACT_D §2): turn LinkedIn / Internshala / Naukri / ZipRecruiter… alert bodies into roles
WITHOUT fetching those sites. Each role becomes a manual-lane opportunity unless `ats_resolve` finds the same role on
the company's own Greenhouse / Lever / Ashby board (a compliant channel)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from hq.pipeline.discover.postings import RawPosting
from hq.pipeline.discover.titles import classify_title
from hq.pipeline.inbox.rules import sender_parts
from hq.util import netguard

ROLE_WORDS = r"(?:intern(?:ship)?|engineer|analyst|developer|scientist|researcher|trainee|associate|fellow(?:ship)?)"
URL = re.compile(r"https?://[^\s<>\"')\]]+")


@dataclass
class AlertRole:
    title: str
    company: str
    location: str | None = None
    url: str | None = None


def _clean(s: str) -> str:
    return " ".join(s.strip(" -–—:;,.·|•\t").split())


def parse_alert(subject: str, body: str) -> list[AlertRole]:
    roles: list[AlertRole] = []
    text = body or ""
    lines = [ln.strip() for ln in text.splitlines()]
    # 1. block format: Title / Company / Location / View job: URL   (LinkedIn, Naukri text parts)
    for i, ln in enumerate(lines):
        m = re.match(r"(?:view job|apply now|view details)\s*:?\s*(https?://\S+)", ln, re.I)
        if m:
            block = [x for x in lines[max(0, i - 4):i] if x and not URL.search(x)][-3:]
            if len(block) >= 2:
                roles.append(AlertRole(_clean(block[0]), _clean(block[1]), _clean(block[2]) if len(block) > 2 else None,
                                       m.group(1)))
    # 2. "New jobs matching <title> in <place>: Company - City; Company - City"
    m = re.search(r"jobs? matching (.+?) in ([A-Za-z ,]+?):\s*(.+?)(?:\.\s|View all|$)", text, re.I | re.S)
    if m:
        title = _clean(m.group(1))
        for part in re.split(r";|\n", m.group(3)):
            bits = [b for b in re.split(r"\s+[-–]\s+", part.strip()) if b.strip()]
            if bits and len(bits[0]) >= 2:
                roles.append(AlertRole(title, _clean(bits[0]), _clean(bits[1]) if len(bits) > 1 else None))
    # 3. "<Title> internship at <Company> (WFH, stipend …)"
    for m in re.finditer(rf"([A-Z][\w/&+.\- ]{{1,60}}?{ROLE_WORDS}[\w ]{{0,20}}?)\s+at\s+([A-Z][\w&.\- ]{{1,50}}?)"
                         r"(?:\s*\(([^)]{1,80})\))?(?=[,.;\n]| and |$)", text):
        roles.append(AlertRole(_clean(m.group(1)), _clean(m.group(2)), _clean(m.group(3) or "") or None))
    # 4. subject "<Title> at <Company>" / "<Company> has an open position"
    m = re.match(rf"(.+?{ROLE_WORDS}.*?)\s+at\s+(.+)$", subject or "", re.I)
    if m and not roles:
        roles.append(AlertRole(_clean(m.group(1)), _clean(m.group(2))))
    m = re.match(r"(.+?) has an open (?:position|role)", subject or "", re.I)
    if m and not roles:
        t = re.search(r"(?:a new |an? )?([\w/ ]{2,40}?) (?:role|position|job) matches", text, re.I)
        title = re.sub(r"^(?:a|an|the)\s+(?:new\s+)?", "", _clean(t.group(1)), flags=re.I) if t else "Open position"
        roles.append(AlertRole(title, _clean(m.group(1))))
    urls = URL.findall(text)
    if len(roles) == 1 and roles[0].url is None and urls:
        roles[0].url = urls[0]
    out, seen = [], set()
    for r in roles:
        key = (r.title.lower(), r.company.lower())
        if r.title and r.company and key not in seen and len(r.company) <= 60:
            seen.add(key)
            out.append(r)
    return out[:25]


def postings(subject: str, body: str, from_addr: str) -> list[RawPosting]:
    """Target roles from one alert email as RawPostings (manual lane when the alert came from a manual-lane site)."""
    _, domain, core = sender_parts(from_addr)
    lane = netguard.is_manual_lane(domain) or core in ("linkedin", "internshala", "naukri", "wellfound", "indeed",
                                                       "glassdoor", "foundit", "instahyre")
    out = []
    for r in parse_alert(subject, body):
        if not classify_title(r.title).target:
            continue
        ext = hashlib.sha1(f"{r.company}|{r.title}|{r.location}".lower().encode()).hexdigest()[:16]
        text = (f"{r.title} at {r.company}" + (f" ({r.location})" if r.location else "") +
                f". Seen in a {core or 'job-board'} alert email; the posting itself was not opened.")
        out.append(RawPosting("email:alerts", "email_alert", ext, r.company, r.title, r.url or "", text, r.location,
                              r.url or None, None, None, automation="manual_lane" if lane else "discover_only",
                              extra={"alert_sender": core, "manual_lane": lane}))
    return out
