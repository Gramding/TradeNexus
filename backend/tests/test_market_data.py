"""Market-data correctness: quote currencies, FX fallbacks and failed-fetch caching.

Live sources are replaced with fakes that return the shapes the real APIs do
(Yahoo quotes London listings in pence as "GBp"; onvista quotes US stocks in EUR).
"""
import sqlite3
import sys
import types

import pytest

import db
import price_service as ps
from conftest import REAL_YAHOO_FETCH


def _seed(sql, *params):
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _seed_price(symbol, price, currency, source="yahoo_finance"):
    _seed("INSERT INTO price_cache (symbol, price, currency, source) VALUES (?, ?, ?, ?)",
          symbol, price, currency, source)


def _seed_fx(frm, to, rate, fetched_at=None):
    if fetched_at is None:
        _seed("INSERT INTO fx_rates (from_currency, to_currency, rate) VALUES (?, ?, ?)", frm, to, rate)
    else:
        _seed("INSERT INTO fx_rates (from_currency, to_currency, rate, fetched_at) VALUES (?, ?, ?, ?)",
              frm, to, rate, fetched_at)


def _cash(client, uid):
    return client.get(f"/users/{uid}/cash").json()["balance"]


def _buy(client, uid, **kw):
    body = {"ticker": "X", "trade_type": "Stock", "action": "buy", "quantity": 10,
            "price_per_unit": 100, "trade_date": "2026-05-01"}
    body.update(kw)
    return client.post(f"/users/{uid}/trades", json=body)


# ── Minor currency units ────────────────────────────────────────────────────

@pytest.mark.parametrize("price, ccy, expected", [
    (72.5, "GBp", (0.725, "GBP")),
    (72.5, "GBX", (0.725, "GBP")),
    (1500, "ZAc", (15.0, "ZAR")),
    (2500, "ILA", (25.0, "ILS")),
    (72.5, "GBP", (72.5, "GBP")),   # pounds stay pounds
    (10, "eur", (10, "EUR")),
])
def test_normalize_quote(price, ccy, expected):
    assert ps.normalize_quote(price, ccy) == expected


def test_yahoo_fetch_normalizes_minor_units(monkeypatch):
    fake_ticker = types.SimpleNamespace(fast_info=types.SimpleNamespace(last_price=72.5, currency="GBp"))
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=lambda s: fake_ticker))
    assert REAL_YAHOO_FETCH(ps.YahooFinanceSource(), "VOD.L") == {
        "price": 0.725, "currency": "GBP", "source": "yahoo_finance",
    }


def test_legacy_pence_cache_row_is_normalized_on_read(client):
    _seed_price("VOD.L", 72.5, "GBp")
    r = client.get("/prices/VOD.L", params={"cache_only": True})
    assert r.status_code == 200
    assert r.json()["price"] == 0.725
    assert r.json()["currency"] == "GBP"


def test_instrument_currency_stored_in_major_unit(client):
    inst = client.post("/instruments", json={
        "symbol": "VOD.L", "ticker": "VOD", "asset_class": "stock", "currency": "GBp",
    }).json()
    assert inst["currency"] == "GBP"


def test_pence_quote_values_pound_position_correctly(client, user_id):
    # 1,000 Vodafone bought at 0.70 GBP, now quoted 72.5p: unrealized is +25 GBP,
    # not the +71,800 a raw pence-vs-pounds comparison produced.
    client.put("/settings", json={"base_currency": "GBP"})
    inst = client.post("/instruments", json={
        "symbol": "VOD.L", "ticker": "VOD", "asset_class": "stock", "currency": "GBp",
    }).json()
    assert _buy(client, user_id, ticker="VOD", quantity=1000, price_per_unit=0.70,
                instrument_id=inst["id"]).status_code == 201
    _seed_price("VOD.L", 72.5, "GBp")

    pos = client.get(f"/users/{user_id}/positions/prices").json()[0]
    assert pos["currency"] == "GBP"
    assert pos["current_price"] == pytest.approx(0.725)
    assert pos["unrealized_pnl"] == pytest.approx(25.0)


# ── Quote currency differs from position currency ───────────────────────────

