"""Phase 4: multi-currency.

Trades are entered in their native currency with an fx_rate (native -> base).
The cash pool, realized P&L, and stats aggregates are stored/summed in the base
currency, so a multi-currency portfolio no longer mixes units. FX is passed
explicitly here (no network in tests); same-currency trades resolve to fx=1.
"""
import sqlite3

import db
import fx_service


def _set_base(client, code):
    r = client.put("/settings", json={"base_currency": code})
    assert r.status_code == 200
    return r.json()


def test_base_currency_syncs_with_currency(client):
    # Setting currency mirrors into base_currency and vice-versa.
    s = client.put("/settings", json={"currency": "EUR"}).json()
    assert s["currency"] == "EUR" and s["base_currency"] == "EUR"
    s = client.put("/settings", json={"base_currency": "GBP"}).json()
    assert s["base_currency"] == "GBP" and s["currency"] == "GBP"


def test_same_currency_trade_has_fx_1(client, user_id):
    t = client.post(f"/users/{user_id}/trades", json={
        "ticker": "AAPL", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
    }).json()
    assert t["trade_currency"] == "USD"
    assert t["fx_rate"] == 1.0


def test_trade_currency_inherits_instrument_currency(client, user_id):
    # A trade with no explicit trade_currency inherits the linked instrument's
    # currency (e.g. a EUR-denominated German instrument logs cost basis in EUR),
    # so price and cost basis share one currency without any conversion.
    inst = client.post("/instruments", json={
        "symbol": "DE000BASF111", "ticker": "BAS", "name": "BASF",
        "asset_class": "stock", "currency": "EUR",
    }).json()
    t = client.post(f"/users/{user_id}/trades", json={
        "ticker": "BAS", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 50, "trade_date": "2026-05-01",
        "instrument_id": inst["id"],  # no trade_currency sent
    }).json()
    assert t["trade_currency"] == "EUR"


def test_foreign_buy_converts_cash_to_base(client, user_id):
    # Base USD; buy 10 @ 100 EUR with fx 1.10 -> cash debit 1100 USD.
    t = client.post(f"/users/{user_id}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
        "trade_currency": "EUR", "fx_rate": 1.10,
    }).json()
    assert t["trade_currency"] == "EUR"
    assert t["fx_rate"] == 1.10
    assert t["total_value"] == 1000.0  # native, unchanged
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == -1100.0  # base currency


def test_foreign_realized_pnl_in_base(client, user_id):
    # Buy 10 @ 100 EUR (fx 1.10), sell 10 @ 120 EUR (fx 1.20).
    # realized base = 120*10*1.20 - 100*10*1.10 = 1440 - 1100 = 340
    buy = client.post(f"/users/{user_id}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
        "trade_currency": "EUR", "fx_rate": 1.10,
    }).json()
    lot = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 10, "sell_price_per_unit": 120, "sell_date": "2026-05-10",
        "fx_rate": 1.20,
    }).json()
    assert lot["realized_pnl"] == 340.0
    stats = client.get(f"/users/{user_id}/stats").json()
    assert stats["net_realized_pnl"] == 340.0


def test_fx_only_move_is_a_gain(client, user_id):
    # Same local price, but EUR strengthened 1.10 -> 1.20: pure FX gain of 200.
    buy = client.post(f"/users/{user_id}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
        "trade_currency": "EUR", "fx_rate": 1.10,
    }).json()
    lot = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 10, "sell_price_per_unit": 100, "sell_date": "2026-05-10",
        "fx_rate": 1.20,
    }).json()
    # 100*10*1.20 - 100*10*1.10 = 1200 - 1100 = 100
    assert lot["realized_pnl"] == 100.0


def test_stats_volume_in_base(client, user_id):
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
        "trade_currency": "EUR", "fx_rate": 1.50,
    })
    stats = client.get(f"/users/{user_id}/stats").json()
    assert stats["buy_volume"] == 1500.0  # 1000 EUR * 1.50


def test_position_exposes_currency_and_base_basis(client, user_id):
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
        "trade_currency": "EUR", "fx_rate": 1.10,
    })
    pos = client.get(f"/users/{user_id}/positions").json()[0]
    assert pos["currency"] == "EUR"
    assert pos["total_cost_basis"] == 1000.0       # native
    assert pos["total_cost_basis_base"] == 1100.0  # base


def test_fx_rate_must_be_positive(client, user_id):
    r = client.post(f"/users/{user_id}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy",
        "quantity": 1, "price_per_unit": 1, "trade_date": "2026-05-01",
        "trade_currency": "EUR", "fx_rate": 0,
    })
    assert r.status_code == 422


def test_fx_endpoint_same_currency(client):
    r = client.get("/fx/USD/USD")
    assert r.status_code == 200
    assert r.json()["rate"] == 1.0


def test_fx_service_same_currency_no_network(client):
    conn = sqlite3.connect(db.DB_PATH)
    try:
        assert fx_service.get_or_fetch_fx(conn, "USD", "USD") == 1.0
        assert fx_service.get_cached_fx(conn, "EUR", "EUR") == 1.0
    finally:
        conn.close()


def test_fx_cache_roundtrip(client):
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO fx_rates (from_currency, to_currency, rate, source) "
            "VALUES ('EUR', 'USD', 1.08, 'yahoo_finance')"
        )
        conn.commit()
        assert fx_service.get_cached_fx(conn, "EUR", "USD") == 1.08
    finally:
        conn.close()
