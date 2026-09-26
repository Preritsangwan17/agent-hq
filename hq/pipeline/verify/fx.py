"""Currency conversion (default target INR) via the Frankfurter API, GET requests only.

Lookup order for a pair:
  1. same currency -> 1.0
  2. HQ_OFFLINE=1 -> committed seed (config/fx_seed.json) only
  3. today's entry in the day cache (data/fx/rates.json, i.e. next to the DB)
  4. live: Frankfurter v1 (ECB reference rates), then v2 for currencies the ECB does not publish (e.g. TWD, AED)
  5. most recent stale cache entry, then the seed
A failed network call marks the network down for a few minutes so a batch of lookups does not stall.

CLI: `python -m hq.pipeline.verify.fx USD TWD` prints rates; `--write-seed` refreshes config/fx_seed.json from live.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from hq import settings
from hq.util.timeutil import now_iso, today_ist

API_BASE = "https://api.frankfurter.dev"
SEED_PATH = settings.CONFIG_DIR / "fx_seed.json"
SEED_CURRENCIES = ("USD", "EUR", "GBP", "CHF", "TWD", "JPY", "SGD", "CAD", "AED", "AUD", "PLN", "QAR", "SAR",
                   "KRW", "HKD", "CNY")
SOURCE_V1 = "frankfurter v1 (ECB reference rate)"
SOURCE_V2 = "frankfurter v2"
ALIASES = {"NTD": "TWD", "RMB": "CNY", "RS": "INR"}
CACHE_KEEP_DAYS = 14
NETWORK_BACKOFF_S = 300.0


class FxUnavailable(LookupError):
    """No live, cached or seeded rate exists for the pair."""


@dataclass(frozen=True)
class FxQuote:
    rate: float
    date: str      # the rate's own publication date (YYYY-MM-DD)
    source: str

    def as_tuple(self) -> tuple[float, str, str]:
        return self.rate, self.date, self.source


def norm_ccy(code: str) -> str:
    code = code.strip().upper()
    return ALIASES.get(code, code)


def default_cache_path() -> Path:
    """data/fx/rates.json next to the active DB (HQ_DB_PATH is re-read so tests can redirect it)."""
    db_path = Path(os.environ.get("HQ_DB_PATH") or settings.DB_PATH)
    return db_path.parent / "fx" / "rates.json"


def is_offline() -> bool:
    return os.environ.get("HQ_OFFLINE") == "1"


class FxRates:
    """Rate provider. Construct with explicit paths in tests; `rate()` below uses a process-wide default."""

    def __init__(self, *, cache_path: Path | None = None, seed_path: Path | None = None,
                 offline: bool | None = None, client: httpx.Client | None = None, timeout: float = 8.0):
        self.cache_path = Path(cache_path) if cache_path else default_cache_path()
        self.seed_path = Path(seed_path) if seed_path else SEED_PATH
        self._offline = offline
        self._client = client
        self._timeout = timeout
        self._memo: dict[str, FxQuote] = {}
        self._unsupported: set[str] = set()
        self._network_down_until = 0.0
        self._seed: dict | None = None

    # ── public ──────────────────────────────────────────────────────
    @property
    def offline(self) -> bool:
        return is_offline() if self._offline is None else self._offline

    def rate(self, from_ccy: str, to_ccy: str = "INR") -> tuple[float, str, str]:
        """(rate, date, source) such that amount_in_to = amount_in_from * rate. Raises FxUnavailable."""
        return self.quote(from_ccy, to_ccy).as_tuple()

    def quote(self, from_ccy: str, to_ccy: str = "INR") -> FxQuote:
        src, dst = norm_ccy(from_ccy), norm_ccy(to_ccy)
        if src == dst:
            return FxQuote(1.0, today_ist().isoformat(), "identity")
        if self.offline:
            return self._seed_quote(src, dst)
        pair = f"{src}/{dst}"
        day = today_ist().isoformat()
        memo_key = f"{day}:{pair}"
        if memo_key in self._memo:
            return self._memo[memo_key]
        cached = self._read_cache().get("days", {}).get(day, {}).get(pair)
        if cached:
            quote = FxQuote(float(cached["rate"]), cached["date"], cached["source"])
            self._memo[memo_key] = quote
            return quote
        try:
            quote = self.fetch_live(src, dst)
        except FxUnavailable:
            return self._fallback(src, dst, pair)
        self._write_cache(day, pair, quote)
        self._memo[memo_key] = quote
        return quote

    def fetch_live(self, src: str, dst: str) -> FxQuote:
        """Frankfurter v1 (ECB) first, then v2. Raises FxUnavailable on any failure."""
        pair = f"{src}/{dst}"
        if pair in self._unsupported or time.monotonic() < self._network_down_until:
            raise FxUnavailable(pair)
        try:
            quote = self._fetch_v1(src, dst) or self._fetch_v2(src, dst)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            self._network_down_until = time.monotonic() + NETWORK_BACKOFF_S
            raise FxUnavailable(f"{pair}: {exc.__class__.__name__}") from exc
        if quote is None:
            self._unsupported.add(pair)
            raise FxUnavailable(f"{pair}: not published by Frankfurter v1 or v2")
        return quote

    def seed_rates(self) -> dict:
        return self._load_seed().get("rates", {})

    # ── live fetch ──────────────────────────────────────────────────
    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        headers = {"User-Agent": "agent-hq/0.1 (local, GET-only fx lookup)", "Accept": "application/json"}
        if self._client is not None:
            return self._client.get(f"{API_BASE}{path}", params=params, headers=headers, timeout=self._timeout)
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            return client.get(f"{API_BASE}{path}", params=params, headers=headers)

    def _fetch_v1(self, src: str, dst: str) -> FxQuote | None:
        resp = self._get("/v1/latest", {"base": src, "symbols": dst})
        if resp.status_code in (400, 404, 422):
            return None
        resp.raise_for_status()
        body = resp.json()
        value = body.get("rates", {}).get(dst)
        if value is None:
            return None
        return FxQuote(float(value), str(body["date"]), SOURCE_V1)

    def _fetch_v2(self, src: str, dst: str) -> FxQuote | None:
        resp = self._get(f"/v2/rate/{src}/{dst}")
        if resp.status_code in (400, 404, 422):
            return None
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, list):
            body = body[0] if body else {}
        if body.get("rate") is None:
            return None
        return FxQuote(float(body["rate"]), str(body["date"]), SOURCE_V2)

    # ── fallbacks ───────────────────────────────────────────────────
    def _fallback(self, src: str, dst: str, pair: str) -> FxQuote:
        days = self._read_cache().get("days", {})
        for day in sorted(days, reverse=True):
            entry = days[day].get(pair)
            if entry:
                return FxQuote(float(entry["rate"]), entry["date"], f"{entry['source']} (stale cache from {day})")
        return self._seed_quote(src, dst)

    def _load_seed(self) -> dict:
        if self._seed is None:
            try:
                self._seed = json.loads(self.seed_path.read_text())
            except (OSError, json.JSONDecodeError):
                self._seed = {}
        return self._seed

    def _seed_quote(self, src: str, dst: str) -> FxQuote:
        """Seed holds X->INR; other pairs are crossed through INR."""
        rates = self.seed_rates()

        def to_inr(code: str) -> tuple[float, str, str]:
            if code == "INR":
                return 1.0, "", ""
            entry = rates.get(code)
            if not entry:
                raise FxUnavailable(f"{src}/{dst}: no seed rate for {code}")
            return float(entry["rate"]), entry.get("date", ""), entry.get("source", "")

        src_rate, src_date, src_source = to_inr(src)
        dst_rate, dst_date, _ = to_inr(dst)
        date = min(d for d in (src_date, dst_date) if d) if (src_date or dst_date) else ""
        origin = src_source or "seed"
        return FxQuote(src_rate / dst_rate, date, f"seed ({origin})")

    # ── cache file ──────────────────────────────────────────────────
    def _read_cache(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_cache(self, day: str, pair: str, quote: FxQuote) -> None:
        data = self._read_cache()
        days = data.setdefault("days", {})
        days.setdefault(day, {})[pair] = {"rate": quote.rate, "date": quote.date, "source": quote.source,
                                          "fetched_at": now_iso()}
        for old in sorted(days)[:-CACHE_KEEP_DAYS]:
            days.pop(old, None)
        data["version"] = 1
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
            tmp.replace(self.cache_path)
        except OSError:
            pass  # the cache is an optimisation; a read-only disk must not break conversion


_default: FxRates | None = None


def default() -> FxRates:
    """Process-wide provider; rebuilt if HQ_DB_PATH now points somewhere else."""
    global _default
    if _default is None or _default.cache_path != default_cache_path():
        _default = FxRates()
    return _default


def rate(from_ccy: str, to_ccy: str = "INR") -> tuple[float, str, str]:
    return default().rate(from_ccy, to_ccy)


def write_seed(path: Path = SEED_PATH, currencies: tuple[str, ...] = SEED_CURRENCIES) -> dict:
    """Fetch live X->INR rates and write the committed fallback file. Currencies that fail keep their old entry."""
    fx = FxRates(offline=False, cache_path=default_cache_path())
    try:
        old = json.loads(path.read_text()).get("rates", {})
    except (OSError, json.JSONDecodeError):
        old = {}
    rates, failed = {}, []
    for code in currencies:
        try:
            quote = fx.fetch_live(code, "INR")
            rates[code] = {"rate": quote.rate, "date": quote.date, "source": quote.source}
        except FxUnavailable:
            fx._network_down_until = 0.0  # try every currency independently
            failed.append(code)
            if code in old:
                rates[code] = old[code]
    seed = {
        "seed": True,
        "quote": "INR",
        "note": ("Fallback FX rates (1 unit of currency = rate INR) used when Frankfurter is unreachable or "
                 "HQ_OFFLINE=1. Refresh: python -m hq.pipeline.verify.fx --write-seed"),
        "generated_at": now_iso(),
        "rates": rates,
    }
    if failed:
        seed["stale_entries"] = failed
    path.write_text(json.dumps(seed, indent=2) + "\n")
    return seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FX rates to INR via Frankfurter (GET only).")
    parser.add_argument("currencies", nargs="*", help="ISO codes to look up (default: seed list)")
    parser.add_argument("--to", default="INR")
    parser.add_argument("--write-seed", action="store_true", help="refresh config/fx_seed.json from live rates")
    args = parser.parse_args(argv)
    if args.write_seed:
        seed = write_seed()
        for code, entry in seed["rates"].items():
            print(f"{code:>4} -> INR {entry['rate']:>12.5f}  {entry['date']}  {entry['source']}")
        if seed.get("stale_entries"):
            print("kept old values for:", ", ".join(seed["stale_entries"]), file=sys.stderr)
        return 0
    for code in args.currencies or SEED_CURRENCIES:
        try:
            value, date, source = rate(code, args.to)
            print(f"{code:>4} -> {args.to} {value:>12.5f}  {date}  {source}")
        except FxUnavailable as exc:
            print(f"{code:>4} -> {args.to} unavailable ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
