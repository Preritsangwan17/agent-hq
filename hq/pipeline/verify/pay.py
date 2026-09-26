"""Pay parsing and normalisation (CONTRACT section 5).

`parse_pay(raw)` turns a posting's pay text into amount/currency/period/status. `normalize(...)` converts it into
the `opportunities` pay columns: monthly local and INR figures, hourly INR, FX provenance, living cost and ratio.

Rules that matter:
- Never assume hours. Hourly (or daily) pay without stated hours is status "variable" and gets hourly INR only.
- Lump sums are spread over `duration_months` when known; otherwise status "variable" with no monthly figure.
- A stated amount with no period is "variable" too: we do not guess whether it is per month or per year.
- "Not listed", "Competitive", "Need-based", "(amount not verified)" and similar are "unknown".
- Fees ("registration fee Rs 499") are "fee_required"; "Unpaid"/"no stipend" are "unpaid".
- ratio = monthly_inr_min / living_cost_monthly_inr (None when either is unknown).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from hq.pipeline.verify.fx import FxUnavailable

WEEKS_PER_MONTH = 52 / 12
DAYS_PER_MONTH = 30.4375

PAY_COLUMNS = (
    "pay_raw", "pay_min", "pay_max", "pay_currency", "pay_period", "pay_status",
    "pay_monthly_local_min", "pay_monthly_local_max",
    "pay_monthly_inr_min", "pay_monthly_inr_mid", "pay_monthly_inr_max",
    "pay_hourly_inr_min", "pay_hourly_inr_max", "fx_rate", "fx_date", "benefits_json",
    "living_cost_monthly_inr", "living_cost_basis", "living_cost_confidence", "pay_ratio",
)

COUNTRY_CURRENCY = {
    "IN": "INR", "US": "USD", "GB": "GBP", "CH": "CHF", "TW": "TWD", "JP": "JPY", "SG": "SGD", "CA": "CAD",
    "AE": "AED", "AU": "AUD", "PL": "PLN", "QA": "QAR", "SA": "SAR", "KR": "KRW", "HK": "HKD", "CN": "CNY",
    "NZ": "NZD", "SE": "SEK", "NO": "NOK", "DK": "DKK", "IL": "ILS", "MY": "MYR", "TH": "THB", "CZ": "CZK",
    "HU": "HUF", "BR": "BRL", "MX": "MXN", "ZA": "ZAR", "ID": "IDR",
    **{c: "EUR" for c in ("DE", "FR", "NL", "IT", "ES", "IE", "AT", "BE", "FI", "PT", "LU", "GR", "EE", "LV", "LT",
                          "SK", "SI", "MT", "CY", "HR")},
}


@dataclass(frozen=True)
class ParsedPay:
    raw: str | None
    status: str                      # listed|unknown|variable|unpaid|fee_required
    min: float | None = None
    max: float | None = None
    currency: str | None = None      # ISO 4217
    period: str | None = None        # hour|day|week|month|year|lump|unknown
    hours_per_week: float | None = None
    duration_months: float | None = None
    fee_amount: float | None = None
    fee_currency: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def monthly_factor(self) -> float | None:
        return monthly_factor(self.period, self.hours_per_week, self.duration_months)

    @property
    def monthly_local_min(self) -> float | None:
        factor = self.monthly_factor
        return None if factor is None or self.min is None else self.min * factor

    @property
    def monthly_local_max(self) -> float | None:
        factor = self.monthly_factor
        return None if factor is None or self.max is None else self.max * factor


def monthly_factor(period: str | None, hours_per_week: float | None = None,
                   duration_months: float | None = None) -> float | None:
    """Multiplier from one `period` unit to one month, or None when it cannot be known without assuming."""
    if period == "month":
        return 1.0
    if period == "year":
        return 1 / 12
    if period == "week":
        return WEEKS_PER_MONTH
    if period == "hour" and hours_per_week:
        return hours_per_week * WEEKS_PER_MONTH
    if period == "lump" and duration_months:
        return 1 / duration_months
    return None


# ── lexicon ───────────────────────────────────────────────────────────
# Alternation order matters: prefixed dollars before the bare "$", "CN¥" before "¥".
_CURRENCY_TOKENS: list[tuple[str, str]] = [
    (r"US\s?\$", "USD"), (r"NT\s?\$", "TWD"), (r"HK\s?\$", "HKD"), (r"(?:CA|CAD|C)\s?\$", "CAD"),
    (r"(?:AU|AUD|A)\s?\$", "AUD"), (r"(?:SG|SGD|S)\s?\$", "SGD"), (r"NZ\s?\$", "NZD"), (r"(?:CN|RMB)\s?¥", "CNY"),
    (r"₹", "INR"), (r"€", "EUR"), (r"£", "GBP"), (r"[¥￥]", "JPY"), (r"₩", "KRW"), (r"zł", "PLN"), (r"\$", "USD"),
]
_ISO_CODES = ("INR USD EUR GBP CHF TWD NTD JPY SGD CAD AED AUD PLN QAR SAR KRW HKD CNY RMB NZD SEK NOK DKK MYR THB "
              "IDR ZAR BRL MXN ILS CZK HUF").split()
_CODE_ALIASES = {"NTD": "TWD", "RMB": "CNY"}
_CURRENCY_WORDS: list[tuple[str, str]] = [
    (r"rs\.?|rupees?|inr", "INR"), (r"usd|dollars?", "USD"), (r"eur|euros?", "EUR"), (r"pounds?\s+sterling|gbp", "GBP"),
    (r"yen", "JPY"), (r"swiss\s+francs?|francs?", "CHF"), (r"yuan|renminbi", "CNY"), (r"dirhams?|dhs?", "AED"),
    (r"zloty|złoty", "PLN"),
]
_CURRENCY_RE = re.compile(
    "|".join(f"(?P<t{i}>{p})" for i, (p, _) in enumerate(_CURRENCY_TOKENS))
    + "|(?<![A-Za-z])(?P<iso>" + "|".join(_ISO_CODES) + r")(?![A-Za-z])"
    + "|" + "|".join(f"(?<![A-Za-z])(?P<w{i}>(?i:{p}))(?![A-Za-z])" for i, (p, _) in enumerate(_CURRENCY_WORDS))
)

_NUMBER_RE = re.compile(
    r"(?<!\d)(?<!\d[.,:])(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?(?![\d.])|\d{1,3}(?:,\d{2,3})+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<suf>lpa|lakhs?|lacs?|l|crores?|cr|thousand|k|million|mn|m)(?![A-Za-z]))?",
    re.IGNORECASE,
)
_SUFFIX_MULT = {"lpa": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5, "crore": 1e7,
                "crores": 1e7, "cr": 1e7, "thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6}
_NOT_AMOUNT_AFTER = re.compile(
    r"^\s*(?:\+\s*)?(?:hours?|hrs?|h|weeks?|wks?|months?|mos?|days?|years?|yrs?|%|percent|am|pm|st|nd|rd|th|"
    r"x\b|people|students|positions|seats|slots)(?![A-Za-z])|^\s*:\d",
    re.IGNORECASE,
)
_RANGE_JOIN = re.compile(r"^(?:-|–|—|to|~|-to-)$", re.IGNORECASE)

_PERIODS: list[tuple[str, re.Pattern[str]]] = [(name, re.compile(p, re.IGNORECASE)) for name, p in [
    ("hour", r"/\s*(?:hour|hr|h)\b|\bper\s+hour\b|\ban\s+hour\b|\bhourly\b|\bp/h\b"),
    ("day", r"/\s*day\b|\bper\s+day\b|\ba\s+day\b|\bdaily\b|\bper\s+diem\b"),
    ("week", r"/\s*(?:week|wk)\b|\bper\s+week\b|\ba\s+week\b|\bweekly\b"),
    ("month", r"/\s*(?:month|mo|mon|m|pm)\b|\bper\s+(?:month|mensem)\b|\ba\s+month\b|\bmonthly\b|\bp\.m\.|\bpcm\b"),
    ("year", r"/\s*(?:year|yr|annum|y)\b|\bper\s+(?:year|annum)\b|\ba\s+year\b|\bannual(?:ly)?\b|\byearly\b"
             r"|\bp\.a\.|\blpa\b|\bctc\b"),
    ("lump", r"\bone[-\s]?time\b|\blump[-\s]?sum\b|\bin\s+total\b|\btotal\b|\bflat\b"
             r"|\bfor\s+the\s+(?:entire|whole|full)\b|\bper\s+(?:programme|program|internship|project|task)\b"),
]]
_HOURS_RE = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)\s*(?:-|–|to)?\s*(?P<hi>\d+(?:\.\d+)?)?\s*(?:hours?|hrs?|h)\s*(?:/|per|a|each)\s*"
    r"(?:week|wk)\b", re.IGNORECASE)
_DURATION_RE = re.compile(r"\bfor\s+(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>months?|weeks?)\b", re.IGNORECASE)
_UNPAID_RE = re.compile(
    r"\bunpaid\b|\bno\s+(?:stipend|pay|salary|compensation|remuneration)\b|\bwithout\s+(?:stipend|pay)\b"
    r"|\bnot\s+paid\b|\bzero\s+stipend\b|\bvolunteer(?:ing)?\b", re.IGNORECASE)
_FEE_RE = re.compile(
    r"\b(?:registration|application|training|joining|enrol?l?ment|onboarding|processing|security|certificate|"
    r"certification|course|program(?:me)?|kit|refundable|admission)\s+(?:fee|fees|charges?|deposit)\b"
    r"|\bfees?\s*(?:of\s*)?(?:rs\.?|inr|₹|\$|usd|€)|\bdeposit\b|\bpay\s+(?:a\s+)?fee\b"
    r"|\bpay\s+(?:rs\.?|inr|₹|\$|usd|€)\s*[\d,.]+\s*(?:to|for)\s+(?:register|apply|confirm|join|enrol|enroll|book"
    r"|secure|reserve|the\s+(?:training|course|kit|certificate))",
    re.IGNORECASE)
_FEE_NEGATION_RE = re.compile(
    r"\bno\s+(?:\w+\s+){0,2}(?:fees?|charges?|deposit)\b|\bfees?\s+(?:waived|waiver)\b|\bfree\s+of\s+(?:cost|charge)\b"
    r"|\bwithout\s+any\s+(?:fees?|charges?)\b|\bnever\s+(?:ask|charge)", re.IGNORECASE)
_UPTO_RE = re.compile(r"(?:\bup\s*to|\bupto|\bmax(?:imum)?\.?|\bnot\s+more\s+than|\bat\s+most)\s*[:\-]?\s*\S{0,6}\s*$",
                      re.IGNORECASE)
_ATLEAST_BEFORE_RE = re.compile(r"(?:\bfrom|\bstarting(?:\s+(?:at|from))?|\bat\s+least|\bmin(?:imum)?\.?)\s*[:\-]?\s*"
                                r"\S{0,6}\s*$", re.IGNORECASE)
_ATLEAST_AFTER_RE = re.compile(r"^\s*\+|\bminimum\b|\bmin\.|\bat\s+least\b|\bonwards\b|\band\s+above\b",
                               re.IGNORECASE)


@dataclass
class _Num:
    value: float
    raw_value: float
    suffix: str | None
    start: int
    end: int
    has_currency: bool = False   # a currency mark sits right before or after it (whitespace only between)


def _touches_currency(text: str, start: int, end: int, marks: list[tuple[int, int, str]]) -> bool:
    for s, e, _ in marks:
        if e <= start and start - e <= 2 and not text[e:start].strip():
            return True
        if s >= end and s - end <= 2 and not text[end:s].strip():
            return True
    return False


def _to_float(num: str) -> float:
    """'25,000' / '1,00,000' / '13.25' -> float; European '1.650' or '1.650,50' -> 1650 / 1650.5."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", num):
        return float(num.replace(".", "").replace(",", "."))
    return float(num.replace(",", ""))


