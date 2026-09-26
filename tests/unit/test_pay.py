"""Pay parsing (table-driven) and normalisation into the opportunities pay columns."""
from __future__ import annotations

import json

import pytest

from hq.pipeline.verify.fx import FxUnavailable
from hq.pipeline.verify.pay import PAY_COLUMNS, ParsedPay, monthly_factor, normalize, parse_pay, pay_json

# raw, status, min, max, currency, period
PARSE_CASES = [
    ("INR 25,000/month", "listed", 25000, 25000, "INR", "month"),
    ("INR 25,000 - 40,000/month", "listed", 25000, 40000, "INR", "month"),
    ("₹ 25,000 - 40,000 /month", "listed", 25000, 40000, "INR", "month"),
    ("₹25,000 - ₹40,000/month", "listed", 25000, 40000, "INR", "month"),
    ("INR 15,000/month", "listed", 15000, 15000, "INR", "month"),
    ("Rs. 10k/month", "listed", 10000, 10000, "INR", "month"),
    ("₹4.2 LPA", "listed", 420000, 420000, "INR", "year"),
    ("INR 8 LPA", "listed", 800000, 800000, "INR", "year"),
    ("₹6-8 LPA", "listed", 600000, 800000, "INR", "year"),
    ("₹1,00,000 per annum", "listed", 100000, 100000, "INR", "year"),
    ("CTC ₹6,00,000", "listed", 600000, 600000, "INR", "year"),
    ("USD 13.25 - 27.50/hour (per Outlier's posting)", "variable", 13.25, 27.5, "USD", "hour"),
    ("$45/hr", "variable", 45, 45, "USD", "hour"),
    ("$15-20/hr", "variable", 15, 20, "USD", "hour"),
    ("€1,200/month", "listed", 1200, 1200, "EUR", "month"),
    ("EUR 1.200/month", "listed", 1200, 1200, "EUR", "month"),
    ("CHF 1,650 per month", "listed", 1650, 1650, "CHF", "month"),
    ("NT$15,000-30,000/month", "listed", 15000, 30000, "TWD", "month"),
    ("NT$15,000/month (TEEP minimum)", "listed", 15000, None, "TWD", "month"),
    ("NTD 15,000", "variable", 15000, 15000, "TWD", "unknown"),
    ("¥140,000 one-time allowance", "variable", 140000, 140000, "JPY", "lump"),
    ("$120k-150k/year", "listed", 120000, 150000, "USD", "year"),
    ("US$3,000 monthly", "listed", 3000, 3000, "USD", "month"),
    ("S$1,800/month", "listed", 1800, 1800, "SGD", "month"),
    ("HK$12,000/mo", "listed", 12000, 12000, "HKD", "month"),
    ("£2,500 per month", "listed", 2500, 2500, "GBP", "month"),
    ("AED 5,000/month", "listed", 5000, 5000, "AED", "month"),
    ("1.2M JPY per year", "listed", 1_200_000, 1_200_000, "JPY", "year"),
    ("₹10,000 per week", "listed", 10000, 10000, "INR", "week"),
    ("₹500 per day", "variable", 500, 500, "INR", "day"),
    ("Up to ₹30,000/month", "listed", None, 30000, "INR", "month"),
    ("₹10,000+ per month", "listed", 10000, None, "INR", "month"),
    ("Summer 2027, ₹8,000/month", "listed", 8000, 8000, "INR", "month"),
    ("20 interns, ₹10,000/month", "listed", 10000, 10000, "INR", "month"),
    ("Stipend: 15-30k/month", "listed", 15000, 30000, None, "month"),
    ("No registration fee; ₹12,000/month", "listed", 12000, 12000, "INR", "month"),
    ("Pay ₹15,000 per month", "listed", 15000, 15000, "INR", "month"),
    ("Pay: $20/hour", "variable", 20, 20, "USD", "hour"),
    ("Unpaid", "unpaid", None, None, None, None),
    ("No stipend", "unpaid", None, None, None, None),
    ("Not listed", "unknown", None, None, None, None),
    ("Need-based stipend, amount set by track and country", "unknown", None, None, None, None),
    ("Fellowship (amount not verified)", "unknown", None, None, None, None),
    ("Not verified", "unknown", None, None, None, None),
    ("Competitive", "unknown", None, None, None, None),
    ("", "unknown", None, None, None, None),
    (None, "unknown", None, None, None, None),
]


