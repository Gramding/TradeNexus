def test_defaults_present(client):
    s = client.get("/settings").json()
    assert s["currency"] == "USD"
    assert s["date_format"] == "MM/DD/YYYY"
    assert s["decimal_separator"] == "."
    assert s["fiscal_year_start_month"] == "1"


def test_partial_update(client):
    r = client.put("/settings", json={"display_name": "Grace"})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Grace"
    # other keys untouched
    assert client.get("/settings").json()["currency"] == "USD"


def test_validation_rejects_bad_values(client):
    assert client.put("/settings", json={"fiscal_year_start_month": 13}).status_code == 400
    assert client.put("/settings", json={"price_refresh_interval_minutes": 7}).status_code == 400
    assert client.put("/settings", json={"decimal_separator": ";"}).status_code == 400
    assert client.put("/settings", json={"date_format": "DD-MM-YY"}).status_code == 400


def test_unknown_key_rejected(client):
    assert client.put("/settings", json={"bogus_key": "x"}).status_code == 400


def test_valid_enumerations_accepted(client):
    r = client.put("/settings", json={
        "price_refresh_interval_minutes": 30,
        "fiscal_year_start_month": 4,
        "decimal_separator": ",",
        "date_format": "YYYY-MM-DD",
    })
    assert r.status_code == 200
    s = r.json()
    assert s["price_refresh_interval_minutes"] == "30"
    assert s["fiscal_year_start_month"] == "4"
    assert s["decimal_separator"] == ","
    assert s["date_format"] == "YYYY-MM-DD"
