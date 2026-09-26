"""Living-cost lookup (remote -> IN-home, unseeded cities) and the city coordinate table."""
from __future__ import annotations

import csv

import pytest

from hq.pipeline.verify.fx import FxUnavailable
from hq.pipeline.verify.living_cost import CITIES_CSV, LIVING_COSTS_CSV, LivingCosts, city_coords, normalize_city

REQUIRED_CITIES = ["Bengaluru", "Hyderabad", "Delhi", "Gurugram", "Noida", "Greater Noida", "Mumbai", "Pune", "Chennai",
                   "Kolkata", "Chiayi", "Taipei", "Tokyo", "Lausanne", "Zurich", "Berlin", "Munich", "Paris", "London",
                   "Singapore", "Toronto", "San Francisco", "New York", "Seattle", "Abu Dhabi", "Dubai", "Amsterdam",
                   "Warsaw", "Doha"]


class StubFx:
    def rate(self, from_ccy, to_ccy="INR"):
        rates = {"TWD": 3.0, "CHF": 115.0, "EUR": 109.0}
        if from_ccy not in rates:
            raise FxUnavailable(from_ccy)
        return rates[from_ccy], "2026-09-25", "stub"


@pytest.fixture
def living():
    return LivingCosts(fx=StubFx())


def test_csv_columns_and_provisional_rows():
    with LIVING_COSTS_CSV.open(newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert reader.fieldnames == ["key", "country_iso2", "city", "currency", "monthly_local", "basis", "confidence",
                                 "source_note", "as_of"]
    assert {r["city"] for r in rows} >= set(REQUIRED_CITIES)
    assert any(r["key"] == "IN-home" for r in rows)
    for row in rows:
        assert row["confidence"] == "provisional"
        assert "provisional estimate" in row["source_note"] and "phase (c)" in row["source_note"]
        assert float(row["monthly_local"]) > 0


def test_indian_city(living):
    value, basis, confidence = living.lookup("Bengaluru", "IN", "onsite")
    assert value == 22000 and confidence == "provisional" and "IN-bengaluru" in basis


@pytest.mark.parametrize(("alias", "canonical"), [("Bangalore", "Bengaluru"), ("Gurgaon", "Gurugram"),
                                                  ("New Delhi", "Delhi"), ("Zürich", "Zurich")])
def test_aliases(living, alias, canonical):
    assert living.lookup(alias, None, "hybrid")[0] == living.lookup(canonical, None, "onsite")[0]


def test_remote_uses_in_home_baseline(living):
    home = living.lookup(None, "IN", "remote")
    assert home[0] == 12000 and "IN-home" in home[1]
    assert living.lookup("Berlin", "DE", "remote") == home


def test_foreign_city_converted_via_fx(living):
    value, basis, _ = living.lookup("Chiayi", "TW", "onsite")
    assert value == 17000 * 3.0 and "TWD 17,000" in basis


def test_unseeded(living):
    assert living.lookup("Atlantis", "XX", "onsite") == (None, "unseeded", None)
    assert living.lookup(None, "IN", "onsite") == (None, "unseeded", None)
    assert living.lookup("Berlin", "US", "onsite") == (None, "unseeded", None)


def test_missing_fx_rate_is_reported(living):
    value, basis, confidence = living.lookup("Warsaw", "PL", "onsite")
    assert value is None and "no FX rate" in basis and confidence == "provisional"


def test_monthly_inr_column_is_supported(tmp_path):
    path = tmp_path / "lc.csv"
    path.write_text("key,country_iso2,city,monthly_inr,basis,confidence,source_note,as_of\n"
                    "IN-x,IN,Xcity,9000,b,provisional,provisional estimate,2026-09-26\n")
    assert LivingCosts(path, fx=StubFx()).lookup("Xcity", "IN", "onsite")[0] == 9000


def test_city_coords():
    with CITIES_CSV.open(newline="") as fh:
        names = {r["city"] for r in csv.DictReader(fh)}
    assert names >= set(REQUIRED_CITIES)
    assert city_coords("Chiayi", "TW") == pytest.approx((23.4801, 120.4491))
    assert city_coords("Minxiong", "TW") != city_coords("Chiayi", "TW")
    assert city_coords("Bangalore") == city_coords("Bengaluru", "IN")
    assert city_coords("Atlantis") is None and city_coords(None) is None


def test_normalize_city():
    assert normalize_city("  München ") == "munich"
    assert normalize_city("San Francisco Bay Area") == "san francisco"