@pytest.mark.parametrize(("raw", "status", "lo", "hi", "currency", "period"), PARSE_CASES,
                         ids=[repr(c[0])[:40] for c in PARSE_CASES])
def test_parse_pay_table(raw, status, lo, hi, currency, period):
    parsed = parse_pay(raw)
    assert parsed.status == status
    assert parsed.min == (None if lo is None else pytest.approx(lo))
    assert parsed.max == (None if hi is None else pytest.approx(hi))
    assert parsed.currency == currency
    assert parsed.period == period


def test_table_has_at_least_30_cases():
    assert len(PARSE_CASES) >= 30


@pytest.mark.parametrize(("raw", "amount", "currency"), [
    ("registration fee ₹499", 499, "INR"),
    ("Pay ₹999 to confirm your seat", 999, "INR"),
    ("Refundable security deposit of Rs 2,000; stipend Rs 5,000/month", 2000, "INR"),
    ("Unpaid; training fee $50", 50, "USD"),
])
def test_fee_required(raw, amount, currency):
    parsed = parse_pay(raw)
    assert parsed.status == "fee_required"
    assert parsed.fee_amount == amount
    assert parsed.fee_currency == currency
    assert parsed.min is None and parsed.max is None


def test_hours_from_arguments_make_hourly_listed():
    parsed = parse_pay("$45/hr", hours_per_week=10)
    assert parsed.status == "listed"
    assert parsed.monthly_local_min == pytest.approx(45 * 10 * 52 / 12)


def test_hours_stated_in_text_are_used_but_never_assumed():
    parsed = parse_pay("$20/hour, 10 hours/week")
    assert parsed.status == "listed" and parsed.hours_per_week == 10
    assert parse_pay("$20/hour").hours_per_week is None
    assert parse_pay("$20/hour").monthly_local_min is None


def test_hours_in_text_do_not_hijack_the_monthly_period():
    parsed = parse_pay("INR 25,000/month, 20 hours/week")
    assert (parsed.period, parsed.min, parsed.hours_per_week) == ("month", 25000, 20)


def test_lump_sum_divides_by_duration():
    assert parse_pay("¥140,000 one-time allowance").monthly_local_min is None
    parsed = parse_pay("¥140,000 one-time allowance", duration_months=2)
    assert parsed.status == "listed"
    assert parsed.monthly_local_min == pytest.approx(70000)
    stated = parse_pay("₹60,000 for 6 months")
    assert (stated.period, stated.duration_months, stated.monthly_local_min) == ("lump", 6, pytest.approx(10000))


def test_monthly_factor():
    assert monthly_factor("month") == 1
    assert monthly_factor("year") == pytest.approx(1 / 12)
    assert monthly_factor("week") == pytest.approx(52 / 12)
    assert monthly_factor("hour") is None
    assert monthly_factor("hour", hours_per_week=40) == pytest.approx(40 * 52 / 12)
    assert monthly_factor("day") is None
    assert monthly_factor("lump") is None
    assert monthly_factor("unknown") is None


# ── normalize ────────────────────────────────────────────────────────
class StubFx:
    RATES = {"USD": 95.82, "TWD": 3.0144, "JPY": 0.608, "CHF": 115.68}

    def rate(self, from_ccy, to_ccy="INR"):
        if from_ccy not in self.RATES:
            raise FxUnavailable(from_ccy)
        return self.RATES[from_ccy], "2026-09-25", "stub"


class StubLiving:
    def lookup(self, city, country_iso2=None, work_mode=None):
        if work_mode == "remote":
            return 12000.0, "IN-home", "provisional"
        return {"Chiayi": (51245.0, "TW-chiayi", "provisional")}.get(city, (None, "unseeded", None))


def norm(raw, **kwargs):
    ctx = {k: kwargs.pop(k) for k in ("city", "country_iso2", "work_mode", "benefits") if k in kwargs}
    return normalize(parse_pay(raw, **kwargs), StubFx(), StubLiving(), **ctx)


def test_normalize_returns_every_pay_column():
    out = norm("INR 25,000/month", work_mode="remote", country_iso2="IN")
    assert set(out) == set(PAY_COLUMNS)


def test_normalize_inr_monthly_with_ratio():
    out = norm("INR 25,000 - 40,000/month", work_mode="remote", country_iso2="IN")
    assert (out["pay_monthly_inr_min"], out["pay_monthly_inr_mid"], out["pay_monthly_inr_max"]) == (25000, 32500, 40000)
    assert out["fx_rate"] == 1.0 and out["fx_date"] is None
    assert out["living_cost_monthly_inr"] == 12000 and out["living_cost_confidence"] == "provisional"
    assert out["pay_ratio"] == pytest.approx(25000 / 12000, abs=1e-3)


