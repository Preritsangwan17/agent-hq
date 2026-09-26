"""Location strings → (city, country_iso2, work_mode, lat, lon) using config/cities.csv plus country hints."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache

from hq import settings as paths

COUNTRY_HINTS = {
    "india": "IN", "united states": "US", "usa": "US", "u.s.": "US", "united kingdom": "GB", "uk": "GB",
    "england": "GB", "germany": "DE", "switzerland": "CH", "taiwan": "TW", "japan": "JP", "singapore": "SG",
    "canada": "CA", "united arab emirates": "AE", "uae": "AE", "netherlands": "NL", "france": "FR", "ireland": "IE",
    "spain": "ES", "poland": "PL", "australia": "AU", "israel": "IL", "sweden": "SE", "korea": "KR", "brazil": "BR",
}
US_STATES = {"ca", "ny", "wa", "tx", "ma", "il", "co", "ga", "az", "nj", "pa", "va", "dc", "or", "fl", "nc", "ut", "mn"}
ALIASES = {"bangalore": "Bengaluru", "gurgaon": "Gurugram", "new delhi": "Delhi", "bombay": "Mumbai", "sf": "San Francisco",
           "nyc": "New York", "new york city": "New York", "zurich": "Zürich", "munchen": "Munich", "münchen": "Munich"}


@dataclass
class Place:
    city: str | None
    country_iso2: str | None
    work_mode: str
    lat: float | None = None
    lon: float | None = None


@lru_cache(maxsize=1)
def _cities() -> dict[str, tuple[str, str, float, float]]:
    out = {}
    path = paths.CONFIG_DIR / "cities.csv"
    if path.exists():
        with path.open() as f:
            for row in csv.DictReader(f):
                out[row["city"].lower()] = (row["city"], row["country_iso2"], float(row["lat"]), float(row["lon"]))
    return out


def parse_location(raw: str | None, *, remote_flag: bool | None = None) -> Place:
    text = (raw or "").strip()
    low = text.lower()
    mode = "remote" if remote_flag or re.search(r"\bremote\b|work from home|wfh|anywhere", low) else \
        "hybrid" if "hybrid" in low else ("onsite" if text else "unknown")
    cities = _cities()
    first = re.split(r"[;|/]| or ", text)[0] if text else ""
    parts = [p.strip() for p in re.split(r",|\(|\)|-", first) if p.strip()]
    city = country = None
    lat = lon = None
    for p in parts:
        key = ALIASES.get(p.lower(), p).lower()
        if key in cities:
            city, country, lat, lon = cities[key]
            break
    if country is None:
        for name, iso in COUNTRY_HINTS.items():
            if re.search(rf"\b{re.escape(name)}\b", low):
                country = iso
                break
    if country is None and any(p.lower() in US_STATES for p in parts):
        country = "US"
    if city is None and parts and parts[0].lower() not in COUNTRY_HINTS and "remote" not in parts[0].lower():
        city = parts[0][:60]
    return Place(city, country, mode, lat, lon)