def test_eur_quote_converted_into_usd_position(client, user_id):
    # Apple booked in USD, priced by onvista in EUR (215 EUR at 1.16 = 249.40 USD).
    inst = client.post("/instruments", json={
        "symbol": "AAPL", "ticker": "AAPL", "asset_class": "stock",
        "currency": "USD", "isin": "US0378331005",
    }).json()
    _buy(client, user_id, ticker="AAPL", quantity=10, price_per_unit=200, instrument_id=inst["id"])
    _seed_price("US0378331005", 215.0, "EUR", source="onvista")
    _seed_fx("EUR", "USD", 1.16)

    pos = client.get(f"/users/{user_id}/positions/prices", params={"source": "onvista"}).json()[0]
    assert pos["quote_price"] == 215.0
    assert pos["quote_currency"] == "EUR"
    assert pos["current_price"] == pytest.approx(249.4)
    assert pos["unrealized_pnl"] == pytest.approx(494.0)
    assert pos["price_error"] is None


def test_quote_without_fx_shows_unavailable_not_wrong(client, user_id):
    inst = client.post("/instruments", json={
        "symbol": "AAPL", "ticker": "AAPL", "asset_class": "stock",
        "currency": "USD", "isin": "US0378331005",
    }).json()
    _buy(client, user_id, ticker="AAPL", instrument_id=inst["id"])
    _seed_price("US0378331005", 215.0, "EUR", source="onvista")  # no EUR->USD rate known

    pos = client.get(f"/users/{user_id}/positions/prices", params={"source": "onvista"}).json()[0]
    assert pos["current_price"] is None
    assert pos["unrealized_pnl"] is None
    assert "EUR" in pos["price_error"]


def test_base_view_unavailable_without_fx(client, user_id):
    # EUR position, USD base, no live EUR->USD: native figures still show, the
    # base-currency figures are None instead of being converted at 1.0.
    _buy(client, user_id, ticker="SAP", trade_currency="EUR", fx_rate=1.10)
    _seed_price("SAP", 110, "EUR")
    pos = client.get(f"/users/{user_id}/positions/prices").json()[0]
    assert pos["unrealized_pnl"] == pytest.approx(100.0)
    assert pos["current_value_base"] is None
    assert pos["unrealized_pnl_base"] is None


# ── FX at trade time ────────────────────────────────────────────────────────

def test_trade_rejected_when_no_fx_rate_known(client, user_id):
    before = _cash(client, user_id)
    r = _buy(client, user_id, ticker="SAP", trade_currency="EUR")
    assert r.status_code == 503
    assert "EUR" in r.json()["detail"]
    assert client.get(f"/users/{user_id}/trades").json()["trades"] == []
    assert _cash(client, user_id) == before


def test_trade_uses_stale_cached_fx_when_live_fails(client, user_id):
    _seed_fx("EUR", "USD", 1.12, fetched_at="2020-01-01 00:00:00")
    r = _buy(client, user_id, ticker="SAP", trade_currency="EUR")
    assert r.status_code == 201, r.text
    assert r.json()["fx_rate"] == 1.12


def test_explicit_fx_rate_still_wins(client, user_id):
    r = _buy(client, user_id, ticker="SAP", trade_currency="EUR", fx_rate=1.05)
    assert r.status_code == 201
    assert r.json()["fx_rate"] == 1.05


def test_sell_falls_back_to_buy_fx_when_live_fails(client, user_id):
    buy = _buy(client, user_id, ticker="SAP", trade_currency="EUR", fx_rate=1.10).json()
    before = _cash(client, user_id)
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 10, "sell_price_per_unit": 110, "sell_date": "2026-06-01",
    })
    assert r.status_code == 201, r.text
    # 1,100 EUR of proceeds credited at the buy's 1.10, not at a made-up 1.0.
    assert _cash(client, user_id) - before == pytest.approx(1210.0)


def test_event_rejected_when_no_fx_rate_known(client, user_id):
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "fee", "event_date": "2026-05-01", "amount": 5, "currency": "EUR",
    })
    assert r.status_code == 503


# ── Failed-fetch cache ──────────────────────────────────────────────────────

def test_failed_fetch_is_not_retried_immediately(client, monkeypatch):
    calls = []

    class Failing(ps.PriceSource):
        def fetch(self, symbol):
            calls.append(symbol)
            return None

    monkeypatch.setitem(ps._SOURCES, "yahoo_finance", Failing)
    conn = db.get_connection()
    try:
        assert ps.get_or_fetch_price(conn, "NOPE") is None
        assert ps.get_or_fetch_price(conn, "NOPE") is None
        assert calls == ["NOPE"]
        # A forced refresh (Refresh button) always retries.
        assert ps.get_or_fetch_price(conn, "NOPE", max_age_minutes=0) is None
        assert calls == ["NOPE", "NOPE"]
    finally:
        conn.close()
