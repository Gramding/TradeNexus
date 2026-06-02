"""Phase 2: contract-multiplier correctness for options.

A Call/Put quote is per-share but each contract controls `multiplier` shares
(100 for US equity options). These tests pin the multiplier into total_value,
cash movement, realized P&L on sells, position cost basis, and unrealized P&L.
"""
from conftest import make_trade


def _buy_option(client, uid, ttype="Call", **overrides):
    body = {
        "ticker": "AAPL", "trade_type": ttype, "action": "buy",
        "quantity": 2, "price_per_unit": 2.50, "trade_date": "2026-05-01",
    }
    body.update(overrides)
    r = client.post(f"/users/{uid}/trades", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_call_defaults_to_100x_multiplier(client, user_id):
    t = _buy_option(client, user_id)  # 2 contracts @ $2.50
    assert t["multiplier"] == 100.0
    # notional = 2 * 2.50 * 100 = 500, not 5
    assert t["total_value"] == 500.0


def test_stock_multiplier_is_1(client, user_id):
    t = make_trade(client, user_id, quantity=10, price_per_unit=100)
    assert t["multiplier"] == 1.0
    assert t["total_value"] == 1000.0


def test_explicit_multiplier_override(client, user_id):
    # A futures-style 50x contract entered as "Other".
    t = _buy_option(client, user_id, ttype="Other", multiplier=50,
                    quantity=1, price_per_unit=10)
    assert t["multiplier"] == 50.0
    assert t["total_value"] == 500.0


def test_multiplier_must_be_positive(client, user_id):
    r = client.post(f"/users/{user_id}/trades", json={
        "ticker": "AAPL", "trade_type": "Call", "action": "buy",
        "quantity": 1, "price_per_unit": 1, "trade_date": "2026-05-01",
        "multiplier": 0,
    })
    assert r.status_code == 422


def test_option_buy_deducts_full_notional_from_cash(client, user_id):
    _buy_option(client, user_id)  # notional 500
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == -500.0


def test_option_strike_and_expiration_persist(client, user_id):
    t = _buy_option(client, user_id, strike_price=150,
                    expiration_date="2026-06-19", underlying="aapl")
    assert t["strike_price"] == 150.0
    assert t["expiration_date"] == "2026-06-19"
    assert t["underlying"] == "AAPL"


def test_option_realized_pnl_scaled_by_multiplier(client, user_id):
    buy = _buy_option(client, user_id, quantity=2, price_per_unit=2.50)  # cost 500
    # Sell 2 @ 4.00 -> proceeds = 2 * 4.00 * 100 = 800; pnl = 800 - 500 = 300
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 2, "sell_price_per_unit": 4.00, "sell_date": "2026-05-10",
    })
    assert r.status_code == 201
    lot = r.json()
    assert lot["proceeds"] == 800.0
    assert lot["realized_pnl"] == 300.0


def test_option_sell_cash_credit_scaled(client, user_id):
    buy = _buy_option(client, user_id, quantity=2, price_per_unit=2.50)  # cash -500
    client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 2, "sell_price_per_unit": 4.00, "sell_date": "2026-05-10",
    })  # +800
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == 300.0


def test_option_position_cost_basis_scaled(client, user_id):
    _buy_option(client, user_id, quantity=2, price_per_unit=2.50)
    positions = client.get(f"/users/{user_id}/positions").json()
    pos = next(p for p in positions if p["trade_type"] == "Call")
    assert pos["multiplier"] == 100.0
    # avg cost stays per-unit (comparable to a quote), basis carries the multiplier
    assert pos["avg_cost_per_unit"] == 2.50
    assert pos["total_cost_basis"] == 500.0


def test_changing_type_to_call_updates_multiplier(client, user_id):
    t = make_trade(client, user_id, quantity=1, price_per_unit=2.50)  # Stock, 1x, tv 2.50
    assert t["multiplier"] == 1.0
    r = client.put(f"/trades/{t['id']}", json={"trade_type": "Call"})
    assert r.status_code == 200
    updated = r.json()
    assert updated["multiplier"] == 100.0
    assert updated["total_value"] == 250.0
