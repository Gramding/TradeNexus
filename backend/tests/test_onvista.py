"""Onvista price source + German ISIN resolution.

The network is mocked at the _onvista_resolve seam so these tests never touch
onvista.de. _onvista_run is replaced with an identity passthrough so the (now
synchronous) fake resolver flows straight through the sync bridge.
"""
import pytest

import price_service as ps
from conftest import make_trade


def _fake_snapshot(isin, *, name="BASF", symbol="BAS", entity_type="STOCK",
                   price=49.005, currency="EUR", exchange="GER"):
    """A stand-in for the normalized dict _onvista_resolve returns from a snapshot."""
    return {
        "price":       price,
        "currency":    currency,
        "name":        name,
        "symbol":      symbol,
        "entity_type": entity_type,
        "exchange":    exchange,
        "isin":        isin,
    }


@pytest.fixture
def mock_onvista(monkeypatch):
    """Route onvista resolution to a local fake. Returns a dict the test can tweak
    (e.g. set 'instrument' to None to simulate a miss)."""
    state = {"instrument": _fake_snapshot("DE000BASF111")}
    monkeypatch.setattr(ps, "_onvista_resolve", lambda isin: state["instrument"])
    monkeypatch.setattr(ps, "_onvista_run", lambda x: x)  # identity: fake is already a value
    return state


# ── Source.fetch ────────────────────────────────────────────────────────────

def test_onvista_source_fetch(mock_onvista):
    result = ps.get_price_source("onvista").fetch("DE000BASF111")
    assert result == {"price": 49.005, "currency": "EUR", "source": "onvista"}


def test_onvista_fetch_rejects_non_isin(mock_onvista):
    # A non-ISIN never reaches the network and returns None.
    assert ps.OnvistaSource().fetch("AAPL") is None


def test_onvista_fetch_miss_returns_none(mock_onvista):
    mock_onvista["instrument"] = None
    assert ps.OnvistaSource().fetch("DE000BASF111") is None


def test_onvista_fetch_uses_snapshot_currency(mock_onvista):
    # The price's own currency (from the snapshot) is reported, not a hardcoded EUR.
    mock_onvista["instrument"] = _fake_snapshot("US0000000000", price=1.5, currency="USD")
    assert ps.OnvistaSource().fetch("US0000000000") == {
        "price": 1.5, "currency": "USD", "source": "onvista",
    }


def test_onvista_fetch_derivative(mock_onvista):
    # A warrant/certificate (entityType DERIVATIVE) resolves like any other type —
    # this is the class the faceted search used to drop, leaving prices unfound.
    mock_onvista["instrument"] = _fake_snapshot(
        "DE000GW1MCC0", name="CALL/APPLIED MATERIALS", symbol="", entity_type="DERIVATIVE",
        price=14.105,
    )
    assert ps.OnvistaSource().fetch("DE000GW1MCC0") == {
        "price": 14.105, "currency": "EUR", "source": "onvista",
    }


def test_resolve_isin_derivative_asset_class(mock_onvista):
    # A derivative maps to the 'other' asset class and falls back to the ISIN as
    # ticker when onvista exposes no short symbol.
    mock_onvista["instrument"] = _fake_snapshot(
        "DE000GW1MCC0", name="CALL/APPLIED MATERIALS", symbol="", entity_type="DERIVATIVE",
    )
    inst = ps.resolve_isin("DE000GW1MCC0")
    assert inst["asset_class"] == "other"
    assert inst["ticker"] == "DE000GW1MCC0"
    assert inst["name"] == "CALL/APPLIED MATERIALS"


def test_onvista_registered():
    assert "onvista" in ps._SOURCES
    assert isinstance(ps.get_price_source("onvista"), ps.OnvistaSource)


# ── resolve_isin ────────────────────────────────────────────────────────────

def test_resolve_isin(mock_onvista):
    inst = ps.resolve_isin("de000basf111")  # lower-case tolerated
    assert inst == {
        "symbol":      "DE000BASF111",
        "ticker":      "BAS",
        "name":        "BASF",
        "exchange":    "GER",
        "asset_class": "stock",
        "currency":    "EUR",
        "isin":        "DE000BASF111",
    }


def test_resolve_isin_bad_format_skips_network(monkeypatch):
    # Invalid ISINs short-circuit before any resolution attempt.
    called = {"n": 0}
    monkeypatch.setattr(ps, "_onvista_resolve", lambda isin: called.__setitem__("n", called["n"] + 1))
    assert ps.resolve_isin("not-an-isin") is None
    assert called["n"] == 0


# ── Settings validation ─────────────────────────────────────────────────────

def test_settings_accepts_known_price_source(client):
    r = client.put("/settings", json={"price_source": "onvista"})
    assert r.status_code == 200, r.text
    assert client.get("/settings").json()["price_source"] == "onvista"


def test_settings_rejects_unknown_price_source(client):
    r = client.put("/settings", json={"price_source": "bogus_source"})
    assert r.status_code == 400


# ── ISIN instrument search ──────────────────────────────────────────────────

def test_isin_search_resolves_via_onvista(client, mock_onvista):
    r = client.get("/instruments/search", params={"q": "DE000BASF111"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "onvista"
    assert len(body["results"]) == 1
    assert body["results"][0]["isin"] == "DE000BASF111"
    assert body["results"][0]["currency"] == "EUR"


def test_isin_search_miss(client, mock_onvista):
    mock_onvista["instrument"] = None
    r = client.get("/instruments/search", params={"q": "DE000BASF111"})
    assert r.status_code == 200
    assert r.json()["results"] == []


# ── positions/prices using the onvista source ───────────────────────────────

def test_positions_prices_onvista_fetches_by_isin(client, user_id, mock_onvista):
    # An instrument carrying an ISIN, linked to an open position.
    inst = client.post("/instruments", json={
        "symbol": "BAS.DE", "ticker": "BAS", "name": "BASF",
        "asset_class": "stock", "currency": "EUR", "isin": "DE000BASF111",
    }).json()
    make_trade(client, user_id, ticker="BAS", instrument_id=inst["id"],
               trade_currency="EUR", price_per_unit=40)

    r = client.get(f"/users/{user_id}/positions/prices", params={"source": "onvista"})
    assert r.status_code == 200, r.text
    pos = r.json()[0]
    assert pos["isin"] == "DE000BASF111"
    assert pos["price_id"] == "DE000BASF111"   # fetched by ISIN, not symbol
    assert pos["current_price"] == 49.005
    assert pos["price_source"] == "onvista"


def test_positions_prices_onvista_recovers_isin_from_symbol(client, user_id, mock_onvista):
    # The instrument's dedicated isin column is blank while the ISIN lives in the
    # symbol (e.g. an ISIN-keyed instrument). onvista must still resolve a price by
    # recovering the ISIN from the symbol instead of showing n/a.
    inst = client.post("/instruments", json={
        "symbol": "DE000BASF111", "ticker": "DE000BASF111", "name": "BASF",
        "asset_class": "stock", "currency": "EUR",  # no isin field
    }).json()
    make_trade(client, user_id, ticker="DE000BASF111", instrument_id=inst["id"],
               trade_currency="EUR", price_per_unit=40)

    r = client.get(f"/users/{user_id}/positions/prices", params={"source": "onvista"})
    assert r.status_code == 200, r.text
    pos = r.json()[0]
    assert pos["price_id"] == "DE000BASF111"   # recovered from symbol
    assert pos["current_price"] == 49.005
    assert pos["price_source"] == "onvista"
