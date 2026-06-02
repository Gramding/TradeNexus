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
        "ticker": "AAPL", "trade_type": "warrant", "action": "buy",
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
    body = client.get(f"/users/{user_id}/trades", params={"trade_type": "stock"}).json()
    rows = body["trades"]
    assert len(rows) == 1
    assert body["total_count"] == 1
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


def test_filter_by_date_range(client, user_id):
    make_trade(client, user_id, ticker="AAA", trade_date="2024-06-15")
    make_trade(client, user_id, ticker="BBB", trade_date="2025-03-10")
    make_trade(client, user_id, ticker="CCC", trade_date="2026-01-20")

    # date_from + date_to (inclusive range) -> only the 2025 trade.
    body = client.get(f"/users/{user_id}/trades",
                      params={"date_from": "2025-01-01", "date_to": "2025-12-31"}).json()
    assert body["total_count"] == 1
    assert [t["ticker"] for t in body["trades"]] == ["BBB"]

    # date_from only -> 2025 and 2026 trades.
    body = client.get(f"/users/{user_id}/trades",
                      params={"date_from": "2025-01-01"}).json()
    assert body["total_count"] == 2

    # date_to is inclusive of the exact day.
    body = client.get(f"/users/{user_id}/trades",
                      params={"date_to": "2024-06-15"}).json()
    assert body["total_count"] == 1
    assert body["trades"][0]["ticker"] == "AAA"


def test_buy_cash_deduction_includes_commission(client, user_id):
    # The cash pool must reflect what the broker actually debits: gross + commission.
    bid = client.post("/brokers", json={
        "name": "BK", "commission_flat": 5, "commission_per_unit": 1,
    }).json()["id"]
    # 10 @ 100 -> gross 1000, commission 5 + 1*10 = 15, net 1015
    make_trade(client, user_id, quantity=10, price_per_unit=100, broker_id=bid)
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -1015.0


def test_edit_buy_resyncs_cash(client, user_id):
    buy = make_trade(client, user_id, quantity=10, price_per_unit=100)  # cash -1000
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -1000

    # Raising the quantity replaces (not duplicates) the deduction: 25 @ 100 = 2500.
    client.put(f"/trades/{buy['id']}", json={"quantity": 25})
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -2500

    # Lowering the price re-syncs again: 25 @ 80 = 2000.
    client.put(f"/trades/{buy['id']}", json={"price_per_unit": 80})
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -2000


def test_invalid_date_filter_rejected(client, user_id):
    assert client.get(f"/users/{user_id}/trades",
                      params={"date_from": "06/15/2024"}).status_code == 400
    assert client.get(f"/users/{user_id}/trades",
                      params={"date_to": "not-a-date"}).status_code == 400