def _currency_marks(text: str) -> list[tuple[int, int, str]]:
    marks = []
    for m in _CURRENCY_RE.finditer(text):
        group = m.lastgroup or ""
        if group == "iso":
            code = _CODE_ALIASES.get(m.group("iso"), m.group("iso"))
        elif group.startswith("t"):
            code = _CURRENCY_TOKENS[int(group[1:])][1]
        else:
            code = _CURRENCY_WORDS[int(group[1:])][1]
        marks.append((m.start(), m.end(), code))
    return marks


def _numbers(text: str, marks: list[tuple[int, int, str]]) -> list[_Num]:
    out = []
    for m in _NUMBER_RE.finditer(text):
        raw_value = _to_float(m.group("num"))
        suffix = (m.group("suf") or "").lower() or None
        end = m.end()
        if m.group("suf") == "m":  # lower-case "m" is too ambiguous; only "M", "mn" and "million" mean million
            suffix, end = None, m.end("num")
        after = text[end:]
        adjacent_ccy = _touches_currency(text, m.start(), end, marks)
        if suffix is None and not adjacent_ccy and _NOT_AMOUNT_AFTER.match(after):
            continue
        if (suffix is None and not adjacent_ccy and re.fullmatch(r"(?:19|20)\d\d", m.group("num"))
                and not re.match(r"\s*(?:/|per\b)", after, re.IGNORECASE)):
            continue  # a year such as "Summer 2027"
        value = raw_value * _SUFFIX_MULT.get(suffix or "", 1.0)
        out.append(_Num(value, raw_value, suffix, m.start(), end, adjacent_ccy))
    return out


