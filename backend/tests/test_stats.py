import datetime

from conftest import make_trade


def test_stats_basic_fields(client, user_id):
    make_trade(client, user_id, quantity=10, price_per_unit=100)   # buy 1000
    s = client.get(f"/users/{user_id}/stats").json()
    for key in ("total_trades", "buy_volume", "sell_volume", "net_position",
                "total_commissions", "net_realized_pnl", "this_fiscal_year_volume",
                "fiscal_year_start", "by_trade_type", "monthly_volume"):
        assert key in s
    assert s["total_trades"] == 1
    assert s["buy_volume"] == 1000.0


def test_fiscal_year_window(client, user_id):
    today = datetime.date.today()
    in_window  = f"{today.year}-01-15"        # inside [Y-01-01, Y+1-01-01)
    out_window = f"{today.year - 1}-12-15"    # before this fiscal year

    make_trade(client, user_id, trade_date=in_window,  quantity=10, price_per_unit=100)   # 1000
    make_trade(client, user_id, trade_date=out_window, quantity=5,  price_per_unit=100)   # 500

    # Default fiscal start = January (from seeded settings)
    s = client.get(f"/users/{user_id}/stats").json()
    assert s["fiscal_year_start"] == f"{today.year}-01-01"
    assert s["this_fiscal_year_volume"] == 1000.0


def test_fiscal_year_param_out_of_range(client, user_id):
    assert client.get(f"/users/{user_id}/stats",
                      params={"fiscal_year_start_month": 13}).status_code == 422
    assert client.get(f"/users/{user_id}/stats",
                      params={"fiscal_year_start_month": 0}).status_code == 422


def test_stats_has_last_computed_at(client, user_id):
    s = client.get(f"/users/{user_id}/stats").json()
    assert "last_computed_at" in s and s["last_computed_at"]


def test_stats_cache_invalidated_on_write(client, user_id):
    make_trade(client, user_id, quantity=10, price_per_unit=100)   # buy 1000
    first = client.get(f"/users/{user_id}/stats").json()
    assert first["total_trades"] == 1

    # A second read is served from cache: identical, same timestamp.
    cached = client.get(f"/users/{user_id}/stats").json()
    assert cached["last_computed_at"] == first["last_computed_at"]
    assert cached["total_trades"] == 1

    # A write invalidates -> recomputed with the new trade reflected.
    make_trade(client, user_id, quantity=5, price_per_unit=100)    # buy 500
    after = client.get(f"/users/{user_id}/stats").json()
    assert after["total_trades"] == 2
    assert after["buy_volume"] == 1500.0


def test_growth_date_from_filtering(client, user_id):
    import datetime
    today = datetime.date.today()
    old = (today - datetime.timedelta(days=400)).isoformat()   # outside default year
    recent = (today - datetime.timedelta(days=10)).isoformat()
    make_trade(client, user_id, trade_date=old)
    make_trade(client, user_id, trade_date=recent)

    # Default: last year only -> the 400-day-old point is excluded.
    default = client.get(f"/users/{user_id}/stats/growth").json()
    assert all(pt["date"] >= (today - datetime.timedelta(days=365)).isoformat()
               for pt in default)
    assert any(pt["date"] == recent for pt in default)
    assert all(pt["date"] != old for pt in default)

    # "All" (empty string) -> everything, including the old point.
    all_pts = client.get(f"/users/{user_id}/stats/growth", params={"date_from": ""}).json()
    assert any(pt["date"] == old for pt in all_pts)

    # Explicit cutoff between the two events.
    cutoff = (today - datetime.timedelta(days=30)).isoformat()
    sliced = client.get(f"/users/{user_id}/stats/growth", params={"date_from": cutoff}).json()
    assert all(pt["date"] >= cutoff for pt in sliced)


def test_growth_bad_date_from(client, user_id):
    r = client.get(f"/users/{user_id}/stats/growth", params={"date_from": "not-a-date"})
    assert r.status_code == 400
