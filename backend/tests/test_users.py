def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_and_list_user(client):
    r = client.post("/users", json={"name": "Alice", "email": "alice@example.com"})
    assert r.status_code == 201
    created = r.json()
    assert created["name"] == "Alice"
    assert created["email"] == "alice@example.com"

    users = client.get("/users").json()
    assert any(u["email"] == "alice@example.com" for u in users)


def test_create_user_empty_name_rejected(client):
    r = client.post("/users", json={"name": "   ", "email": "x@example.com"})
    assert r.status_code == 422


def test_duplicate_email_conflict(client):
    client.post("/users", json={"name": "A", "email": "dup@example.com"})
    r = client.post("/users", json={"name": "B", "email": "dup@example.com"})
    assert r.status_code == 409


def test_delete_user(client, user_id):
    assert client.delete(f"/users/{user_id}").status_code == 200
    # trades for a missing user 404
    assert client.get(f"/users/{user_id}/trades").status_code == 404