def _is_range_join(between: str) -> bool:
    stripped = _CURRENCY_RE.sub("", between).replace(" ", "")
    return bool(_RANGE_JOIN.match(stripped))


def _pick_currency(marks: list[tuple[int, int, str]], start: int, end: int) -> str | None:
    if not marks:
        return None
    def distance(mark: tuple[int, int, str]) -> int:
        s, e, _ = mark
        return max(0, start - e) if e <= start else max(0, s - end)
    return min(marks, key=distance)[2]


def _find_period(text: str, amount_end: int, amount_start: int) -> str | None:
    after_hits, before_hits = [], []
    for name, pattern in _PERIODS:
        for m in pattern.finditer(text):
            if m.start() >= amount_end - 1:
                after_hits.append((m.start(), name))
            elif m.end() <= amount_start + 1:
                before_hits.append((m.start(), name))
    if after_hits:
        return min(after_hits)[1]
    if before_hits:
        return max(before_hits)[1]
    return None


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for s, e in spans:
        chars[s:e] = " " * (e - s)
    return "".join(chars)


def parse_pay(raw: str | None, *, hours_per_week: float | None = None,
              duration_months: float | None = None) -> ParsedPay:
    """Parse a pay string. Explicit hours/duration arguments win over values stated in the text."""
    text = (raw or "").strip()
    if not text:
        return ParsedPay(raw=raw, status="unknown", notes=("no pay text",))
    notes: list[str] = []

    # Hours per week and "for N months" are context, not pay; read them and blank them out.
    spans = []
    hours_match = _HOURS_RE.search(text)
    if hours_match:
        spans.append(hours_match.span())
        if hours_per_week is None:
            hours_per_week = float(hours_match.group("lo"))
            notes.append("hours per week taken from the pay text"
                         + (" (lower bound of a range)" if hours_match.group("hi") else ""))
    duration_match = _DURATION_RE.search(text)
    if duration_match:
        spans.append(duration_match.span())
        if duration_months is None:
            n = float(duration_match.group("n"))
            duration_months = n if duration_match.group("unit").lower().startswith("month") else n * 7 / DAYS_PER_MONTH
    work = _mask(text, spans)
    marks = _currency_marks(work)

    if _FEE_RE.search(work) and not _FEE_NEGATION_RE.search(work):
        nums = _numbers(work, marks)
        fee = nums[0] if nums else None
        return ParsedPay(raw=raw, status="fee_required", fee_amount=fee.value if fee else None,
                         fee_currency=_pick_currency(marks, fee.start, fee.end) if fee else None,
                         hours_per_week=hours_per_week, duration_months=duration_months,
                         notes=tuple(notes + ["candidate is asked to pay"]))
    if _UNPAID_RE.search(work):
        return ParsedPay(raw=raw, status="unpaid", hours_per_week=hours_per_week, duration_months=duration_months,
                         notes=tuple(notes))

    nums = _numbers(work, marks)
    if not nums:
        return ParsedPay(raw=raw, status="unknown", hours_per_week=hours_per_week, duration_months=duration_months,
                         notes=tuple(notes + ["no amount stated"]))

    # The pay amount is the first number carrying a currency mark, else simply the first number.
    idx = next((i for i, n in enumerate(nums) if n.has_currency), 0)
    first = nums[idx]
    second = None
    if idx + 1 < len(nums) and _is_range_join(work[first.end:nums[idx + 1].start]):
        second = nums[idx + 1]
        if first.suffix is None and second.suffix and first.raw_value < second.raw_value:
            first = _Num(first.raw_value * _SUFFIX_MULT[second.suffix], first.raw_value, second.suffix,
                         first.start, first.end, first.has_currency)
    end = second.end if second else first.end
    lo, hi = first.value, (second.value if second else first.value)
    if lo > hi:
        lo, hi = hi, lo
    before, after = work[:first.start], work[end:]
    if second is None:
        if _UPTO_RE.search(before):
            lo = None
            notes.append("upper bound only")
        elif _ATLEAST_BEFORE_RE.search(before) or _ATLEAST_AFTER_RE.search(after[:40]):
            hi = None
            notes.append("lower bound only")

    currency = _pick_currency(marks, first.start, end)
    suffixes = {first.suffix, second.suffix if second else None}
    if currency is None and suffixes & {"lpa", "lakh", "lakhs", "lac", "lacs", "l", "crore", "crores", "cr"}:
        currency = "INR"
        notes.append("currency inferred from lakh/crore notation")

    period = "year" if "lpa" in suffixes else _find_period(work, end, first.start)
    if period is None and duration_match and 0 <= duration_match.start() - end <= 3:
        period = "lump"  # "Rs 60,000 for 6 months" is a total for the stated duration
    period = period or "unknown"
    if period == "unknown":
        notes.append("pay period not stated")

    factor = monthly_factor(period, hours_per_week, duration_months)
    status = "listed" if factor is not None else "variable"
    if period == "hour" and not hours_per_week:
        notes.append("hourly with unknown hours: no monthly figure")
    if period == "lump" and not duration_months:
        notes.append("lump sum with unknown duration: no monthly figure")
    return ParsedPay(raw=raw, status=status, min=lo, max=hi, currency=currency, period=period,
                     hours_per_week=hours_per_week, duration_months=duration_months, notes=tuple(notes))


