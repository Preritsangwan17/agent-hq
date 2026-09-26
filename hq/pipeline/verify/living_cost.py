"""Monthly living cost per city (config/living_costs.csv) converted to INR at lookup time, plus city coordinates.

Phase (a) values are PROVISIONAL student-level estimates (confidence "provisional"); phase (c) replaces them with
sourced figures. Remote roles are costed at the IN-home baseline because Prerit works from India. An unknown city
returns (None, "unseeded", None) so the verifier can raise a decision instead of guessing.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from hq import settings
from hq.pipeline.verify.fx import FxUnavailable

LIVING_COSTS_CSV = settings.CONFIG_DIR / "living_costs.csv"
CITIES_CSV = settings.CONFIG_DIR / "cities.csv"
HOME_KEY = "IN-home"
UNSEEDED = "unseeded"

# Spellings seen on job boards -> the canonical city name used in the CSVs.
CITY_ALIASES = {
    "bangalore": "bengaluru", "bengaluru urban": "bengaluru", "gurgaon": "gurugram", "new delhi": "delhi",
    "delhi ncr": "delhi", "bombay": "mumbai", "navi mumbai": "mumbai", "calcutta": "kolkata", "madras": "chennai",
    "secunderabad": "hyderabad", "sf": "san francisco", "san francisco bay area": "san francisco",
    "bay area": "san francisco", "nyc": "new york", "new york city": "new york", "munchen": "munich",
    "taipei city": "taipei", "new taipei": "taipei", "chiayi city": "chiayi", "chiayi county": "chiayi",
    "minxiong": "chiayi", "ecublens": "lausanne", "the hague": "amsterdam", "warszawa": "warsaw",
}


class FxProvider(Protocol):
    def rate(self, from_ccy: str, to_ccy: str = "INR") -> tuple[float, str, str]: ...


@dataclass(frozen=True)
class LivingCostEntry:
    key: str
    country_iso2: str
    city: str
    currency: str
    monthly_local: float
    basis: str
    confidence: str
    source_note: str
    as_of: str
    monthly_inr_fixed: float | None = None   # only when the CSV carries a monthly_inr column


def _clean(name: str | None) -> str:
    """Lower-case, accent-free, punctuation-free form of a place name."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def normalize_city(name: str | None) -> str:
    """Cleaned and alias-resolved city key (Bangalore -> bengaluru, Gurgaon -> gurugram, ...)."""
    text = _clean(name)
    return CITY_ALIASES.get(text, text)


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def load_entries(path: Path = LIVING_COSTS_CSV) -> list[LivingCostEntry]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    entries = []
    for row in rows:
        monthly_local = _float(row.get("monthly_local"))
        monthly_inr = _float(row.get("monthly_inr"))
        currency = (row.get("currency") or "").strip().upper() or "INR"
        if monthly_local is None and monthly_inr is not None:
            monthly_local, currency = monthly_inr, "INR"
        if monthly_local is None:
            continue
        entries.append(LivingCostEntry(
            key=row["key"].strip(), country_iso2=(row.get("country_iso2") or "").strip().upper(),
            city=(row.get("city") or "").strip(), currency=currency, monthly_local=monthly_local,
            basis=(row.get("basis") or "").strip(), confidence=(row.get("confidence") or "provisional").strip(),
            source_note=(row.get("source_note") or "").strip(), as_of=(row.get("as_of") or "").strip(),
            monthly_inr_fixed=monthly_inr,
        ))
    return entries


class LivingCosts:
    def __init__(self, csv_path: Path | None = None, fx: FxProvider | None = None):
        self.csv_path = Path(csv_path) if csv_path else LIVING_COSTS_CSV
        self._fx = fx
        self._entries: list[LivingCostEntry] | None = None

    @property
    def fx(self) -> FxProvider:
        if self._fx is None:
            from hq.pipeline.verify import fx as fx_module
            return fx_module.default()
        return self._fx

    def entries(self) -> list[LivingCostEntry]:
        if self._entries is None:
            self._entries = load_entries(self.csv_path)
        return self._entries

    def by_key(self, key: str) -> LivingCostEntry | None:
        return next((e for e in self.entries() if e.key == key), None)

    def find(self, city: str | None, country_iso2: str | None = None) -> LivingCostEntry | None:
        wanted = normalize_city(city)
        if not wanted:
            return None
        country = (country_iso2 or "").upper()
        matches = [e for e in self.entries() if e.key != HOME_KEY and normalize_city(e.city) == wanted]
        if country:
            matches = [e for e in matches if e.country_iso2 == country]
        return matches[0] if len(matches) == 1 else None

    def monthly_inr(self, entry: LivingCostEntry) -> float | None:
        if entry.monthly_inr_fixed is not None:
            return entry.monthly_inr_fixed
        if entry.currency == "INR":
            return entry.monthly_local
        try:
            rate, _, _ = self.fx.rate(entry.currency, "INR")
        except FxUnavailable:
            return None
        return round(entry.monthly_local * rate)

    def lookup(self, city: str | None, country_iso2: str | None = None,
               work_mode: str | None = None) -> tuple[float | None, str, str | None]:
        """(monthly_inr, basis, confidence). Remote -> IN-home baseline; unseeded city -> (None, 'unseeded', None)."""
        entry = self.by_key(HOME_KEY) if (work_mode or "").lower() == "remote" else self.find(city, country_iso2)
        if entry is None:
            return None, UNSEEDED, None
        value = self.monthly_inr(entry)
        where = entry.city if entry.key == HOME_KEY else f"{entry.city}, {entry.country_iso2}"
        basis = f"{where} [{entry.key}]: {entry.currency} {entry.monthly_local:,.0f}/mo; {entry.basis}"
        if value is None:
            basis += " (no FX rate for INR conversion)"
        return value, basis, entry.confidence


_default: LivingCosts | None = None


def default() -> LivingCosts:
    global _default
    if _default is None:
        _default = LivingCosts()
    return _default


def lookup(city: str | None, country_iso2: str | None = None,
           work_mode: str | None = None) -> tuple[float | None, str, str | None]:
    return default().lookup(city, country_iso2, work_mode)


@lru_cache(maxsize=4)
def _load_cities(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {(_clean(r["city"]), r["country_iso2"].strip().upper()): (float(r["lat"]), float(r["lon"]))
                for r in csv.DictReader(fh)}


def city_coords(city: str | None, country_iso2: str | None = None,
                path: Path = CITIES_CSV) -> tuple[float, float] | None:
    """(lat, lon) from config/cities.csv, or None. Exact name first, then its alias; country narrows ambiguity."""
    cities = _load_cities(path)
    country = (country_iso2 or "").upper()
    for name in dict.fromkeys((_clean(city), normalize_city(city))):
        if not name:
            continue
        if country and (name, country) in cities:
            return cities[(name, country)]
        hits = [coords for (n, c), coords in cities.items() if n == name and (not country or c == country)]
        if len(hits) == 1:
            return hits[0]
    return None
