"""Phase 6: bonds.

Bonds are quoted as a percentage of par, so a 98.5 price on a $1000 face bond
is $985 per unit. We model this by deriving multiplier = face_value / 100, so
the existing options-style notional machinery (q × p × multiplier) Just Works.
Accrued interest paid at purchase is bundled into the cash debit but kept out
of cost basis, so realized P&L stays principal-only.
"""


def _buy_bond(client, uid, **overrides):
    body = {
        "ticker": "T2030", "trade_type": "Bond", "action": "buy",
        "quantity": 10, "price_per_unit": 98.5, "trade_date": "2026-04-01",
    }
    body.update(overrides)
    r = client.post(f"/users/{uid}/trades", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_bond_default_multiplier_and_face_value(client, user_id):
    t = _buy_bond(client, user_id)  # default face 1000 -> multiplier 10
    assert t["face_value"] == 1000.0
    assert t["multiplier"] == 10.0
    # 10 bonds × 98.5 × 10 = 9850
    assert t["total_value"] == 9850.0


def test_bond_explicit_face_value_drives_multiplier(client, user_id):
    # Some short-term notes use $100 face. multiplier should follow at 1x.
    t = _buy_bond(client, user_id, quantity=5, price_per_unit=99, face_value=100)
    assert t["face_value"] == 100.0
    assert t["multiplier"] == 1.0
    assert t["total_value"] == 495.0  # 5 × 99 × 1


def test_bond_cash_debit_uses_full_notional(client, user_id):
    _buy_bond(client, user_id)  # 9850 USD
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == -9850.0


def test_accrued_interest_adds_to_buy_cash_but_not_basis(client, user_id):
    t = _buy_bond(client, user_id, accrued_interest=12.34)
    # Cost basis (total_value) is unchanged — pure clean price × notional
    assert t["total_value"] == 9850.0
    # ... but the cash debit picks up the accrued interest the buyer paid.
    bal = client.get(f"/users/{user_id}/cash").json()["balance"]
    assert bal == -9862.34


def test_accrued_interest_must_be_non_negative(client, user_id):
    r = client.post(f"/users/{user_id}/trades", json={
        "ticker": "T2030", "trade_type": "Bond", "action": "buy",
        "quantity": 1, "price_per_unit": 100, "trade_date": "2026-04-01",
        "accrued_interest": -1,
    })
    assert r.status_code == 422


def test_bond_sell_realized_pnl_principal_only(client, user_id):
    buy = _buy_bond(client, user_id, quantity=10, price_per_unit=98.5)  # basis 9850
    # Sell at par: pnl = 10 × 100 × 10 − 9850 = 10000 − 9850 = 150
    r = client.post(f"/trades/{buy['id']}/sell", json={
        "quantity_sold": 10, "sell_price_per_unit": 100, "sell_date": "2030-05-15",
    })
    assert r.status_code == 201
    assert r.json()["realized_pnl"] == 150.0


def test_bond_metadata_persists(client, user_id):
    t = _buy_bond(client, user_id,
                  coupon_rate=4.5, coupon_frequency=2, maturity_date="2030-05-15")
    assert t["coupon_rate"] == 4.5
    assert t["coupon_frequency"] == 2
    assert t["maturity_date"] == "2030-05-15"


def test_face_value_must_be_positive(client, user_id):
    r = client.post(f"/users/{user_id}/trades", json={
        "ticker": "T2030", "trade_type": "Bond", "action": "buy",
        "quantity": 1, "price_per_unit": 100, "trade_date": "2026-04-01",
        "face_value": 0,
    })
    assert r.status_code == 422


def test_non_bond_trade_has_no_face_value(client, user_id):
    t = client.post(f"/users/{user_id}/trades", json={
        "ticker": "AAPL", "trade_type": "Stock", "action": "buy",
        "quantity": 1, "price_per_unit": 100, "trade_date": "2026-04-01",
    }).json()
    assert t["face_value"] is None
    assert t["multiplier"] == 1.0
