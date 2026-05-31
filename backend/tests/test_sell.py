from conftest import make_trade


def test_partial_then_full_sell(client, user_id):
    buy = make_trade(client, user_id, quantity=10, price_per_unit=100)

    # Sell 4 @ 120 -> realized pnl = (480) - (400) = 80 (no commissions)
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 4, "sell_price_per_unit": 120, "sell_date": "2026-05-10",
    })
    assert r.status_code == 201
    lot = r.json()
    assert lot["proceeds"] == 480
    assert lot["realized_pnl"] == 80

    # Buy lot is now partial with 6 remaining
    rows = client.get(f"/users/{user_id}/trades", params={"action": "buy"}).json()
    buy_row = next(t for t in rows if t["id"] == buy["id"])
    assert buy_row["remaining_quantity"] == 6
    assert buy_row["status"] == "partial"

    # Sell the remaining 6 -> closed
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 6, "sell_price_per_unit": 110, "sell_date": "2026-05-11",
    })
    assert r.status_code == 201
    rows = client.get(f"/users/{user_id}/trades", params={"action": "buy"}).json()
    buy_row = next(t for t in rows if t["id"] == buy["id"])
    assert buy_row["remaining_quantity"] == 0
    assert buy_row["status"] == "closed"


def test_oversell_rejected(client, user_id):
    buy = make_trade(client, user_id, quantity=5, price_per_unit=100)
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 6, "sell_price_per_unit": 100, "sell_date": "2026-05-10",
    })
    assert r.status_code == 400


def test_sell_adds_proceeds_to_cash(client, user_id):
    buy = make_trade(client, user_id, quantity=10, price_per_unit=100)  # cash -1000
    client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 10, "sell_price_per_unit": 150, "sell_date": "2026-05-10",
    })  # proceeds +1500
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == 500.0
