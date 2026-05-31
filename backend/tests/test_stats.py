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
