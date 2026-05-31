"""Price-cache tests. These never trigger a live network fetch: they only use the
cache_only read and the cache count/clear endpoints."""
import datetime

import db


def _seed_cache(ticker, price, hours_old=0, source="yahoo_finance"):
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = (now - datetime.timedelta(hours=hours_old)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO price_cache (ticker, price, currency, fetched_at, source) "
            "VALUES (?, ?, 'USD', ?, ?) "
            "ON CONFLICT(ticker, source) DO UPDATE SET price=excluded.price, fetched_at=excluded.fetched_at",
            (ticker.upper(), price, ts, source),
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


def test_price_cache_count_and_clear(client):
    assert client.get("/settings/price-cache").json()["count"] == 0
    _seed_cache("AAA", 1)
    _seed_cache("BBB", 2)
    assert client.get("/settings/price-cache").json()["count"] == 2

    r = client.delete("/settings/price-cache")
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
    assert client.get("/settings/price-cache").json()["count"] == 0
