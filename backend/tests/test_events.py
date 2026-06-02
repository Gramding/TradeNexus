"""Phase 5: dividends, splits, interest, fees.

Events feed into the cash pool (in base currency) or, in the case of splits,
retroactively adjust open lots. These tests pin per-type math, multi-currency
conversion, split invariants, and stats fields.
"""


def _make_instr(client, **overrides):
    body = {"symbol": "AAPL", "ticker": "AAPL", "asset_class": "stock", "currency": "USD"}
    body.update(overrides)
    r = client.post("/instruments", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _buy(client, uid, instr_id, **overrides):
    body = {
        "ticker": "AAPL", "trade_type": "Stock", "action": "buy",
        "quantity": 10, "price_per_unit": 100, "trade_date": "2026-04-01",
        "instrument_id": instr_id,
    }
    body.update(overrides)
    r = client.post(f"/users/{uid}/trades", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── dividends ────────────────────────────────────────────────────────────────

def test_dividend_credits_per_share(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"])  # 10 shares, cash -1000
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "dividend", "instrument_id": inst["id"],
        "event_date": "2026-05-15", "amount": 0.50,
    })
    assert r.status_code == 201, r.text
    # 0.50 * 10 shares = 5.00 credit
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -995.0


def test_dividend_pays_only_on_shares_held_on_date(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"], trade_date="2026-06-01")  # after the record date
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "dividend", "instrument_id": inst["id"],
        "event_date": "2026-05-15", "amount": 0.50,
    })
    assert r.status_code == 201
    # No eligible shares -> 0.00 dividend
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -1000.0


def test_dividend_in_foreign_currency_converts(client, user_id):
    inst = _make_instr(client, symbol="SAP.DE", ticker="SAP", currency="EUR")
    _buy(client, user_id, inst["id"], trade_currency="EUR", fx_rate=1.10)
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "dividend", "instrument_id": inst["id"],
        "event_date": "2026-05-15", "amount": 1.00, "fx_rate": 1.20,
    })
    assert r.status_code == 201
    # 1.00 EUR * 10 sh * 1.20 = 12.00 USD; cash = -1100 + 12 = -1088
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -1088.0


# ── splits ───────────────────────────────────────────────────────────────────

def test_split_2_for_1_doubles_qty_halves_price(client, user_id):
    inst = _make_instr(client)
    t = _buy(client, user_id, inst["id"], quantity=10, price_per_unit=200)  # basis 2000
    client.post(f"/users/{user_id}/events", json={
        "event_type": "split", "instrument_id": inst["id"],
        "event_date": "2026-05-01", "ratio": 2.0,
    })
    pos = client.get(f"/users/{user_id}/positions").json()[0]
    assert pos["total_remaining_quantity"] == 20.0
    assert pos["avg_cost_per_unit"] == 100.0
    assert pos["total_cost_basis"] == 2000.0  # invariant


def test_reverse_split_halves_qty_doubles_price(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"], quantity=10, price_per_unit=20)
    client.post(f"/users/{user_id}/events", json={
        "event_type": "split", "instrument_id": inst["id"],
        "event_date": "2026-05-01", "ratio": 0.5,
    })
    pos = client.get(f"/users/{user_id}/positions").json()[0]
    assert pos["total_remaining_quantity"] == 5.0
    assert pos["avg_cost_per_unit"] == 40.0
    assert pos["total_cost_basis"] == 200.0  # invariant


def test_split_moves_no_cash(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"])
    before = client.get(f"/users/{user_id}/cash").json()["balance"]
    client.post(f"/users/{user_id}/events", json={
        "event_type": "split", "instrument_id": inst["id"],
        "event_date": "2026-05-01", "ratio": 2.0,
    })
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == before


def test_split_then_sell_uses_adjusted_basis(client, user_id):
    inst = _make_instr(client)
    buy = _buy(client, user_id, inst["id"], quantity=10, price_per_unit=200)  # basis 2000
    client.post(f"/users/{user_id}/events", json={
        "event_type": "split", "instrument_id": inst["id"],
        "event_date": "2026-05-01", "ratio": 2.0,
    })
    # After 2:1 the lot is 20 @ 100. Sell all at 150 -> pnl = 3000 - 2000 = 1000.
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 20, "sell_price_per_unit": 150, "sell_date": "2026-05-10",
    })
    assert r.status_code == 201, r.text
    assert r.json()["realized_pnl"] == 1000.0


