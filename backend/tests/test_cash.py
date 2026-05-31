def test_deposit_and_withdraw(client, user_id):
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == 0.0

    r = client.post(f"/users/{user_id}/cash/deposit", json={"amount": 1000, "note": "seed"})
    assert r.status_code == 201
    assert r.json()["balance"] == 1000.0

    r = client.post(f"/users/{user_id}/cash/withdraw", json={"amount": 300})
    assert r.status_code == 201
    assert r.json()["balance"] == 700.0


def test_withdraw_over_balance_rejected(client, user_id):
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 100})
    r = client.post(f"/users/{user_id}/cash/withdraw", json={"amount": 500})
    assert r.status_code == 400


def test_non_positive_amounts_rejected(client, user_id):
    assert client.post(f"/users/{user_id}/cash/deposit", json={"amount": 0}).status_code == 422
    assert client.post(f"/users/{user_id}/cash/deposit", json={"amount": -5}).status_code == 422


def test_cash_transactions_listed(client, user_id):
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 50, "note": "hello"})
    data = client.get(f"/users/{user_id}/cash").json()
    assert data["balance"] == 50.0
    assert data["total_count"] == 1
    assert data["has_more"] is False
    assert data["next_cursor"] is None
    assert any(tx["transaction_type"] == "deposit" and tx["note"] == "hello"
               for tx in data["transactions"])


def test_cash_pagination_and_balance(client, user_id):
    # 60 deposits -> two pages at limit 50; balance reflects ALL rows, every page.
    for i in range(60):
        client.post(f"/users/{user_id}/cash/deposit", json={"amount": 10, "note": f"d{i}"})

    first = client.get(f"/users/{user_id}/cash").json()
    assert len(first["transactions"]) == 50
    assert first["total_count"] == 60
    assert first["has_more"] is True
    assert first["next_cursor"] is not None
    assert first["balance"] == 600.0

    second = client.get(
        f"/users/{user_id}/cash", params={"cursor": first["next_cursor"]}
    ).json()
    assert len(second["transactions"]) == 10
    assert second["has_more"] is False
    assert second["balance"] == 600.0   # full balance, not just this page
    first_ids = {tx["id"] for tx in first["transactions"]}
    second_ids = {tx["id"] for tx in second["transactions"]}
    assert first_ids.isdisjoint(second_ids)


def test_cash_filter_by_transaction_type(client, user_id):
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 100})
    client.post(f"/users/{user_id}/cash/withdraw", json={"amount": 30})
    data = client.get(
        f"/users/{user_id}/cash", params={"transaction_type": "deposit"}
    ).json()
    assert data["total_count"] == 1
    assert all(tx["transaction_type"] == "deposit" for tx in data["transactions"])
    assert data["balance"] == 70.0   # balance ignores the filter
