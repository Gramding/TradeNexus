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
    rows = client.get(f"/users/{user_id}/trades", params={"action": "buy"}).json()["trades"]
    buy_row = next(t for t in rows if t["id"] == buy["id"])
    assert buy_row["remaining_quantity"] == 6
    assert buy_row["status"] == "partial"

    # Sell the remaining 6 -> closed
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 6, "sell_price_per_unit": 110, "sell_date": "2026-05-11",
    })
    assert r.status_code == 201
    rows = client.get(f"/users/{user_id}/trades", params={"action": "buy"}).json()["trades"]
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


def test_sell_cash_credit_nets_commission(client, user_id):
    bid = client.post("/brokers", json={
        "name": "BK", "commission_flat": 0, "commission_per_unit": 1,
    }).json()["id"]
    # Buy 10 @ 100: commission 1*10 = 10 -> net buy 1010, cash -1010.
    buy = make_trade(client, user_id, quantity=10, price_per_unit=100, broker_id=bid)
    # Sell 10 @ 150: proceeds 1500, sell commission 1*10 = 10 -> net credit 1490.
    client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 10, "sell_price_per_unit": 150, "sell_date": "2026-05-10",
    })
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == -1010 + 1490  # 480


def test_delete_buy_with_sells_cascades_and_reverses_cash(client, user_id):
    # Fund the pool, buy, then sell part of the position.
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 10_000})
    buy = make_trade(client, user_id, quantity=10, price_per_unit=100)   # -1000 cash
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 4, "sell_price_per_unit": 120, "sell_date": "2026-05-10",
    })
    assert r.status_code == 201

    bal_before = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal_before == 10_000 - 1000 + 480   # deposit - buy + proceeds

    # Deleting the buy must succeed (previously failed with a FK error) ...
    assert client.delete(f"/trades/{buy['id']}").status_code == 200

    # ... the buy is gone, its sell lots are gone, and the cash effects are reversed.
    trades = client.get(f"/users/{user_id}/trades").json()["trades"]
    assert all(t["id"] != buy["id"] for t in trades)
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == 10_000  # back to deposit only


def test_delete_buy_without_sells_reverses_deduction(client, user_id):
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 5_000})
    buy = make_trade(client, user_id, quantity=2, price_per_unit=250)      # -500 cash
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == 4_500
    assert client.delete(f"/trades/{buy['id']}").status_code == 200
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == 5_000  # deduction reversed
