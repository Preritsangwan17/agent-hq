"""FX provider: seed fallback, offline mode, v1 -> v2 fallback, day cache (all network mocked with respx)."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from hq.pipeline.verify import fx as fx_mod
from hq.pipeline.verify.fx import SEED_CURRENCIES, SEED_PATH, FxRates, FxUnavailable

HOST = "api.frankfurter.dev"


@pytest.fixture
def seed(tmp_path):
    path = tmp_path / "fx_seed.json"
    path.write_text(json.dumps({"seed": True, "quote": "INR", "rates": {
        "USD": {"rate": 95.0, "date": "2026-09-20", "source": "frankfurter v1 (ECB reference rate)"},
        "TWD": {"rate": 3.0, "date": "2026-09-21", "source": "frankfurter v2"},
    }}))
    return path


@pytest.fixture
def make(tmp_path, seed):
    def _make(**kwargs):
        kwargs.setdefault("cache_path", tmp_path / "fx" / "rates.json")
        kwargs.setdefault("seed_path", seed)
        return FxRates(**kwargs)
    return _make


def v1_ok(rate, date="2026-09-25"):
    def handler(request):
        base, symbol = request.url.params["base"], request.url.params["symbols"]
        return httpx.Response(200, json={"amount": 1.0, "base": base, "date": date, "rates": {symbol: rate}})
    return handler


def test_identity(make):
    assert make(offline=True).rate("INR", "INR")[0] == 1.0


def test_offline_uses_seed_only(make):
    with respx.mock(assert_all_called=False) as router:
        route = router.route(host=HOST)
        rate, date, source = make(offline=True).rate("USD")
        assert not route.called
    assert (rate, date) == (95.0, "2026-09-20")
    assert source.startswith("seed")


def test_env_offline_flag(make, monkeypatch):
    monkeypatch.setenv("HQ_OFFLINE", "1")
    with respx.mock(assert_all_called=False) as router:
        route = router.route(host=HOST)
        assert make().rate("TWD")[0] == 3.0
        assert not route.called


def test_seed_cross_rate_and_aliases(make):
    fx = make(offline=True)
    assert fx.rate("TWD", "USD")[0] == pytest.approx(3.0 / 95.0)
    assert fx.rate("ntd")[0] == 3.0
    with pytest.raises(FxUnavailable):
        fx.rate("PLN")


@respx.mock
def test_live_v1_then_cached(make, tmp_path):
    route = respx.route(host=HOST, path="/v1/latest").mock(side_effect=v1_ok(95.82))
    fx = make(offline=False)
    assert fx.rate("USD") == (95.82, "2026-09-25", fx_mod.SOURCE_V1)
    cache = json.loads((tmp_path / "fx" / "rates.json").read_text())
    (day,) = cache["days"]
    assert cache["days"][day]["USD/INR"]["rate"] == 95.82
    # a fresh provider reads today's cache instead of the network
    assert make(offline=False).rate("USD")[0] == 95.82
    assert route.call_count == 1


@respx.mock
def test_v2_used_when_ecb_lacks_currency(make):
    respx.route(host=HOST, path="/v1/latest").mock(return_value=httpx.Response(404, json={"message": "not found"}))
    v2 = respx.route(host=HOST, path="/v2/rate/TWD/INR").mock(
        return_value=httpx.Response(200, json={"date": "2026-09-26", "base": "TWD", "quote": "INR", "rate": 3.0144}))
    assert make(offline=False).rate("TWD") == (3.0144, "2026-09-26", fx_mod.SOURCE_V2)
    assert v2.called


@respx.mock
def test_network_error_falls_back_to_seed_and_backs_off(make):
    route = respx.route(host=HOST).mock(side_effect=httpx.ConnectError("offline"))
    fx = make(offline=False)
    rate, _, source = fx.rate("USD")
    assert rate == 95.0 and source.startswith("seed")
    fx.rate("TWD")
    assert route.call_count == 1  # second lookup skipped the network during back-off


@respx.mock
def test_network_error_prefers_stale_cache(make, tmp_path):
    cache = tmp_path / "fx" / "rates.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"version": 1, "days": {"2000-01-01": {"USD/INR": {
        "rate": 90.0, "date": "1999-12-31", "source": fx_mod.SOURCE_V1}}}}))
    respx.route(host=HOST).mock(side_effect=httpx.ConnectError("offline"))
    rate, _, source = make(offline=False).rate("USD")
    assert rate == 90.0 and "stale" in source


@respx.mock
def test_unknown_everywhere_raises(make):
    respx.route(host=HOST).mock(return_value=httpx.Response(422, json={"message": "invalid currency"}))
    with pytest.raises(FxUnavailable):
        make(offline=False).rate("XYZ")


def test_default_cache_follows_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_DB_PATH", str(tmp_path / "db" / "hq.db"))
    assert fx_mod.default_cache_path() == tmp_path / "db" / "fx" / "rates.json"
    assert fx_mod.default().cache_path == tmp_path / "db" / "fx" / "rates.json"


def test_committed_seed_covers_required_currencies():
    seed = json.loads(SEED_PATH.read_text())
    assert seed["seed"] is True and seed["quote"] == "INR"
    for code in SEED_CURRENCIES:
        entry = seed["rates"][code]
        assert entry["rate"] > 0 and entry["date"] and entry["source"], code
    assert 80 < seed["rates"]["USD"]["rate"] < 110
