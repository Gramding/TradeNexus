from conftest import make_trade


def test_query_too_short(client, user_id):
    assert client.get("/search", params={"user_id": user_id, "q": "a"}).status_code == 400


def test_buckets_returned_and_typed(client, user_id):
    make_trade(client, user_id, ticker="AAPL", trade_type="stock")
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 100, "note": "payday"})

    data = client.get("/search", params={"user_id": user_id, "q": "AAPL"}).json()
    assert set(data.keys()) == {"trades", "positions", "cash_transactions"}
    assert len(data["trades"]) == 1
    assert data["trades"][0]["ticker"] == "AAPL"
    assert len(data["positions"]) == 1            # open buy -> appears as a position

    # cash note search
    data = client.get("/search", params={"user_id": user_id, "q": "payday"}).json()
    assert len(data["cash_transactions"]) == 1


def test_empty_arrays_never_null(client, user_id):
    data = client.get("/search", params={"user_id": user_id, "q": "zzqq"}).json()
    assert data == {"trades": [], "positions": [], "cash_transactions": []}


def test_scoped_to_user(client, user_id):
    make_trade(client, user_id, ticker="AAPL")
    other = client.post("/users", json={"name": "Other", "email": "o@example.com"}).json()["id"]
    data = client.get("/search", params={"user_id": other, "q": "AAPL"}).json()
    assert data["trades"] == []
