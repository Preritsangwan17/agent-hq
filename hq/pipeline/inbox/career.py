"""Conservative, source-linked career facts from untrusted email.

This module never follows email links. A company is verified only against a previously
checked public posting and Gmail's authentication result; email claims alone cannot do it.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from hq.gmail.api import GmailMessage
from hq.pipeline.inbox.rules import is_free_mail, sender_parts

ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com",
             "workable.com", "icims.com")
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "cutt.ly", "shorturl.at", "is.gd", "ow.ly"}
BAD_LINK = re.compile(r"\.(?:exe|dmg|pkg|msi|bat|cmd|scr|apk)(?:$|[?#])", re.I)
URL = re.compile(r"https?://[^\s<>\"']+", re.I)
MONEY = re.compile(r"\b(?:pay|transfer|send)\s+(?:a\s+)?(?:fee|deposit|money|amount|security deposit)|"
                   r"\b(?:training|registration|processing)\s+fee\b|\bgift\s*cards?\b|"
                   r"\b(?:crypto|bitcoin|usdt)\s+payment\b", re.I)
SECRETS = re.compile(r"\b(?:password|one.time password|otp|verification code|bank (?:account|details)|"
                     r"credit card|debit card)\b", re.I)

FIELD_LABELS: dict[str, str] = {
    "interview_date": r"(?:interview date|interview scheduled for)",
    "interview_time": r"(?:interview time)",
    "interview_link": r"(?:interview link|meeting link)",
    "assessment_deadline": r"(?:assessment deadline|test deadline)",
    "assessment_link": r"(?:assessment link|test link)",
    "salary_or_stipend": r"(?:salary|stipend|compensation|pay)",
    "location": r"(?:work location|job location|office address)",
    "reporting_location": r"(?:reporting location|report at)",
    "work_mode": r"(?:work mode|working model|remote/hybrid/onsite)",
    "start_date": r"(?:start date|employment starts|internship starts)",
    "joining_date": r"(?:joining date|date of joining|join on)",
    "reporting_time": r"(?:reporting time|report at)",
    "reporting_manager": r"(?:reporting manager|report to)",
    "offer_deadline": r"(?:offer deadline|accept(?:ance)? deadline|respond by)",
    "documents_required": r"(?:documents required|documents to (?:bring|submit)|required documents)",
    "background_verification": r"(?:background verification|background check)",
    "hr_contact": r"(?:hr contact|recruiter contact)",
    "employee_portal": r"(?:employee portal|intern portal)",
    "onboarding_link": r"(?:onboarding link|onboarding portal|onboarding form)",
    "orientation_link": r"(?:orientation link|orientation meeting)",
    "orientation": r"(?:orientation|induction)",
    "equipment": r"(?:laptop|equipment)",
    "travel_or_accommodation": r"(?:travel|accommodation|housing)",
}
CHECKS = {
    "assessment": ("Complete the assessment", r"\b(?:assessment|coding test|online test)\b"),
    "interview": ("Attend the interview", r"\binterview\b"),
    "offer_letter": ("Review the offer letter", r"offer letter"),
    "acceptance": ("Confirm your decision on the offer", r"accept(?: the)? offer|offer deadline"),
    "onboarding_form": ("Complete the onboarding form", r"onboarding form|employee portal"),
    "documents": ("Submit the requested documents", r"documents (?:required|to submit)|upload (?:your )?documents"),
    "background_check": ("Complete background verification", r"background (?:check|verification)"),
    "joining_date": ("Confirm the joining date", r"joining date|date of joining"),
    "orientation": ("Attend orientation", r"orientation|induction"),
    "reporting": ("Report at the stated location or link", r"reporting location|reporting time|report at"),
}


def _host(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _within(host: str, domain: str) -> bool:
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def _official_hosts(opp: dict[str, Any] | None) -> list[str]:
    if not opp:
        return []
    candidates = [opp.get("company_domain"), _host(opp.get("url")), _host(opp.get("apply_url"))]
    email = opp.get("apply_email") or ""
    if "@" in email:
        candidates.append(email.rsplit("@", 1)[1].lower())
    return list(dict.fromkeys(h.removeprefix("www.") for h in candidates if h and not any(_within(h, a) for a in ATS_HOSTS)
                              and h not in ("linkedin.com", "indeed.com", "internshala.com")))


def assess(msg: GmailMessage, opp: dict[str, Any] | None) -> dict[str, Any]:
    sender = sender_parts(msg.from_addr)[1]
    official = _official_hosts(opp)
    match = any(_within(sender, h) for h in official)
    ats = any(_within(sender, h) for h in ATS_HOSTS)
    reasons: list[str] = []
    sources: list[dict[str, str]] = []
    for field in ("url", "apply_url"):
        link = (opp or {}).get(field)
        if link and str(link).startswith("https://"):
            sources.append({"kind": "public_posting", "url": str(link),
                            "checked": bool((opp or {}).get("link_status") == "live")})
    if match:
        reasons.append(f"Sender domain {sender} matches a domain in the application record.")
    elif ats and opp:
        reasons.append(f"Sender uses recruiting platform {sender}; check the specific job link.")
    else:
        reasons.append(f"Sender domain {sender or 'unknown'} has no established match to the company.")
    personal_claim = is_free_mail(msg.from_addr) and bool(official)
    if personal_claim:
        reasons.append("A personal email account claims to represent this company.")
    auth = (msg.headers.get("authentication-results") or "").lower()
    auth_match = re.search(r"\bdmarc=pass\b[^;]*\bheader\.from=([a-z0-9.-]+)", auth)
    dmarc_pass = bool(auth_match and _within(sender, auth_match.group(1)))
    dmarc_fail = bool(re.search(r"\bdmarc=(?:fail|reject)\b", auth))
    if dmarc_fail:
        reasons.append("Gmail reports failed DMARC authentication.")
    elif dmarc_pass:
        reasons.append("Gmail reports DMARC pass; this does not prove the offer is genuine.")
    suspicious = bool(dmarc_fail or personal_claim)
    text = f"{msg.subject}\n{msg.body_text[:20_000]}"
    if MONEY.search(text):
        reasons.append("The message asks for a fee, deposit, money, gift cards, or crypto.")
        suspicious = True
    if SECRETS.search(text):
        reasons.append("The message requests sensitive credentials or financial details.")
        suspicious = True
    links: list[dict[str, str]] = []
    link_issue = False
    for raw in URL.findall(text)[:30]:
        link = raw.rstrip(".,);]")
        host = _host(link)
        links.append({"url": link, "host": host})
        try:
            parsed = urlparse(link)
            unusual = "@" in parsed.netloc or bool(BAD_LINK.search(parsed.path))
        except ValueError:
            unusual = True
        if host in SHORTENERS or not host or unusual:
            reasons.append(f"Review the shortened, unusual, or executable link: {host or 'unknown host'}.")
            suspicious = True
        elif opp and not (any(_within(host, h) for h in official) or any(_within(host, h) for h in ATS_HOSTS)
                              or host in ("calendly.com", "zoom.us", "meet.google.com", "teams.microsoft.com")):
            reasons.append(f"Link domain {host} is not in the known company or recruiting domains.")
            link_issue = True
    sources += [{"kind": "email_link_unverified", "url": x["url"], "checked": False} for x in links]
    if suspicious:
        verdict = "Potentially Suspicious"
    elif link_issue:
        verdict = "Needs Review"
    elif (match and dmarc_pass and (opp or {}).get("link_status") == "live"
          and str((opp or {}).get("canonical_key") or "").split(":", 1)[0] in ("greenhouse", "lever", "ashby")):
        verdict = "Verified Company"
    elif match or ats:
        verdict = "Likely Legitimate"
    else:
        verdict = "Needs Review"
    if not sources:
        reasons.append("No independently checked public posting is attached to this application.")
    return {"verification": verdict, "reasons": list(dict.fromkeys(reasons)), "sources": sources,
            "sender_domain": sender}


def stage_for(label: str, body: str, current_stage: str | None = None) -> str | None:
    lower = body.lower()
    if label == "rejection":
        return "Rejected"
    if re.search(r"\b(?:we confirm your acceptance|your acceptance has been recorded)\b", lower):
        return "Accepted"
    if current_stage in ("Accepted", "Joining/Onboarding") and re.search(
            r"\b(?:joining instructions|orientation schedule|onboarding instructions)\b", lower):
        return "Joining/Onboarding"
    if label == "offer":
        return "Offer"
    if label == "selected":
        return "Selected"
    return {"auto_ack": "Confirmation", "assessment": "Assessment", "interview_invite": "Interview",
            "info_request": "HR Discussion", "legal": "HR Discussion"}.get(label)


def extract(body: str, message_id: str, occurred_at: str, verification: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Only explicitly labeled lines and safe HTTPS links become facts. Every fact keeps its email source."""
    facts: dict[str, Any] = {}
    for line in body.splitlines()[:250]:
        clean = line.strip()[:500]
        for key, label in FIELD_LABELS.items():
            m = re.match(rf"^(?:{label})\s*[:\-]\s*(.{{2,300}})$", clean, re.I)
            if m and key not in facts:
                value = m.group(1).strip()
                is_link = key.endswith("_link") or key == "employee_portal"
                if is_link:
                    value = value.rstrip(".,);")
                if is_link and (not value.startswith("https://") or not _host(value)):
                    continue
                facts[key] = {"value": value, "source_message_id": message_id,
                              "source_date": occurred_at,
                              "official": verification == "Verified Company" and not is_link}
    items = []
    for key, (title, pattern) in CHECKS.items():
        if re.search(pattern, body, re.I):
            items.append({"key": key, "title": title, "source_message_id": message_id})
    return facts, items
