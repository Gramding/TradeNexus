import pathlib
import sys
from db import get_connection, DB_PATH

# schema.sql lives beside this file in dev; in a PyInstaller bundle it is extracted
# to sys._MEIPASS (added via --add-data in build.py).
_SCHEMA_DIR = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
SCHEMA = (_SCHEMA_DIR / "schema.sql").read_text()

SEED_USER = ("TradeNexus User", "user@tradenexus.local")

# Default application settings, inserted only if the key is not already present.
SEED_SETTINGS = [
    ("display_name", "Trader"),
    ("currency", "USD"),
    ("base_currency", "USD"),
    ("language", "en"),
    ("date_format", "MM/DD/YYYY"),
    ("date_format_manual_override", "0"),
    ("decimal_separator", "."),
    ("price_refresh_interval_minutes", "15"),
    ("price_source", "yahoo_finance"),
    ("default_broker_id", ""),
    ("fiscal_year_start_month", "1"),
]

# Default chart/badge colors for the seeded trade types. Users can override any of
# these from the Trade Types settings page (stored in trade_types.color).
DEFAULT_TYPE_COLORS = {
    "Stock":   "#4f8ef7",
    "ETF":     "#a259ff",
    "Crypto":  "#ffaa33",
    "Forex":   "#4caf82",
    "Futures": "#e6c84f",
    "Call":    "#2bb6c4",
    "Put":     "#e05c5c",
    "Bond":    "#9aa0a6",
    "Other":   "#7b8099",
}

# Default trade types (name, is_default, color). is_default=1 marks app-seeded rows.
# The asset-class-aligned names (ETF/Crypto/Forex/Futures/Bond) let an instrument's
# asset_class auto-fill the trade type by name. Call/Put/Other remain for options
# and unlisted free-text entries that have no asset class.
SEED_TRADE_TYPES = [(name, 1, DEFAULT_TYPE_COLORS[name]) for name in (
    "Stock", "ETF", "Crypto", "Forex", "Futures", "Call", "Put", "Bond", "Other",
)]

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


