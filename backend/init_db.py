import pathlib
from db import get_connection, DB_PATH

SCHEMA = (pathlib.Path(__file__).parent / "schema.sql").read_text()

SEED_USER = ("TradeNexus User", "user@tradenexus.local")

# Default application settings, inserted only if the key is not already present.
SEED_SETTINGS = [
    ("display_name", "Trader"),
    ("currency", "USD"),
    ("date_format", "MM/DD/YYYY"),
    ("decimal_separator", "."),
    ("price_refresh_interval_minutes", "15"),
    ("default_broker_id", ""),
    ("fiscal_year_start_month", "1"),
]

# Default trade types (name, is_default). is_default=1 marks app-seeded rows.
SEED_TRADE_TYPES = [
    ("Stock", 1),
    ("Call", 1),
    ("Put", 1),
    ("Other", 1),
]

# trades schema WITHOUT the legacy trade_type CHECK constraint. Used to rebuild an
# older trades table so capitalized trade_type values are accepted (the constraint
# is replaced by trade_types + route-layer enforcement).
_TRADES_NO_CHECK_DDL = """
CREATE TABLE trades_new (
    id                 INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    broker_id          INTEGER  REFERENCES brokers(id),
    ticker             TEXT     NOT NULL,
    trade_type         TEXT     NOT NULL,
    action             TEXT     NOT NULL CHECK (action IN ('buy', 'sell')),
    quantity           REAL     NOT NULL CHECK (quantity > 0),
    price_per_unit     REAL     NOT NULL CHECK (price_per_unit >= 0),
    total_value        REAL     NOT NULL CHECK (total_value >= 0),
    trade_date         TEXT     NOT NULL,
    notes              TEXT,
    commission         REAL     NOT NULL DEFAULT 0,
    net_total_value    REAL,
    status             TEXT     NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'partial', 'closed')),
    remaining_quantity REAL,
    created_at         TEXT     NOT NULL DEFAULT (datetime('now'))
)
"""

_TRADES_COLS = (
    "id, user_id, broker_id, ticker, trade_type, action, quantity, price_per_unit, "
    "total_value, trade_date, notes, commission, net_total_value, status, "
    "remaining_quantity, created_at"
)


def seed_trade_types(conn):
    """Insert the default trade types if the table is empty."""
    cur = conn.cursor()
    if cur.execute("SELECT COUNT(*) FROM trade_types").fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO trade_types (name, is_default) VALUES (?, ?)",
            SEED_TRADE_TYPES,
        )
        conn.commit()
        print(f"Seeded {len(SEED_TRADE_TYPES)} default trade types")


