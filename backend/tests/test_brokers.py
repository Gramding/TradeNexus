def test_broker_crud(client):
    r = client.post("/brokers", json={
        "name": "Fidelity", "commission_flat": 1.0, "commission_per_unit": 0.5,
    })
    assert r.status_code == 201
    bid = r.json()["id"]

    assert any(b["name"] == "Fidelity" for b in client.get("/brokers").json())

    r = client.put(f"/brokers/{bid}", json={"name": "Fidelity Inc"})
    assert r.status_code == 200
    assert r.json()["name"] == "Fidelity Inc"

    assert client.delete(f"/brokers/{bid}").status_code == 200


def test_broker_name_required(client):
    assert client.post("/brokers", json={"name": "   "}).status_code == 422


def test_invalid_color_rejected(client):
    r = client.post("/brokers", json={"name": "X", "color": "red"})
    assert r.status_code == 422


def test_commission_applied_to_trade(client):
    bid = client.post("/brokers", json={
        "name": "B", "commission_flat": 5, "commission_per_unit": 1,
    }).json()["id"]
    uid = client.post("/users", json={"name": "U", "email": "u@example.com"}).json()["id"]

    # 10 units -> commission = 5 + 1*10 = 15; buy net = 1000 + 15
    t = client.post(f"/users/{uid}/trades", json={
        "ticker": "AAPL", "trade_type": "stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-05-01",
        "broker_id": bid,
    }).json()
    assert t["commission"] == 15.0
    assert t["net_total_value"] == 1015.0