def test_normalize_hourly_unknown_hours_is_variable_hourly_only():
    out = norm("USD 13.25 - 27.50/hour (per Outlier's posting)", work_mode="remote", country_iso2="IN")
    assert out["pay_status"] == "variable"
    assert out["pay_monthly_inr_min"] is None and out["pay_monthly_inr_max"] is None
    assert out["pay_monthly_local_min"] is None
    assert out["pay_hourly_inr_min"] == pytest.approx(13.25 * 95.82, abs=0.01)
    assert out["pay_hourly_inr_max"] == pytest.approx(27.5 * 95.82, abs=0.01)
    assert out["pay_ratio"] is None


def test_normalize_hourly_with_known_hours_sets_monthly_and_hourly():
    out = norm("$20/hr", hours_per_week=10, work_mode="remote", country_iso2="IN")
    assert out["pay_status"] == "listed"
    assert out["pay_monthly_inr_min"] == round(20 * 10 * 52 / 12 * 95.82)
    assert out["pay_hourly_inr_min"] == pytest.approx(20 * 95.82, abs=0.01)


def test_normalize_twd_min_only():
    out = norm("NT$15,000/month (TEEP minimum)", city="Chiayi", country_iso2="TW", work_mode="onsite")
    assert out["pay_monthly_inr_min"] == round(15000 * 3.0144)
    assert out["pay_monthly_inr_max"] is None
    assert out["pay_monthly_inr_mid"] == out["pay_monthly_inr_min"]
    assert out["pay_ratio"] == pytest.approx(round(15000 * 3.0144) / 51245, abs=1e-3)


def test_normalize_year_and_lump():
    assert norm("$120k-150k/year", work_mode="remote")["pay_monthly_inr_min"] == round(10000 * 95.82)
    lump = norm("¥140,000 one-time allowance", duration_months=2, city="Tokyo", country_iso2="JP")
    assert lump["pay_monthly_inr_min"] == round(70000 * 0.608)
    assert lump["living_cost_basis"] == "unseeded" and lump["pay_ratio"] is None


def test_normalize_infers_currency_from_country():
    out = norm("Stipend: 15-30k/month", country_iso2="IN", work_mode="remote")
    assert out["pay_currency"] == "INR" and out["pay_monthly_inr_min"] == 15000


def test_normalize_unavailable_fx_keeps_local_figures():
    out = norm("PLN 4,000/month", city="Warsaw", country_iso2="PL", work_mode="onsite")
    assert out["pay_monthly_local_min"] == 4000
    assert out["pay_monthly_inr_min"] is None and out["fx_rate"] is None


@pytest.mark.parametrize("raw", ["Unpaid", "Not listed", "registration fee ₹499"])
def test_normalize_non_listed_has_no_money(raw):
    out = norm(raw, work_mode="remote", country_iso2="IN")
    assert out["pay_monthly_inr_min"] is None and out["pay_ratio"] is None
    assert out["living_cost_monthly_inr"] == 12000


def test_normalize_benefits_and_pay_json_shape():
    benefits = {"housing": True, "meals": True, "travel": True, "allowance_inr": 8000}
    out = norm("Fellowship (amount not verified)", work_mode="onsite", benefits=benefits)
    assert json.loads(out["benefits_json"]) == benefits
    shaped = pay_json(out)
    assert set(shaped) == {"raw", "status", "min", "max", "currency", "period", "monthly_inr_min", "monthly_inr_mid",
                           "monthly_inr_max", "hourly_inr_min", "hourly_inr_max", "fx_rate", "fx_date",
                           "living_cost_monthly_inr", "living_cost_basis", "living_cost_confidence", "ratio",
                           "benefits"}
    assert shaped["benefits"] == benefits and shaped["status"] == "unknown"


def test_normalize_accepts_plain_callables():
    parsed = ParsedPay(raw="USD 1,000/month", status="listed", min=1000, max=1000, currency="USD", period="month")
    out = normalize(parsed, lambda f, t: (90.0, "2026-01-01", "x"), lambda c, k, w: (45000.0, "b", "provisional"))
    assert out["pay_monthly_inr_min"] == 90000 and out["pay_ratio"] == 2.0
