from conftest import make_trade


def test_create_trade_normalizes_type_and_defaults(client, user_id):
    t = make_trade(client, user_id, trade_type="stock", quantity=10, price_per_unit=100)
    assert t["trade_type"] == "Stock"          # lowercase input -> canonical name
    assert t["action"] == "buy"
    assert t["status"] == "open"
    assert t["remaining_quantity"] == 10
    assert t["total_value"] == 1000


def test_buy_deducts_cash(client, user_id):
    make_trade(client, user_id, quantity=5, price_per_unit=20)   # total 100
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == -100.0


def test_unknown_trade_type_rejected(client, user_id):
    r = client.post(f"/users/{user_id}/trades", json={
        "ticker": "AAPL", "trade_type": "bond", "action": "buy",
        "quantity": 1, "price_per_unit": 1, "trade_date": "2026-05-01",
    })
    assert r.status_code == 400
    assert r.json()["detail"] == "Unknown trade type"


def test_invalid_action_and_quantity(client, user_id):
    base = {"ticker": "AAPL", "trade_type": "stock", "trade_date": "2026-05-01"}
    r = client.post(f"/users/{user_id}/trades", json={**base, "action": "hold", "quantity": 1, "price_per_unit": 1})
    assert r.status_code == 422
    r = client.post(f"/users/{user_id}/trades", json={**base, "action": "buy", "quantity": 0, "price_per_unit": 1})
    assert r.status_code == 422


def test_filter_by_trade_type_case_insensitive(client, user_id):
    make_trade(client, user_id, ticker="AAPL", trade_type="stock")
    make_trade(client, user_id, ticker="SPY", trade_type="call")
    rows = client.get(f"/users/{user_id}/trades", params={"trade_type": "stock"}).json()
    assert len(rows) == 1
    assert rows[0]["trade_type"] == "Stock"


def test_update_trade_type(client, user_id):
    t = make_trade(client, user_id, trade_type="stock")
    r = client.put(f"/trades/{t['id']}", json={"trade_type": "put"})
    assert r.status_code == 200
    assert r.json()["trade_type"] == "Put"

    r = client.put(f"/trades/{t['id']}", json={"trade_type": "bogus"})
    assert r.status_code == 400


def test_delete_trade(client, user_id):
    t = make_trade(client, user_id)
    assert client.delete(f"/trades/{t['id']}").status_code == 200
    assert client.delete(f"/trades/{t['id']}").status_code == 404
