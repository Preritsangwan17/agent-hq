"""Deterministic inbox rules (CONTRACT_D §2): labels, notify-only lock kinds and the items an info request asks for.

These run on every inbound message before the classifier model. A lock found here is final — the model can add a
lock but never remove one. Email text is untrusted data; nothing in it is ever executed or followed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths

FREE_MAIL = {"gmail", "outlook", "hotmail", "yahoo", "rediffmail", "proton", "protonmail", "icloud", "aol", "zoho",
             "yandex", "gmx", "mail"}
LOCK_NEED_KIND = {"interview": "interview", "assessment": "assessment", "offer": "offer", "legal": "legal",
                  "documents": "legal", "money": "money", "profile": "missing_info"}
LOCK_PRIORITY = ["money", "offer", "legal", "documents", "assessment", "interview", "profile"]
LABELS = ("interview_invite", "assessment", "info_request", "rejection", "auto_ack", "offer", "selected", "scam", "legal",
          "job_alert", "other")


@dataclass
class RuleResult:
    label: str | None
    lock_kinds: list[str] = field(default_factory=list)
    lock_terms: list[str] = field(default_factory=list)
    requested: list[str] = field(default_factory=list)
    sender_kind: str | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def lock(self) -> bool:
        return bool(self.lock_kinds)

    @property
    def lock_kind(self) -> str | None:
        return next((k for k in LOCK_PRIORITY if k in self.lock_kinds), None)

    def only_allowed_items(self) -> bool:
        allowed = set(config().get("allowed_items") or [])
        return bool(self.requested) and set(self.requested) <= allowed

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "lock": self.lock, "lock_kinds": self.lock_kinds, "lock_terms": self.lock_terms,
                "requested": self.requested, "sender_kind": self.sender_kind, "reasons": self.reasons}


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def config() -> dict[str, Any]:
    p = paths.CONFIG_DIR / "inbox_rules.yaml"
    return _load(str(p), p.stat().st_mtime)


@lru_cache(maxsize=512)
def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


def _hits(patterns: list[str] | None, text: str) -> list[str]:
    out = []
    for p in patterns or []:
        out += [m.group(0).strip() for m in _rx(p).finditer(text)]
    return out


def normalize(text: str) -> str:
    return " ".join((text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').split())


def sender_parts(from_addr: str) -> tuple[str, str, str]:
    """(local part, domain, core name) — core is the registrable name, e.g. talent@mail.lever.co → lever."""
    m = re.search(r"([\w.+-]+)@([\w.-]+)", from_addr or "")
    if not m:
        return "", "", ""
    local, domain = m.group(1).lower(), m.group(2).lower().rstrip(".")
    parts = domain.split(".")
    core = parts[-3] if len(parts) >= 3 and parts[-2] in ("co", "ac", "com", "org", "net", "edu") and \
        len(parts[-1]) == 2 else (parts[-2] if len(parts) >= 2 else parts[0])
    return local, domain, core


def sender_kind(from_addr: str) -> str | None:
    cfg = config()
    local, domain, core = sender_parts(from_addr)
    labels = set(domain.split("."))
    if core in set(cfg.get("alert_senders") or []) and (re.search(r"alert|jobs?[-_.]|noreply|no-reply", local)
                                                         or core != "linkedin"):
        return "alert"
    if core in set(cfg.get("ats_senders") or []) or labels & set(cfg.get("ats_senders") or []):
        return "ats"
    return None


def is_free_mail(from_addr: str) -> bool:
    return sender_parts(from_addr)[2] in FREE_MAIL


def classify(subject: str, body: str, from_addr: str = "") -> RuleResult:
    cfg = config()
    lab = cfg.get("labels") or {}
    text = normalize(f"{subject}\n{body}")
    kind = sender_kind(from_addr)
    res = RuleResult(label=None, sender_kind=kind)

    rejection = _hits(cfg.get("rejection"), text)
    ack = _hits(cfg.get("auto_ack"), text)
    alert = _hits(cfg.get("job_alert"), text)
    if kind == "alert" and (alert or re.search(r"alert", sender_parts(from_addr)[0])):
        res.label, res.reasons = "job_alert", [f"alert sender ({sender_parts(from_addr)[1]})"] + alert[:2]
        return res  # marketing mail from job boards never locks or gets a reply

    # ── locks ────────────────────────────────────────────────────────────────────────────────────────
    soft_context = bool(rejection or ack)
    for lock_kind, patterns in (cfg.get("lock") or {}).items():
        if soft_context and lock_kind in ("interview", "assessment", "profile", "offer"):
            continue  # "we won't move forward to the interview stage" is not an invitation
        hits = _hits(patterns, text)
        if hits:
            res.lock_kinds.append(lock_kind)
            res.lock_terms += hits[:3]
    strong = _hits(lab.get("interview_strong"), text)
    if soft_context and strong and "interview" not in res.lock_kinds:
        res.lock_kinds.append("interview")      # a real scheduling signal inside an ack still locks
        res.lock_terms += strong[:2]

    # ── label (first match wins) ─────────────────────────────────────────────────────────────────────
    pay = _hits(lab.get("scam_pay"), text)
    ids_or_bank = [t for t in res.lock_terms if re.search(r"aadha|pan|passport|bank|kyc|id proof", t, re.I)]
    offer = _hits(lab.get("offer"), text)
    if pay or (ids_or_bank and (is_free_mail(from_addr) or ("certificate" in text.lower() and not offer))):
        res.label, res.reasons = "scam", ["asks for money" if pay else "asks for ID/bank details"] + (pay or ids_or_bank)[:2]
    elif rejection:
        res.label, res.reasons = "rejection", rejection[:2]
    elif offer:
        res.label, res.reasons = "offer", offer[:2]
    elif _hits(lab.get("selected"), text):
        res.label, res.reasons = "selected", _hits(lab.get("selected"), text)[:2]
    elif _hits(lab.get("legal"), text):
        res.label, res.reasons = "legal", _hits(lab.get("legal"), text)[:2]
    elif _hits(lab.get("assessment"), text) or kind == "ats" and re.search(r"hackerrank|codesignal|codility",
                                                                          sender_parts(from_addr)[2]):
        res.label, res.reasons = "assessment", _hits(lab.get("assessment"), text)[:2] or [sender_parts(from_addr)[1]]
    elif strong or (_hits(lab.get("interview_weak"), text) and not ack):
        res.label, res.reasons = "interview_invite", (strong or _hits(lab.get("interview_weak"), text))[:2]
    elif ack:
        res.label, res.reasons = "auto_ack", ack[:2]
    elif alert and kind == "alert":
        res.label, res.reasons = "job_alert", alert[:2]
    elif _hits(cfg.get("info_request"), text):
        res.label, res.reasons = "info_request", _hits(cfg.get("info_request"), text)[:2]
    if res.label in ("interview_invite",) and "interview" not in res.lock_kinds:
        res.lock_kinds.append("interview")
    if res.label == "assessment" and "assessment" not in res.lock_kinds:
        res.lock_kinds.append("assessment")
    if res.label == "offer" and "offer" not in res.lock_kinds:
        res.lock_kinds.append("offer")
    if res.label == "selected" and "offer" not in res.lock_kinds:
        res.lock_kinds.append("offer")
    if res.label == "scam" and "money" not in res.lock_kinds:
        res.lock_kinds.append("money")
    if res.label == "info_request" or (res.label is None and res.lock_kinds):
        res.requested = [k for k, p in (cfg.get("requested_items") or {}).items() if _rx(p).search(text)]
    return res


def need_kind_for(lock_kind: str | None, label: str | None) -> str:
    if lock_kind:
        return LOCK_NEED_KIND.get(lock_kind, "missing_info")
    return {"interview_invite": "interview", "assessment": "assessment", "offer": "offer", "selected": "offer", "legal": "legal",
            "scam": "money"}.get(label or "", "missing_info")
