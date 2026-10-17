"""Editing and deleting trades keeps positions, realized P&L and the cash pool in
step; corporate events and caches follow the data they depend on."""
import sqlite3

import pytest

import db
import init_db


def _buy(client, uid, **kw):
    body = {"ticker": "AAPL", "trade_type": "Stock", "action": "buy", "quantity": 10,
            "price_per_unit": 100, "trade_date": "2026-05-01"}
    body.update(kw)
    r = client.post(f"/users/{uid}/trades", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _short(client, uid, **kw):
    return _buy(client, uid, action="sell", direction="short", **kw)


def _sell(client, trade_id, qty, price, date="2026-06-01"):
    r = client.post(f"/trades/{trade_id}/sell", json={
        "quantity_sold": qty, "sell_price_per_unit": price, "sell_date": date})
    assert r.status_code == 201, r.text
    return r.json()


def _cover(client, trade_id, qty, price, date="2026-06-01"):
    r = client.post(f"/trades/{trade_id}/cover", json={
        "quantity_covered": qty, "cover_price_per_unit": price, "cover_date": date})
    assert r.status_code == 201, r.text
    return r.json()


def _cash(client, uid):
    return client.get(f"/users/{uid}/cash").json()["balance"]


def _trades(client, uid):
    return client.get(f"/users/{uid}/trades").json()


def _positions(client, uid):
    return client.get(f"/users/{uid}/positions").json()


def _close_row(client, uid):
    return next(t for t in _trades(client, uid)["trades"] if t["is_close"])


@pytest.fixture
def funded(client, user_id):
    client.post(f"/users/{user_id}/cash/deposit", json={"amount": 100000})
    return user_id


# ── Editing ──────────────────────────────────────────────────────────────────

def test_edit_quantity_moves_open_quantity_and_cash(client, funded):
    t = _buy(client, funded)
    r = client.put(f"/trades/{t['id']}", json={"quantity": 20})
    assert r.status_code == 200, r.text
    assert _positions(client, funded)[0]["total_remaining_quantity"] == 20
    assert _cash(client, funded) == pytest.approx(100000 - 2000)


def test_edit_cannot_switch_buy_and_sell(client, funded):
    t = _buy(client, funded)
    r = client.put(f"/trades/{t['id']}", json={"action": "sell"})
    assert r.status_code == 422
    assert len(_positions(client, funded)) == 1


def test_edit_ticker_is_normalized(client, funded):
    t = _buy(client, funded)
    client.put(f"/trades/{t['id']}", json={"ticker": " aapl "})
    _buy(client, funded)
    assert len(_positions(client, funded)) == 1


def test_editing_close_row_note_keeps_cash(client, funded):
    t = _buy(client, funded)
    _sell(client, t["id"], 10, 110)
    before = _cash(client, funded)
    close = _close_row(client, funded)
    r = client.put(f"/trades/{close['id']}", json={"notes": "took profit"})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "took profit"
    assert _cash(client, funded) == pytest.approx(before)


def test_editing_close_row_numbers_is_refused(client, funded):
    t = _buy(client, funded)
    _sell(client, t["id"], 10, 110)
    close = _close_row(client, funded)
    r = client.put(f"/trades/{close['id']}", json={"price_per_unit": 120})
    assert r.status_code == 409


def test_edit_form_resend_of_unchanged_close_row_is_allowed(client, funded):
    # The edit form sends every field; unchanged values must not count as edits.
    t = _buy(client, funded)
    _sell(client, t["id"], 10, 110)
    close = _close_row(client, funded)
    r = client.put(f"/trades/{close['id']}", json={
        "ticker": close["ticker"], "trade_type": close["trade_type"], "action": close["action"],
        "quantity": close["quantity"], "price_per_unit": close["price_per_unit"],
        "trade_date": close["trade_date"] + "T00:00:00", "notes": "n", "commission": close["commission"],
    })
    assert r.status_code == 200, r.text


def test_position_with_sales_locks_economic_fields(client, funded):
    t = _buy(client, funded)
    _sell(client, t["id"], 4, 110)
    assert client.put(f"/trades/{t['id']}", json={"quantity": 20}).status_code == 409
    # Notes and the date can still change.
    r = client.put(f"/trades/{t['id']}", json={"notes": "core holding", "trade_date": "2026-04-30"})
    assert r.status_code == 200, r.text


def test_edit_keeps_bond_accrued_interest_in_cash(client, funded):
    t = _buy(client, funded, ticker="T-2030", trade_type="Bond", quantity=1, price_per_unit=100,
             accrued_interest=12.5)
    after_buy = _cash(client, funded)
    client.put(f"/trades/{t['id']}", json={"notes": "edited"})
    assert _cash(client, funded) == pytest.approx(after_buy)


def test_commission_null_on_edit_reverts_to_broker_commission(client, funded):
    br = client.post("/brokers", json={"name": "Flat5", "commission_flat": 5}).json()
    t = _buy(client, funded, broker_id=br["id"], commission=9)
    r = client.put(f"/trades/{t['id']}", json={"commission": None})
    assert r.json()["commission"] == 5


# ── Deleting ─────────────────────────────────────────────────────────────────

def test_delete_close_row_undoes_the_sale(client, funded):
    t = _buy(client, funded)
    _sell(client, t["id"], 5, 110)
    before_sale_cash = 100000 - 1000
    close = _close_row(client, funded)
    assert client.delete(f"/trades/{close['id']}").status_code == 200
    pos = _positions(client, funded)[0]
    assert pos["total_remaining_quantity"] == 10
    assert client.get(f"/users/{funded}/stats").json()["net_realized_pnl"] == 0
    assert _cash(client, funded) == pytest.approx(before_sale_cash)
    assert [x["status"] for x in _trades(client, funded)["trades"]] == ["open"]


def test_delete_cover_row_undoes_the_cover(client, funded):
    s = _short(client, funded, ticker="TSLA")
    _cover(client, s["id"], 4, 90)
    close = _close_row(client, funded)
    client.delete(f"/trades/{close['id']}")
    pos = _positions(client, funded)[0]
    assert pos["direction"] == "short" and pos["total_remaining_quantity"] == 10
    assert _cash(client, funded) == pytest.approx(100000 + 1000)


def test_delete_opening_trade_removes_its_sales(client, funded):
    t = _buy(client, funded)
    _sell(client, t["id"], 5, 110)
    client.delete(f"/trades/{t['id']}")
    assert _trades(client, funded)["trades"] == []
    assert _cash(client, funded) == pytest.approx(100000)


def test_delete_only_touches_its_own_cash_rows(client, funded):
    # A cover's sell lot and a long trade can share an id number; deleting the
    # trade must not remove the cover's cash row.
    s = _short(client, funded, ticker="BBB")      # trade 1
    long_ = _buy(client, funded, ticker="AAA")    # trade 2
    _cover(client, s["id"], 1, 100)               # sell lot 1
    _cover(client, s["id"], 1, 100)               # sell lot 2 (same number as the long)
    before = _cash(client, funded)
    client.delete(f"/trades/{long_['id']}")
    assert _cash(client, funded) - before == pytest.approx(1000)


def test_delete_does_not_touch_other_users(client, funded):
    other = client.post("/users", json={"name": "O", "email": "o@x.io"}).json()["id"]
    client.post(f"/users/{other}/cash/deposit", json={"amount": 5000})
    s = _short(client, other, ticker="ZZZ")       # trade 1 (other user)
    t = _buy(client, funded)                      # trade 2 (funded user)
    _cover(client, s["id"], 1, 100)               # other user's sell lot 1
    _cover(client, s["id"], 1, 100)               # other user's sell lot 2, same number as trade 2
    client.delete(f"/trades/{t['id']}")
    assert _cash(client, other) == pytest.approx(5000 + 1000 - 200)


def test_undo_blocked_after_later_split(client, funded):
    inst = client.post("/instruments", json={"symbol": "NVDA", "ticker": "NVDA", "asset_class": "stock"}).json()
    t = _buy(client, funded, ticker="NVDA", instrument_id=inst["id"])
    _sell(client, t["id"], 5, 110, date="2026-05-05")
    client.post(f"/users/{funded}/events", json={"event_type": "split", "event_date": "2026-05-10",
                                                 "instrument_id": inst["id"], "ratio": 2})
    close = _close_row(client, funded)
    assert client.delete(f"/trades/{close['id']}").status_code == 409


# ── Events ───────────────────────────────────────────────────────────────────

def test_split_scales_open_shorts_too(client, funded):
    inst = client.post("/instruments", json={"symbol": "NVDA", "ticker": "NVDA", "asset_class": "stock"}).json()
    _buy(client, funded, ticker="NVDA", instrument_id=inst["id"])
    _short(client, funded, ticker="NVDA", instrument_id=inst["id"])
    client.post(f"/users/{funded}/events", json={"event_type": "split", "event_date": "2026-05-10",
                                                 "instrument_id": inst["id"], "ratio": 10})
    qty = {p["direction"]: p["total_remaining_quantity"] for p in _positions(client, funded)}
    assert qty == {"long": 100, "short": 100}


def test_dividend_uses_holdings_on_its_date(client, funded):
    inst = client.post("/instruments", json={"symbol": "KO", "ticker": "KO", "asset_class": "stock"}).json()
    t = _buy(client, funded, ticker="KO", instrument_id=inst["id"], trade_date="2026-01-01")
    _sell(client, t["id"], 10, 100, date="2026-06-01")
    before = _cash(client, funded)
    client.post(f"/users/{funded}/events", json={"event_type": "dividend", "event_date": "2026-03-01",
                                                 "instrument_id": inst["id"], "amount": 1})
    assert _cash(client, funded) - before == pytest.approx(10)


def test_dividend_backs_out_later_splits(client, funded):
    inst = client.post("/instruments", json={"symbol": "KO", "ticker": "KO", "asset_class": "stock"}).json()
    _buy(client, funded, ticker="KO", instrument_id=inst["id"], trade_date="2026-01-01")
    client.post(f"/users/{funded}/events", json={"event_type": "split", "event_date": "2026-04-01",
                                                 "instrument_id": inst["id"], "ratio": 2})
    before = _cash(client, funded)
    client.post(f"/users/{funded}/events", json={"event_type": "dividend", "event_date": "2026-03-01",
                                                 "instrument_id": inst["id"], "amount": 1})
    assert _cash(client, funded) - before == pytest.approx(10)   # 10 pre-split shares, not 20


def test_split_delete_blocked_by_later_sale(client, funded):
    inst = client.post("/instruments", json={"symbol": "NVDA", "ticker": "NVDA", "asset_class": "stock"}).json()
    t = _buy(client, funded, ticker="NVDA", instrument_id=inst["id"])
    ev = client.post(f"/users/{funded}/events", json={"event_type": "split", "event_date": "2026-05-10",
                                                      "instrument_id": inst["id"], "ratio": 2}).json()
    _sell(client, t["id"], 5, 60, date="2026-05-20")
    assert client.delete(f"/events/{ev['id']}").status_code == 409


# ── Commission currency ──────────────────────────────────────────────────────

def test_broker_commission_converted_into_trade_currency(client, funded):
    br = client.post("/brokers", json={"name": "IB", "commission_flat": 5, "commission_currency": "USD"}).json()
    t = _buy(client, funded, ticker="SAP", trade_currency="EUR", fx_rate=1.25, broker_id=br["id"])
    assert t["commission"] == pytest.approx(4.0)


def test_unconvertible_commission_is_refused(client, funded):
    br = client.post("/brokers", json={"name": "CH", "commission_flat": 5, "commission_currency": "CHF"}).json()
    r = client.post(f"/users/{funded}/trades", json={
        "ticker": "SAP", "trade_type": "Stock", "action": "buy", "quantity": 1, "price_per_unit": 1,
        "trade_date": "2026-05-01", "trade_currency": "EUR", "fx_rate": 1.1, "broker_id": br["id"]})
    assert r.status_code == 503


# ── Caches ───────────────────────────────────────────────────────────────────

def test_trade_count_updates_immediately(client, funded):
    _buy(client, funded)
    assert _trades(client, funded)["total_count"] == 1
    _buy(client, funded)
    assert _trades(client, funded)["total_count"] == 2


def test_stats_follow_trade_type_rename(client, funded):
    _buy(client, funded)
    client.get(f"/users/{funded}/stats")
    tt = next(x for x in client.get("/trade-types").json() if x["name"] == "Stock")
    client.put(f"/trade-types/{tt['id']}", json={"name": "Equity", "color": tt.get("color")})
    names = [x["trade_type"] for x in client.get(f"/users/{funded}/stats").json()["by_trade_type"]]
    assert names == ["Equity"]


# ── Migration back-fill for databases written before the links existed ─────

def test_backfill_links_close_rows_and_resolves_id_collisions(client, funded):
    s = _short(client, funded, ticker="BBB")
    long_ = _buy(client, funded, ticker="AAA")
    _cover(client, s["id"], 1, 100)
    _cover(client, s["id"], 1, 100)            # sell lot id == long trade id
    t = _buy(client, funded, ticker="CCC")
    _sell(client, t["id"], 2, 120)

    # Wipe the new columns to look like an old database, then re-run the back-fill.
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute("UPDATE trades SET sell_lot_id = NULL")
        conn.execute("UPDATE cash_pool SET reference_kind = NULL")
        cur = conn.cursor()
        init_db._backfill_close_row_links(cur)
        init_db._backfill_cash_reference_kind(cur)
        conn.commit()
        unlinked = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE sell_lot_id IS NULL AND "
            "((action = 'sell' AND direction = 'long') OR (action = 'buy' AND direction = 'short'))"
        ).fetchone()[0]
        unclassified = conn.execute(
            "SELECT COUNT(*) FROM cash_pool WHERE reference_id IS NOT NULL AND reference_kind IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    assert unlinked == 0
    assert unclassified == 0

    before = _cash(client, funded)
    client.delete(f"/trades/{long_['id']}")
    assert _cash(client, funded) - before == pytest.approx(1000)