# Performance indexes, created after the tables exist. CREATE INDEX IF NOT EXISTS
# makes this safe to run repeatedly on an existing database.
_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_trades_user_date ON trades(user_id, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_trades_user_status ON trades(user_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_trades_user_ticker ON trades(user_id, ticker)",
    "CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_sell_lots_buy_trade_id ON sell_lots(buy_trade_id)",
    "CREATE INDEX IF NOT EXISTS idx_sell_lots_sell_date ON sell_lots(sell_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_cash_pool_user_id ON cash_pool(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_cash_pool_user_date ON cash_pool(user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_price_cache_symbol_source ON price_cache(symbol, source)",
    "CREATE INDEX IF NOT EXISTS idx_instruments_symbol ON instruments(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_instruments_ticker ON instruments(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_user_date ON events(user_id, event_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_events_instrument ON events(instrument_id)",
    "CREATE INDEX IF NOT EXISTS idx_fx_rates_pair ON fx_rates(from_currency, to_currency)",
]


def create_indexes(conn):
    """Create all performance indexes. Idempotent — safe on an existing database."""
    cur = conn.cursor()
    for ddl in _INDEXES:
        cur.execute(ddl)
    conn.commit()
    # Refresh the query planner's statistics now that the indexes exist.
    cur.execute("ANALYZE")
    conn.commit()
    print(f"Ensured {len(_INDEXES)} indexes and ran ANALYZE")


def seed_trade_types(conn):
    """Ensure every default trade type exists. Idempotent (INSERT OR IGNORE on the
    unique name), so existing databases pick up newly added defaults — e.g. the
    asset-class types — on the next startup. Default types can't be deleted (the
    route layer blocks it), so re-inserting a missing one never fights the user."""
    cur = conn.cursor()
    before = cur.execute("SELECT COUNT(*) FROM trade_types").fetchone()[0]
    cur.executemany(
        "INSERT OR IGNORE INTO trade_types (name, is_default, color) VALUES (?, ?, ?)",
        SEED_TRADE_TYPES,
    )
    conn.commit()
    added = cur.execute("SELECT COUNT(*) FROM trade_types").fetchone()[0] - before
    if added:
        print(f"Seeded {added} default trade type(s)")


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


def _migrate_instruments(conn):
    """Add trades.instrument_id and best-effort back-fill the instruments table.

    For each distinct ticker on existing trades we create a minimal instrument
    (symbol = ticker = UPPER(ticker), asset_class = 'stock' as a safe default),
    then link every unlinked trade to it. Existing data is never modified beyond
    populating instrument_id, so this is safe to run on a populated database.
    """
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(trades)")
    columns = {row[1] for row in cur.fetchall()}
    if "instrument_id" not in columns:
        cur.execute("ALTER TABLE trades ADD COLUMN instrument_id INTEGER REFERENCES instruments(id)")
        print("Migration: added trades.instrument_id")

    # Create one instrument per distinct ticker. INSERT OR IGNORE skips tickers
    # already present (instruments.symbol is UNIQUE), so this is idempotent.
    cur.execute(
        """
        INSERT OR IGNORE INTO instruments (symbol, ticker, asset_class)
        SELECT DISTINCT UPPER(ticker), UPPER(ticker), 'stock'
        FROM trades
        WHERE ticker IS NOT NULL AND TRIM(ticker) != ''
        """
    )
    if cur.rowcount > 0:
        print(f"Migration: created {cur.rowcount} instrument(s) from existing tickers")

    # Link trades to their instrument by matching the ticker. Only fill rows that
    # are not already linked so a re-run never disturbs explicit assignments.
    cur.execute(
        """
        UPDATE trades
        SET instrument_id = (SELECT id FROM instruments WHERE symbol = UPPER(trades.ticker))
        WHERE instrument_id IS NULL
        """
    )
    if cur.rowcount > 0:
        print(f"Migration: linked {cur.rowcount} trade(s) to instruments")

    conn.commit()


def _migrate_price_cache_symbol(conn):
    """Rename price_cache.ticker -> symbol and re-key existing rows to the Yahoo
    symbol. Runs after _migrate_instruments so the instruments table is populated.

    No-op once the column is already named symbol (fresh schema or prior run).
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(price_cache)")
    cols = {row[1] for row in cur.fetchall()}
    if "symbol" in cols or "ticker" not in cols:
        return  # already migrated or fresh schema

    # Re-key cached rows from the display ticker to the matching instrument's Yahoo
    # symbol. UPDATE OR IGNORE skips any row whose target (symbol, source) already
    # exists — price_cache is a regenerable cache, so dropping a duplicate is fine.
    cur.execute(
        "UPDATE OR IGNORE price_cache "
        "SET ticker = (SELECT i.symbol FROM instruments i WHERE UPPER(i.ticker) = price_cache.ticker) "
        "WHERE EXISTS (SELECT 1 FROM instruments i WHERE UPPER(i.ticker) = price_cache.ticker)"
    )
    # Drop the old column-named index before the rename, then let create_indexes()
    # rebuild it under the new column name.
    cur.execute("DROP INDEX IF EXISTS idx_price_cache_ticker_source")
    cur.execute("ALTER TABLE price_cache RENAME COLUMN ticker TO symbol")
    conn.commit()
    print("Migration: renamed price_cache.ticker -> symbol and re-keyed to instrument symbols")


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
    if "quote_url_template" not in broker_cols:
        cur.execute("ALTER TABLE brokers ADD COLUMN quote_url_template TEXT")
        print("Migration: added brokers.quote_url_template")
    if "quote_url_key" not in broker_cols:
        cur.execute("ALTER TABLE brokers ADD COLUMN quote_url_key TEXT DEFAULT 'symbol'")
        print("Migration: added brokers.quote_url_key")

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

    # trade_types.color (per-type chart/badge color). Back-fill the default types
    # with their standard colors so existing databases get sensible chart colors;
    # user-created types stay uncolored until set from the settings page.
    cur.execute("PRAGMA table_info(trade_types)")
    tt_cols = {row[1] for row in cur.fetchall()}
    if "color" not in tt_cols:
        cur.execute("ALTER TABLE trade_types ADD COLUMN color TEXT")
        for nm, col in DEFAULT_TYPE_COLORS.items():
            cur.execute(
                "UPDATE trade_types SET color = ? WHERE name = ? AND color IS NULL",
                (col, nm),
            )
        print("Migration: added trade_types.color (+ default colors)")

    conn.commit()

    # Drop the legacy trade_type CHECK so capitalized values are accepted. Runs
    # after the additive migrations above so the rebuilt table has every column.
    _rebuild_trades_without_check(conn)

    # Add + back-fill instrument_id last: the rebuild above copies a fixed column
    # list, so running this afterward guarantees the column survives the rebuild.
    _migrate_instruments(conn)

    # Re-key price_cache to instrument symbols (needs instruments populated above).
    _migrate_price_cache_symbol(conn)

    # Phase 1: foundation columns for options, shorts, and multi-currency.
    # All have defaults so existing rows remain valid; new behavior lands in later
    # phases. CHECK constraints from schema.sql don't apply to ALTER-added columns
    # in SQLite — validation is enforced at the route layer (consistent with how
    # trade_type is already handled).
    _migrate_phase1_columns(conn)

    # Phase 5: widen cash_pool.transaction_type to include event-driven flows
    # (dividend, interest, fee). Splits do not move cash, so they have no type.
    _migrate_cash_pool_event_types(conn)


_PHASE1_TRADE_COLUMNS = [
    ("direction",        "TEXT NOT NULL DEFAULT 'long'"),
    ("multiplier",       "REAL NOT NULL DEFAULT 1"),
    ("strike_price",     "REAL"),
    ("expiration_date",  "TEXT"),
    ("underlying",       "TEXT"),
    ("trade_currency",   "TEXT NOT NULL DEFAULT 'USD'"),
    ("fx_rate",          "REAL NOT NULL DEFAULT 1"),
    # Phase 6 (bonds): all nullable, harmless on non-bond trades.
    ("face_value",       "REAL"),
    ("coupon_rate",      "REAL"),
    ("coupon_frequency", "INTEGER"),
    ("maturity_date",    "TEXT"),
    ("accrued_interest", "REAL"),
]


_CASH_POOL_NEW_DDL = """
CREATE TABLE cash_pool_new (
    id               INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER  NOT NULL REFERENCES users(id),
    transaction_type TEXT     NOT NULL CHECK (transaction_type IN ('deposit', 'withdrawal', 'sell_proceeds', 'buy_deduction', 'dividend', 'interest', 'fee')),
    amount           REAL     NOT NULL,
    reference_id     INTEGER,
    note             TEXT,
    created_at       TEXT     NOT NULL DEFAULT (datetime('now'))
)
"""

_CASH_POOL_COLS = "id, user_id, transaction_type, amount, reference_id, note, created_at"


def _migrate_cash_pool_event_types(conn):
    """Rebuild cash_pool so its transaction_type CHECK accepts the Phase 5 event
    types. No-op when the table already lists 'dividend' (already migrated or
    fresh install via schema.sql)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='cash_pool'"
    ).fetchone()
    if not row or "'dividend'" in row[0]:
        return

    prev_iso = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        conn.execute(_CASH_POOL_NEW_DDL)
        conn.execute(f"INSERT INTO cash_pool_new ({_CASH_POOL_COLS}) SELECT {_CASH_POOL_COLS} FROM cash_pool")
        conn.execute("DROP TABLE cash_pool")
        conn.execute("ALTER TABLE cash_pool_new RENAME TO cash_pool")
        conn.execute("COMMIT")
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.execute("PRAGMA foreign_keys=ON")
        if problems:
            raise RuntimeError(f"Foreign-key check failed after cash_pool rebuild: {problems}")
        print("Migration: rebuilt cash_pool to accept event transaction types")
    finally:
        conn.isolation_level = prev_iso


