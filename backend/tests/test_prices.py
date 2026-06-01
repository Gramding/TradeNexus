"""Price-cache tests. These never trigger a live network fetch: they only use the
cache_only read and the cache count/clear endpoints."""
import datetime

import db
from conftest import make_trade


def _seed_cache(symbol, price, hours_old=0, source="yahoo_finance"):
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = (now - datetime.timedelta(hours=hours_old)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO price_cache (symbol, price, currency, fetched_at, source) "
            "VALUES (?, ?, 'USD', ?, ?) "
            "ON CONFLICT(symbol, source) DO UPDATE SET price=excluded.price, fetched_at=excluded.fetched_at",
            (symbol.upper(), price, ts, source),
        )
        conn.commit()
    finally:
        conn.close()


def test_cache_only_hit_regardless_of_age(client):
    _seed_cache("ZZTEST", 189.45, hours_old=72)   # 3 days old
    r = client.get("/prices/ZZTEST", params={"cache_only": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["price"] == 189.45
    assert body["from_cache"] is True


def test_cache_only_miss_is_404_no_fetch(client):
    # No cache row and cache_only -> 404 without any live fetch.
    r = client.get("/prices/NOSUCH", params={"cache_only": "true"})
    assert r.status_code == 404


def test_positions_prices_expose_instrument_and_broker(client, user_id):
    # The positions/prices payload must carry instrument_id + the dominant broker_id
    # so the frontend can resolve a broker quote link. Seed the price cache so the
    # endpoint never makes a live fetch.
    bid = client.post("/brokers", json={
        "name": "Robinhood",
        "quote_url_template": "https://robinhood.com/stocks/{value}",
        "quote_url_key": "ticker",
    }).json()["id"]
    instr = client.post("/instruments", json={
        "symbol": "VOD.L", "ticker": "VOD", "name": "Vodafone", "isin": "GB00BH4HKS39",
    }).json()
    _seed_cache("VOD.L", 12.34)
    make_trade(client, user_id, ticker="VOD", broker_id=bid, instrument_id=instr["id"])

    positions = client.get(f"/users/{user_id}/positions/prices").json()
    assert len(positions) == 1
    assert positions[0]["instrument_id"] == instr["id"]
    assert positions[0]["broker_id"] == bid


def test_price_cache_count_and_clear(client):
    assert client.get("/settings/price-cache").json()["count"] == 0
    _seed_cache("AAA", 1)
    _seed_cache("BBB", 2)
    assert client.get("/settings/price-cache").json()["count"] == 2

    r = client.delete("/settings/price-cache")
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
    assert client.get("/settings/price-cache").json()["count"] == 0