# ── normalisation ─────────────────────────────────────────────────────
FxLike = Any          # object with .rate(from, to) -> (rate, date, source), or such a callable
LivingCostLike = Any  # object with .lookup(city, country_iso2, work_mode) -> (inr|None, basis, confidence), or callable


def _call_fx(fx: FxLike, currency: str) -> tuple[float, str, str] | None:
    if fx is None:
        return None
    fn: Callable[..., tuple[float, str, str]] = fx.rate if hasattr(fx, "rate") else fx
    try:
        return fn(currency, "INR")
    except FxUnavailable:
        return None


def _call_living(living_cost: LivingCostLike, city: str | None, country_iso2: str | None,
                 work_mode: str | None) -> tuple[float | None, str | None, str | None]:
    if living_cost is None:
        return None, None, None
    fn = living_cost.lookup if hasattr(living_cost, "lookup") else living_cost
    return fn(city, country_iso2, work_mode)


def _round_inr(value: float | None) -> float | None:
    return None if value is None else float(round(value))


def normalize(parsed: ParsedPay, fx: FxLike, living_cost: LivingCostLike, *, city: str | None = None,
              country_iso2: str | None = None, work_mode: str | None = None,
              benefits: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return every `opportunities` pay column (PAY_COLUMNS) for this parse."""
    out: dict[str, Any] = dict.fromkeys(PAY_COLUMNS)
    out.update(pay_raw=parsed.raw, pay_min=parsed.min, pay_max=parsed.max, pay_currency=parsed.currency,
               pay_period=parsed.period, pay_status=parsed.status,
               benefits_json=json.dumps(dict(benefits or {}), ensure_ascii=False, separators=(",", ":")))

    has_amount = parsed.min is not None or parsed.max is not None
    currency = parsed.currency
    if has_amount and currency is None and country_iso2:
        currency = COUNTRY_CURRENCY.get(country_iso2.upper())
        out["pay_currency"] = currency

    local_min, local_max = parsed.monthly_local_min, parsed.monthly_local_max
    out["pay_monthly_local_min"] = None if local_min is None else round(local_min, 2)
    out["pay_monthly_local_max"] = None if local_max is None else round(local_max, 2)

    if not (has_amount and currency):
        quote = None
    elif currency == "INR":
        quote = (1.0, None, "identity")  # no conversion, so no FX date
    else:
        quote = _call_fx(fx, currency)
    if quote:
        rate, date, _source = quote
        out["fx_rate"], out["fx_date"] = rate, date
        inr_min = _round_inr(local_min * rate) if local_min is not None else None
        inr_max = _round_inr(local_max * rate) if local_max is not None else None
        out["pay_monthly_inr_min"], out["pay_monthly_inr_max"] = inr_min, inr_max
        known = [v for v in (inr_min, inr_max) if v is not None]
        out["pay_monthly_inr_mid"] = _round_inr(sum(known) / len(known)) if known else None
        if parsed.period == "hour":
            out["pay_hourly_inr_min"] = None if parsed.min is None else round(parsed.min * rate, 2)
            out["pay_hourly_inr_max"] = None if parsed.max is None else round(parsed.max * rate, 2)

    lc_inr, lc_basis, lc_conf = _call_living(living_cost, city, country_iso2, work_mode)
    out["living_cost_monthly_inr"] = lc_inr
    out["living_cost_basis"] = lc_basis
    out["living_cost_confidence"] = lc_conf
    if out["pay_monthly_inr_min"] is not None and lc_inr:
        out["pay_ratio"] = round(out["pay_monthly_inr_min"] / lc_inr, 3)
    return out


def pay_json(row: Mapping[str, Any]) -> dict[str, Any]:
    """The CONTRACT `Pay` object from an opportunities row (dict or sqlite3.Row)."""
    benefits = row["benefits_json"]
    if isinstance(benefits, str):
        try:
            benefits = json.loads(benefits)
        except json.JSONDecodeError:
            benefits = {}
    return {
        "raw": row["pay_raw"], "status": row["pay_status"], "min": row["pay_min"], "max": row["pay_max"],
        "currency": row["pay_currency"], "period": row["pay_period"],
        "monthly_inr_min": row["pay_monthly_inr_min"], "monthly_inr_mid": row["pay_monthly_inr_mid"],
        "monthly_inr_max": row["pay_monthly_inr_max"], "hourly_inr_min": row["pay_hourly_inr_min"],
        "hourly_inr_max": row["pay_hourly_inr_max"], "fx_rate": row["fx_rate"], "fx_date": row["fx_date"],
        "living_cost_monthly_inr": row["living_cost_monthly_inr"], "living_cost_basis": row["living_cost_basis"],
        "living_cost_confidence": row["living_cost_confidence"], "ratio": row["pay_ratio"],
        "benefits": benefits or {},
    }
