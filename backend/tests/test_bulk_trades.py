"""Tests for the mass / bulk Add Trade endpoint (POST /trades/bulk)."""


def _make_users(client, n):
    ids = []
    for i in range(n):
        r = client.post("/users", json={"name": f"U{i}", "email": f"u{i}@example.com"})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


def _bulk_body(user_ids, **overrides):
    body = {
        "user_ids": user_ids,
        "ticker": "AAPL",
        "trade_type": "stock",
        "action": "buy",
        "quantity": 10,
        "price_per_unit": 100,
        "trade_date": "2026-05-01",
    }
    body.update(overrides)
    return body


def test_bulk_creates_trade_for_each_user(client):
    a, b, c = _make_users(client, 3)
    r = client.post("/trades/bulk", json=_bulk_body([a, b, c]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["count"] == 3
    assert {item["user_id"] for item in data["created"]} == {a, b, c}

    # Every selected user gets exactly one trade and its buy cash deduction.
    for uid in (a, b, c):
        trades = client.get(f"/users/{uid}/trades").json()["trades"]
        assert len(trades) == 1
        assert trades[0]["ticker"] == "AAPL"
        assert client.get(f"/users/{uid}/cash").json()["balance"] == -1000.0


def test_bulk_is_all_or_nothing_on_bad_user(client):
    a, b = _make_users(client, 2)
    missing = 999999
    r = client.post("/trades/bulk", json=_bulk_body([a, missing, b]))
    assert r.status_code == 404, r.text

    # Nothing was written for the valid users — the whole batch rolled back.
    for uid in (a, b):
        assert client.get(f"/users/{uid}/trades").json()["trades"] == []


def test_bulk_requires_at_least_one_user(client):
    r = client.post("/trades/bulk", json=_bulk_body([]))
    assert r.status_code == 422


def test_bulk_dedupes_repeated_user_ids(client):
    (a,) = _make_users(client, 1)
    r = client.post("/trades/bulk", json=_bulk_body([a, a, a]))
    assert r.status_code == 201, r.text
    assert r.json()["count"] == 1
    assert len(client.get(f"/users/{a}/trades").json()["trades"]) == 1


def test_bulk_invalid_trade_type_writes_nothing(client):
    a, b = _make_users(client, 2)
    r = client.post("/trades/bulk", json=_bulk_body([a, b], trade_type="NotAType"))
    assert r.status_code == 400, r.text
    for uid in (a, b):
        assert client.get(f"/users/{uid}/trades").json()["trades"] == []
