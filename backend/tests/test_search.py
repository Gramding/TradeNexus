from conftest import make_trade


def test_query_too_short(client, user_id):
    assert client.get("/search", params={"user_id": user_id, "q": "a"}).status_code == 400


def test_buckets_returned_and_typed(client, user_id):
    make_trade(client, user_id, ticker="AAPL", trade_type="stock")
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 100, "note": "payday"})

    data = client.get("/search", params={"user_id": user_id, "q": "AAPL"}).json()
    assert set(data.keys()) == {"trades", "positions", "cash_transactions"}
    # Each bucket is {results, has_more, next_cursor}.
    assert set(data["trades"].keys()) == {"results", "has_more", "next_cursor"}
    assert len(data["trades"]["results"]) == 1
    assert data["trades"]["has_more"] is False
    assert data["trades"]["next_cursor"] is None
    assert data["trades"]["results"][0]["ticker"] == "AAPL"
    assert len(data["positions"]["results"]) == 1   # open buy -> appears as a position

    # cash note search
    data = client.get("/search", params={"user_id": user_id, "q": "payday"}).json()
    assert len(data["cash_transactions"]["results"]) == 1


def test_empty_arrays_never_null(client, user_id):
    data = client.get("/search", params={"user_id": user_id, "q": "zzqq"}).json()
    assert set(data.keys()) == {"trades", "positions", "cash_transactions"}
    for bucket in data.values():
        assert bucket == {"results": [], "has_more": False, "next_cursor": None}


def test_scoped_to_user(client, user_id):
    make_trade(client, user_id, ticker="AAPL")
    other = client.post("/users", json={"name": "Other", "email": "o@example.com"}).json()["id"]
    data = client.get("/search", params={"user_id": other, "q": "AAPL"}).json()
    assert data["trades"]["results"] == []


def test_type_param_returns_single_bucket(client, user_id):
    make_trade(client, user_id, ticker="AAPL")
    data = client.get(
        "/search", params={"user_id": user_id, "q": "AAPL", "type": "trades"}
    ).json()
    assert set(data.keys()) == {"trades"}
    assert data["trades"]["results"][0]["ticker"] == "AAPL"


def test_type_param_paginates_bucket(client, user_id):
    # 25 matching trades -> first page caps at 20 with a cursor to load the rest.
    for i in range(25):
        make_trade(client, user_id, ticker="AAPL", trade_date=f"2026-01-{i + 1:02d}")
    first = client.get(
        "/search", params={"user_id": user_id, "q": "AAPL", "type": "trades"}
    ).json()["trades"]
    assert len(first["results"]) == 20
    assert first["has_more"] is True
    assert first["next_cursor"] is not None

    second = client.get(
        "/search",
        params={"user_id": user_id, "q": "AAPL", "type": "trades", "cursor": first["next_cursor"]},
    ).json()["trades"]
    assert len(second["results"]) == 5
    assert second["has_more"] is False
    first_ids = {t["trade_id"] for t in first["results"]}
    second_ids = {t["trade_id"] for t in second["results"]}
    assert first_ids.isdisjoint(second_ids)


def test_bad_type_rejected(client, user_id):
    r = client.get("/search", params={"user_id": user_id, "q": "AAPL", "type": "bogus"})
    assert r.status_code == 422