def _migrate_phase1_columns(conn):
    """Add the additive trade columns introduced from Phase 1 onward
    (direction/multiplier/option metadata, currency/fx, bond fields),
    idempotently. Creates `events` and `fx_rates` tables if missing (schema.sql
    also creates them on fresh installs; this covers existing databases that
    pre-date the new tables). Name kept for migration-history continuity even
    though later phases append to the same column list."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(trades)")
    existing = {row[1] for row in cur.fetchall()}
    added = []
    for name, decl in _PHASE1_TRADE_COLUMNS:
        if name not in existing:
            cur.execute(f"ALTER TABLE trades ADD COLUMN {name} {decl}")
            added.append(name)
    if added:
        print(f"Migration: added trades columns {added}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id            INTEGER  PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            instrument_id INTEGER  REFERENCES instruments(id),
            event_type    TEXT     NOT NULL CHECK (event_type IN ('dividend', 'split', 'interest', 'fee')),
            event_date    TEXT     NOT NULL,
            amount        REAL,
            ratio         REAL,
            currency      TEXT     NOT NULL DEFAULT 'USD',
            fx_rate       REAL     NOT NULL DEFAULT 1 CHECK (fx_rate > 0),
            note          TEXT,
            created_at    TEXT     NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fx_rates (
            id            INTEGER  PRIMARY KEY AUTOINCREMENT,
            from_currency TEXT     NOT NULL,
            to_currency   TEXT     NOT NULL,
            rate          REAL     NOT NULL CHECK (rate > 0),
            fetched_at    TEXT     NOT NULL DEFAULT (datetime('now')),
            source        TEXT     NOT NULL DEFAULT 'yahoo_finance',
            UNIQUE(from_currency, to_currency, source)
        )
        """
    )
    conn.commit()


def _bootstrap(conn, *, seed_demo_user: bool):
    """Create the schema, run migrations, and seed defaults. Idempotent.

    Default settings and trade types are always seeded (the app needs them to
    function). The demo user is only seeded for development; a shipped app starts
    with zero users so it is genuinely empty.
    """
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    _migrate(conn)

    # Create indexes after tables exist (and after the trades rebuild in _migrate).
    create_indexes(conn)

    if seed_demo_user:
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


def ensure_initialized():
    """Bring the database up to a working, EMPTY state (no demo user).

    Safe to call on every app startup — it only creates what is missing.
    """
    conn = get_connection()
    try:
        _bootstrap(conn, seed_demo_user=False)
    finally:
        conn.close()


def init():
    """Full initializer for development / CLI use — also seeds a demo user."""
    conn = get_connection()
    try:
        _bootstrap(conn, seed_demo_user=True)
    finally:
        conn.close()
    print(f"Database initialised at {DB_PATH}")


if __name__ == "__main__":
    init()
