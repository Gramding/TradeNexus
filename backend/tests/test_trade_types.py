from conftest import make_trade


def test_default_types_seeded_and_ordered(client):
    types = client.get("/trade-types").json()
    names = [t["name"] for t in types]
    assert set(names) == {"Stock", "Call", "Put", "Other"}
    # is_default DESC, then name ASC -> all defaults, alphabetical
    assert names == sorted(names)
    assert all(t["is_default"] == 1 for t in types)
    assert all(t["usage_count"] == 0 for t in types)


def test_usage_count_reflects_trades(client, user_id):
    make_trade(client, user_id, trade_type="stock")
    make_trade(client, user_id, trade_type="stock")
    stock = next(t for t in client.get("/trade-types").json() if t["name"] == "Stock")
    assert stock["usage_count"] == 2


def test_create_validation(client):
    assert client.post("/trade-types", json={"name": "Bond"}).status_code == 201
    # case-insensitive duplicate
    assert client.post("/trade-types", json={"name": "bond"}).status_code == 409
    # empty / too long
    assert client.post("/trade-types", json={"name": "   "}).status_code == 422
    assert client.post("/trade-types", json={"name": "x" * 51}).status_code == 422


def test_create_is_not_default(client):
    created = client.post("/trade-types", json={"name": "Warrant"}).json()
    assert created["is_default"] == 0


def test_rename_cascades_to_trades(client, user_id):
    bond = client.post("/trade-types", json={"name": "Bond"}).json()
    make_trade(client, user_id, trade_type="bond")

    r = client.put(f"/trade-types/{bond['id']}", json={"name": "Bonds"})
    assert r.status_code == 200
    assert r.json()["trades_updated"] == 1

    rows = client.get(f"/users/{user_id}/trades").json()
    assert rows[0]["trade_type"] == "Bonds"


def test_delete_rules(client, user_id):
    types = {t["name"]: t for t in client.get("/trade-types").json()}

    # default cannot be deleted
    r = client.delete(f"/trade-types/{types['Stock']['id']}")
    assert r.status_code == 400
    assert "Default" in r.json()["detail"]

    # in-use custom type cannot be deleted
    bond = client.post("/trade-types", json={"name": "Bond"}).json()
    make_trade(client, user_id, trade_type="bond")
    r = client.delete(f"/trade-types/{bond['id']}")
    assert r.status_code == 400
    assert "Cannot delete" in r.json()["detail"]

    # unused custom type can be deleted
    spare = client.post("/trade-types", json={"name": "Spare"}).json()
    assert client.delete(f"/trade-types/{spare['id']}").status_code == 200
