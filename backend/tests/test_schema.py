"""Verify Phase 1 schema foundation: new trades columns, events and fx_rates
tables, and that existing trades migrate cleanly with default values.

These are DB-level checks — they hit sqlite directly via the same connection
the app uses, so a missing migration would be caught regardless of whether any
route exposes the new columns yet."""
import sqlite3

import db


PHASE1_TRADE_COLUMNS = {
    "direction", "multiplier", "strike_price", "expiration_date",
    "underlying", "trade_currency", "fx_rate",
}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_trades_has_phase1_columns(client):
    conn = sqlite3.connect(db.DB_PATH)
    try:
        cols = _columns(conn, "trades")
    finally:
        conn.close()
    missing = PHASE1_TRADE_COLUMNS - cols
    assert not missing, f"trades missing columns: {missing}"


def test_events_and_fx_rates_tables_exist(client):
    conn = sqlite3.connect(db.DB_PATH)
    try:
        tables = _tables(conn)
        assert "events" in tables
        assert "fx_rates" in tables
        # Spot-check critical columns so a future rename catches in tests.
        ev = _columns(conn, "events")
        assert {"user_id", "event_type", "event_date", "amount", "ratio", "fx_rate"} <= ev
        fx = _columns(conn, "fx_rates")
        assert {"from_currency", "to_currency", "rate", "fetched_at"} <= fx
    finally:
        conn.close()


def test_existing_trade_gets_defaults(client, user_id):
    """A normally-created trade should fill the new columns with safe defaults."""
    body = {
        "ticker": "AAPL", "trade_type": "stock", "action": "buy",
        "quantity": 10, "price_per_unit": 150, "trade_date": "2026-05-01",
    }
    r = client.post(f"/users/{user_id}/trades", json=body)
    assert r.status_code == 201
    trade_id = r.json()["id"]

    conn = sqlite3.connect(db.DB_PATH)
    try:
        row = conn.execute(
            "SELECT direction, multiplier, strike_price, expiration_date, "
            "underlying, trade_currency, fx_rate FROM trades WHERE id = ?",
            (trade_id,),
        ).fetchone()
    finally:
        conn.close()

    direction, multiplier, strike, expiry, underlying, ccy, fx = row
    assert direction == "long"
    assert multiplier == 1
    assert strike is None
    assert expiry is None
    assert underlying is None
    assert ccy == "USD"
    assert fx == 1


def test_migration_idempotent_on_existing_database():
    """Running the migration twice on the same DB must not error."""
    import init_db
    init_db._migrate_phase1_columns(sqlite3.connect(db.DB_PATH))
    init_db._migrate_phase1_columns(sqlite3.connect(db.DB_PATH))
