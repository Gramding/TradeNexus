"""Phase 3: short positions (sell-to-open + buy-to-cover).

A short is opened with action='sell' (cash is credited with the proceeds) and
closed with a buy-to-cover via /trades/{id}/cover. Profit is the open proceeds
minus the buy-back cost, so a falling price is a gain — the mirror image of a
long. These tests pin cash, realized P&L, position direction, and cleanup.
"""


def _open_short(client, uid, **overrides):
    body = {
        "ticker": "TSLA", "trade_type": "Stock", "action": "sell",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
    }
    body.update(overrides)
    r = client.post(f"/users/{uid}/trades", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_sell_opens_short_and_credits_cash(client, user_id):
    t = _open_short(client, user_id)  # sell 10 @ 100 -> +1000
    assert t["direction"] == "short"
    assert t["action"] == "sell"
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == 1000.0


def test_short_appears_as_short_position(client, user_id):
    _open_short(client, user_id, quantity=10, price_per_unit=100)
    positions = client.get(f"/users/{user_id}/positions").json()
    assert len(positions) == 1
    pos = positions[0]
    assert pos["direction"] == "short"
    assert pos["total_remaining_quantity"] == 10
    assert pos["avg_cost_per_unit"] == 100
    assert pos["total_cost_basis"] == 1000.0   # proceeds received


def test_direction_must_match_action(client, user_id):
    # A buy can't be a short open; a sell can't be a long open.
    r = client.post(f"/users/{user_id}/trades", json={
        "ticker": "X", "trade_type": "Stock", "action": "buy", "direction": "short",
        "quantity": 1, "price_per_unit": 1, "trade_date": "2026-05-01",
    })
    assert r.status_code == 422
    r = client.post(f"/users/{user_id}/trades", json={
        "ticker": "X", "trade_type": "Stock", "action": "sell", "direction": "long",
        "quantity": 1, "price_per_unit": 1, "trade_date": "2026-05-01",
    })
    assert r.status_code == 422


def test_cover_profit_when_price_falls(client, user_id):
    short = _open_short(client, user_id, quantity=10, price_per_unit=100)  # +1000
    # Buy back 10 @ 70 -> cost 700, pnl = 1000 - 700 = 300
    r = client.post(f"/trades/{short['id']}/cover", json={
        "quantity_covered": 10, "cover_price_per_unit": 70, "cover_date": "2026-05-10",
    })
    assert r.status_code == 201, r.text
    lot = r.json()
    assert lot["realized_pnl"] == 300.0
    # cash: +1000 (open) - 700 (cover) = 300
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == 300.0


def test_cover_loss_when_price_rises(client, user_id):
    short = _open_short(client, user_id, quantity=10, price_per_unit=100)  # +1000
    r = client.post(f"/trades/{short['id']}/cover", json={
        "quantity_covered": 10, "cover_price_per_unit": 130, "cover_date": "2026-05-10",
    })  # cost 1300, pnl = 1000 - 1300 = -300
    assert r.json()["realized_pnl"] == -300.0
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -300.0


def test_partial_cover_updates_remaining(client, user_id):
    short = _open_short(client, user_id, quantity=10, price_per_unit=100)
    client.post(f"/trades/{short['id']}/cover", json={
        "quantity_covered": 4, "cover_price_per_unit": 90, "cover_date": "2026-05-10",
    })
    positions = client.get(f"/users/{user_id}/positions").json()
    pos = next(p for p in positions if p["direction"] == "short")
    assert pos["total_remaining_quantity"] == 6


def test_overcover_rejected(client, user_id):
    short = _open_short(client, user_id, quantity=5, price_per_unit=100)
    r = client.post(f"/trades/{short['id']}/cover", json={
        "quantity_covered": 6, "cover_price_per_unit": 90, "cover_date": "2026-05-10",
    })
    assert r.status_code == 400


def test_cannot_cover_a_long(client, user_id):
    buy = client.post(f"/users/{user_id}/trades", json={
        "ticker": "AAPL", "trade_type": "Stock", "action": "buy",
        "quantity": 5, "price_per_unit": 100, "trade_date": "2026-05-01",
    }).json()
    r = client.post(f"/trades/{buy['id']}/cover", json={
        "quantity_covered": 5, "cover_price_per_unit": 90, "cover_date": "2026-05-10",
    })
    assert r.status_code == 400


def test_cannot_sell_a_short_via_sell_endpoint(client, user_id):
    short = _open_short(client, user_id, quantity=5, price_per_unit=100)
    r = client.post(f"/trades/{short['id']}/sell", json={
        "quantity_sold": 5, "sell_price_per_unit": 90, "sell_date": "2026-05-10",
    })
    assert r.status_code == 400


def test_short_realized_pnl_flows_to_stats(client, user_id):
    short = _open_short(client, user_id, quantity=10, price_per_unit=100)
    client.post(f"/trades/{short['id']}/cover", json={
        "quantity_covered": 10, "cover_price_per_unit": 80, "cover_date": "2026-05-10",
    })  # pnl +200
    stats = client.get(f"/users/{user_id}/stats").json()
    assert stats["net_realized_pnl"] == 200.0


def test_delete_short_open_reverses_cash_and_covers(client, user_id):
    start = client.get(f"/users/{user_id}/cash").json()["balance"]
    short = _open_short(client, user_id, quantity=10, price_per_unit=100)  # +1000
    client.post(f"/trades/{short['id']}/cover", json={
        "quantity_covered": 4, "cover_price_per_unit": 70, "cover_date": "2026-05-10",
    })  # -280
    # Deleting the short open should wipe the cover lot + reverse all cash.
    r = client.delete(f"/trades/{short['id']}")
    assert r.status_code == 200
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == start
    assert client.get(f"/users/{user_id}/positions").json() == []


def test_long_and_short_same_ticker_are_separate(client, user_id):
    client.post(f"/users/{user_id}/trades", json={
        "ticker": "NVDA", "trade_type": "Stock", "action": "buy",
        "quantity": 5, "price_per_unit": 100, "trade_date": "2026-05-01",
    })
    _open_short(client, user_id, ticker="NVDA", quantity=3, price_per_unit=110)
    positions = client.get(f"/users/{user_id}/positions").json()
    dirs = sorted(p["direction"] for p in positions if p["ticker"] == "NVDA")
    assert dirs == ["long", "short"]
