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
    assert any(tx["transaction_type"] == "deposit" and tx["note"] == "hello"
               for tx in data["transactions"])