def _rebuild_trades_without_check(conn):
    """Drop the legacy trade_type CHECK constraint by rebuilding the trades table.

    No-op if the table has already been rebuilt (or was created fresh without the
    constraint). All rows and the trades.id values are preserved.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'"
    ).fetchone()
    if not row or "trade_type IN ('stock'" not in row[0]:
        return  # already rebuilt or fresh schema — nothing to do

    # PRAGMA foreign_keys cannot change inside a transaction, so switch the
    # connection to autocommit and manage BEGIN/COMMIT explicitly.
    prev_iso = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        # Single-statement execute() (not executescript, which would force a COMMIT
        # and break the surrounding transaction).
        conn.execute(_TRADES_NO_CHECK_DDL)
        conn.execute(f"INSERT INTO trades_new ({_TRADES_COLS}) SELECT {_TRADES_COLS} FROM trades")
        conn.execute("DROP TABLE trades")
        conn.execute("ALTER TABLE trades_new RENAME TO trades")
        conn.execute("COMMIT")
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.execute("PRAGMA foreign_keys=ON")
        if problems:
            raise RuntimeError(f"Foreign-key check failed after trades rebuild: {problems}")
        print("Migration: rebuilt trades table to drop the trade_type CHECK constraint")
    finally:
        conn.isolation_level = prev_iso


def _migrate(conn):
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(trades)")
    columns = {row[1] for row in cur.fetchall()}

    if "status" not in columns:
        cur.execute(
            "ALTER TABLE trades ADD COLUMN status TEXT NOT NULL DEFAULT 'open' "
            "CHECK (status IN ('open', 'partial', 'closed'))"
        )
        print("Migration: added trades.status")

    if "remaining_quantity" not in columns:
        cur.execute("ALTER TABLE trades ADD COLUMN remaining_quantity REAL")
        print("Migration: added trades.remaining_quantity")

    # Back-fill remaining_quantity for rows that don't have it yet
    cur.execute(
        "UPDATE trades SET remaining_quantity = quantity WHERE remaining_quantity IS NULL"
    )
    if cur.rowcount:
        print(f"Migration: set remaining_quantity = quantity on {cur.rowcount} row(s)")

    if "broker_id" not in columns:
        cur.execute("ALTER TABLE trades ADD COLUMN broker_id INTEGER REFERENCES brokers(id)")
        print("Migration: added trades.broker_id")

    cur.execute("PRAGMA table_info(brokers)")
    broker_cols = {row[1] for row in cur.fetchall()}
    if "color" not in broker_cols:
        cur.execute("ALTER TABLE brokers ADD COLUMN color TEXT")
        print("Migration: added brokers.color")
    if "commission_flat" not in broker_cols:
        cur.execute("ALTER TABLE brokers ADD COLUMN commission_flat REAL NOT NULL DEFAULT 0")
        print("Migration: added brokers.commission_flat")
    if "commission_per_unit" not in broker_cols:
        cur.execute("ALTER TABLE brokers ADD COLUMN commission_per_unit REAL NOT NULL DEFAULT 0")
        print("Migration: added brokers.commission_per_unit")
    if "commission_currency" not in broker_cols:
        cur.execute("ALTER TABLE brokers ADD COLUMN commission_currency TEXT NOT NULL DEFAULT 'USD'")
        print("Migration: added brokers.commission_currency")

    cur.execute("PRAGMA table_info(trades)")
    columns = {row[1] for row in cur.fetchall()}
    if "commission" not in columns:
        cur.execute("ALTER TABLE trades ADD COLUMN commission REAL NOT NULL DEFAULT 0")
        print("Migration: added trades.commission")
    if "net_total_value" not in columns:
        cur.execute("ALTER TABLE trades ADD COLUMN net_total_value REAL")
        cur.execute(
            "UPDATE trades SET net_total_value = "
            "CASE WHEN action='buy' THEN total_value + commission ELSE total_value - commission END"
        )
        print("Migration: added trades.net_total_value and back-filled from total_value")

    conn.commit()

    # Drop the legacy trade_type CHECK so capitalized values are accepted. Runs
    # after the additive migrations above so the rebuilt table has every column.
    _rebuild_trades_without_check(conn)


def init():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.executescript(SCHEMA)
        _migrate(conn)

        cur.execute("SELECT id FROM users WHERE email = ?", (SEED_USER[1],))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO users (name, email) VALUES (?, ?)", SEED_USER)
            conn.commit()
            print(f"Seeded test user (id={cur.lastrowid}): {SEED_USER[0]} <{SEED_USER[1]}>")
        else:
            print("Test user already exists, skipping seed.")

        # Insert default settings only for keys that are missing; never overwrite.
        cur.executemany(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            SEED_SETTINGS,
        )
        if cur.rowcount:
            print(f"Seeded {cur.rowcount} default app setting(s)")
        conn.commit()

        # Seed trade types, then normalize existing trades to the canonical names
        # so every trade matches a name in trade_types.
        seed_trade_types(conn)
        for canonical in ("Stock", "Call", "Put", "Other"):
            cur.execute(
                "UPDATE trades SET trade_type = ? WHERE LOWER(trade_type) = ?",
                (canonical, canonical.lower()),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"Database initialised at {DB_PATH}")


if __name__ == "__main__":
    init()
