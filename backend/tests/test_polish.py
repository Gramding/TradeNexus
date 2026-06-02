"""Phase 7 polish: pinned follow-ups documented in earlier phases.

  1) Option positions group by strike + expiration (Phase 2 caveat).
  2) Per-position UNREALIZED P&L in base currency (Phase 4 caveat).
  3) Global-search position previews include shorts (Phase 3 caveat).
"""
import sqlite3

import db


def _opt(client, uid, strike, expiration, **overrides):
    body = {
        "ticker": "AAPL", "trade_type": "Call", "action": "buy",
        "quantity": 1, "price_per_unit": 2.50, "trade_date": "2026-05-01",
        "strike_price": strike, "expiration_date": expiration,
    }
    body.update(overrides)
    r = client.post(f"/users/{uid}/trades", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── 1. option grouping by strike + expiration ───────────────────────────────

def test_two_calls_different_strikes_are_separate_positions(client, user_id):
    _opt(client, user_id, strike=150, expiration="2026-06-19")
    _opt(client, user_id, strike=160, expiration="2026-06-19")
    positions = client.get(f"/users/{user_id}/positions").json()
    assert len(positions) == 2
    strikes = sorted(p["strike_price"] for p in positions)
    assert strikes == [150.0, 160.0]


def test_two_calls_different_expirations_are_separate_positions(client, user_id):
    _opt(client, user_id, strike=150, expiration="2026-06-19")
    _opt(client, user_id, strike=150, expiration="2026-07-17")
    positions = client.get(f"/users/{user_id}/positions").json()
    assert len(positions) == 2
    expirations = sorted(p["expiration_date"] for p in positions)
    assert expirations == ["2026-06-19", "2026-07-17"]


def test_same_strike_and_expiration_still_aggregates(client, user_id):
    _opt(client, user_id, strike=150, expiration="2026-06-19", quantity=1)
    _opt(client, user_id, strike=150, expiration="2026-06-19", quantity=2)
    positions = client.get(f"/users/{user_id}/positions").json()
    assert len(positions) == 1
    assert positions[0]["total_remaining_quantity"] == 3


def test_stocks_still_group_when_strike_null(client, user_id):
    body_base = {
        "ticker": "AAPL", "trade_type": "Stock", "action": "buy",
        "quantity": 1, "price_per_unit": 100, "trade_date": "2026-05-01",
    }
    client.post(f"/users/{user_id}/trades", json=body_base)
    client.post(f"/users/{user_id}/trades", json={**body_base, "quantity": 2, "price_per_unit": 110})
    positions = client.get(f"/users/{user_id}/positions").json()
    assert len(positions) == 1
    assert positions[0]["total_remaining_quantity"] == 3


# ── 2. per-position unrealized P&L in base currency ─────────────────────────

def test_positions_prices_exposes_base_unrealized(client, user_id):
    # Foreign buy (EUR at fx 1.10), then a live USD price simulated via cache.
    client.put("/settings", json={"base_currency": "USD"})
    inst = client.post("/instruments", json={
        "symbol": "SAP.DE", "ticker": "SAP", "asset_class": "stock", "currency": "EUR",
    }).json()
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
        "instrument_id": inst["id"], "trade_currency": "EUR", "fx_rate": 1.10,
    })
    # Seed a "current" EUR price + a fresh EUR->USD live FX rate the route reads.
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute("INSERT INTO price_cache (symbol, price, currency, source) "
                     "VALUES ('SAP.DE', 110, 'EUR', 'yahoo_finance')")
        conn.execute("INSERT INTO fx_rates (from_currency, to_currency, rate, source) "
                     "VALUES ('EUR', 'USD', 1.20, 'yahoo_finance')")
        conn.commit()
    finally:
        conn.close()

    pos = client.get(f"/users/{user_id}/positions/prices").json()[0]
    # Native: cost 1000 EUR, value 1100 EUR, unrealized +100 EUR
    assert pos["total_cost_basis"] == 1000.0
    assert pos["current_value"] == 1100.0
    assert pos["unrealized_pnl"] == 100.0
    # Base: cost converted at the lot's stored fx (1.10) = 1100 USD; value at
    # live fx (1.20) = 1320 USD; unrealized in base = +220 USD.
    assert pos["total_cost_basis_base"] == 1100.0
    assert pos["current_value_base"] == 1320.0
    assert pos["unrealized_pnl_base"] == 220.0


def test_base_unrealized_equals_native_for_same_currency(client, user_id):
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "AAPL", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
    })
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute("INSERT INTO price_cache (symbol, price, currency, source) "
                     "VALUES ('AAPL', 120, 'USD', 'yahoo_finance')")
        conn.commit()
    finally:
        conn.close()
    pos = client.get(f"/users/{user_id}/positions/prices").json()[0]
    assert pos["unrealized_pnl"] == pos["unrealized_pnl_base"] == 200.0


# ── 3. shorts in global search positions ────────────────────────────────────

def test_search_positions_includes_shorts(client, user_id):
    # Open a short on TSLA
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "TSLA", "trade_type": "Stock", "action": "sell",
        "quantity": 5, "price_per_unit": 200, "trade_date": "2026-05-01",
    })
    bucket = client.get("/search", params={"user_id": user_id, "q": "TS"}).json()
    rows = bucket["positions"]["results"]
    assert len(rows) == 1
    assert rows[0]["direction"] == "short"
    assert rows[0]["ticker"] == "TSLA"


def test_search_positions_separates_long_and_short_same_ticker(client, user_id):
    # Long + short on NVDA
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "NVDA", "trade_type": "Stock", "action": "buy",
        "quantity": 3, "price_per_unit": 100, "trade_date": "2026-05-01",
    })
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "NVDA", "trade_type": "Stock", "action": "sell",
        "quantity": 2, "price_per_unit": 110, "trade_date": "2026-05-02",
    })
    rows = client.get("/search", params={"user_id": user_id, "q": "NV"}).json()["positions"]["results"]
    dirs = sorted(r["direction"] for r in rows)
    assert dirs == ["long", "short"]