# ── interest / fee ───────────────────────────────────────────────────────────

def test_interest_credits_cash(client, user_id):
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "interest", "event_date": "2026-05-31", "amount": 12.34,
    })
    assert r.status_code == 201
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == 12.34


def test_fee_debits_cash(client, user_id):
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "fee", "event_date": "2026-05-31", "amount": 5,
    })
    assert r.status_code == 201
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -5.0


# ── validation ───────────────────────────────────────────────────────────────

def test_dividend_requires_instrument(client, user_id):
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "dividend", "event_date": "2026-05-15", "amount": 1,
    })
    assert r.status_code == 422


def test_split_requires_positive_ratio(client, user_id):
    inst = _make_instr(client)
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "split", "instrument_id": inst["id"],
        "event_date": "2026-05-15", "ratio": 0,
    })
    assert r.status_code == 422


def test_unknown_event_type_rejected(client, user_id):
    r = client.post(f"/users/{user_id}/events", json={
        "event_type": "merger", "event_date": "2026-05-15", "amount": 1,
    })
    assert r.status_code == 422


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_dividend_reverses_cash(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"])
    ev = client.post(f"/users/{user_id}/events", json={
        "event_type": "dividend", "instrument_id": inst["id"],
        "event_date": "2026-05-15", "amount": 0.50,
    }).json()
    assert client.delete(f"/events/{ev['id']}").status_code == 200
    assert client.get(f"/users/{user_id}/cash").json()["balance"] == -1000.0


def test_delete_split_undoes_adjustment_when_no_trades_after(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"], quantity=10, price_per_unit=200)
    ev = client.post(f"/users/{user_id}/events", json={
        "event_type": "split", "instrument_id": inst["id"],
        "event_date": "2026-05-01", "ratio": 2.0,
    }).json()
    assert client.delete(f"/events/{ev['id']}").status_code == 200
    pos = client.get(f"/users/{user_id}/positions").json()[0]
    assert pos["total_remaining_quantity"] == 10.0
    assert pos["avg_cost_per_unit"] == 200.0


def test_delete_split_rejected_with_later_trade(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"], quantity=10, price_per_unit=200, trade_date="2026-04-01")
    ev = client.post(f"/users/{user_id}/events", json={
        "event_type": "split", "instrument_id": inst["id"],
        "event_date": "2026-05-01", "ratio": 2.0,
    }).json()
    # Buy more AFTER the split: deleting the split would invert this fresh lot too.
    _buy(client, user_id, inst["id"], quantity=5, price_per_unit=120, trade_date="2026-06-01")
    assert client.delete(f"/events/{ev['id']}").status_code == 409


# ── stats ────────────────────────────────────────────────────────────────────

def test_stats_surfaces_event_income_and_fees(client, user_id):
    inst = _make_instr(client)
    _buy(client, user_id, inst["id"])  # need shares for the dividend
    client.post(f"/users/{user_id}/events", json={
        "event_type": "dividend", "instrument_id": inst["id"],
        "event_date": "2026-05-15", "amount": 0.50,
    })  # +5 dividend
    client.post(f"/users/{user_id}/events", json={
        "event_type": "interest", "event_date": "2026-05-31", "amount": 3,
    })
    client.post(f"/users/{user_id}/events", json={
        "event_type": "fee", "event_date": "2026-05-31", "amount": 2,
    })
    stats = client.get(f"/users/{user_id}/stats").json()
    assert stats["dividend_income"] == 5.0
    assert stats["interest_income"] == 3.0
    assert stats["fees_paid"] == 2.0
