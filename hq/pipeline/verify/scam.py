"""Scam check (PLAN §3, CONTRACT_C §4): fees (incl. application fees), known mills, certificate-only offers, a
free-mail recruiter for a brand-name company, lookalike domains, early ID/bank requests, crypto/cheque language.
Fees and mills are decisive; the rest add up (2+ signals → suspicious)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from hq import settings as paths
from hq.util import netguard


@dataclass
class ScamResult:
    verdict: str                      # clean | suspicious | scam
    signals: list[dict[str, str]] = field(default_factory=list)
    fee: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "signals": self.signals, "fee": self.fee}


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def lexicon() -> dict[str, Any]:
    p = paths.CONFIG_DIR / "scam_lexicon.yaml"
    return _load(str(p), p.stat().st_mtime)


def mills() -> list[str]:
    p = paths.CONFIG_DIR / "known_mills.yaml"
    data = _load(str(p), p.stat().st_mtime) if p.exists() else {}
    return [m["name"] for m in data.get("mills") or [] if isinstance(m, dict) and m.get("name")]


def _brand_of(company: str, brands: list[str]) -> str | None:
    low = company.lower()
    return next((b for b in brands if re.search(rf"\b{re.escape(b)}\b", low)), None)


def check_scam(*, company: str, text: str, url: str | None = None, apply_email: str | None = None) -> ScamResult:
    lex = lexicon()
    low = " ".join((text or "").split()).lower()
    signals: list[dict[str, str]] = []

    def sig(kind: str, what: str) -> None:
        signals.append({"kind": kind, "evidence": what[:200]})

    fee = False
    for pat in lex.get("fee", []):
        m = re.search(pat, low)
        if m and not re.search(r"\b(no|without any|free of|zero|never (ask|charge)|don't charge|do not charge)\b[^.]{0,30}$",
                               low[max(0, m.start() - 40):m.start()]):
            sig("fee", m.group(0))
            fee = True
            break
    for name in mills():
        if name.lower() in (company or "").lower() or name.lower() in low:
            sig("known_mill", name)
    for key in ("certificate_only", "id_bank_request", "money_language"):
        for pat in lex.get(key, []):
            m = re.search(pat, low)
            if m:
                sig(key, m.group(0))
                break
    brand = _brand_of(company or "", lex.get("brand_names", []))
    if apply_email:
        domain = apply_email.split("@")[-1].lower()
        if domain in lex.get("free_mail_domains", []) and brand:
            sig("free_mail_brand", f"{company} recruiting from {domain}")
    if brand and url:
        host = netguard.host_of(url)
        core = host.split(".")[-2] if host.count(".") >= 1 else host
        if brand not in host and fuzz.ratio(brand, core) >= 75:
            sig("lookalike_domain", host)
    decisive = fee or any(s["kind"] == "known_mill" for s in signals)
    verdict = "scam" if decisive else ("suspicious" if len(signals) >= 2 else "clean")
    if not decisive and len(signals) == 1 and signals[0]["kind"] in ("money_language", "id_bank_request") and \
            re.search(r"\b(send|share|provide|pay|transfer)\b", low):
        verdict = "suspicious"
    return ScamResult(verdict, signals, fee)
