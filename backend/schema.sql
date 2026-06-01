CREATE TABLE IF NOT EXISTS users (
    id         INTEGER  PRIMARY KEY AUTOINCREMENT,
    name       TEXT     NOT NULL,
    email      TEXT     NOT NULL UNIQUE,
    created_at TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS brokers (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    name                TEXT     NOT NULL UNIQUE,
    price_source        TEXT     NOT NULL DEFAULT 'yahoo_finance',
    color               TEXT,
    commission_flat     REAL     NOT NULL DEFAULT 0,
    commission_per_unit REAL     NOT NULL DEFAULT 0,
    commission_currency TEXT     NOT NULL DEFAULT 'USD',
    config              TEXT,
    notes               TEXT,
    created_at          TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS instruments (
    id          INTEGER  PRIMARY KEY,
    symbol      TEXT     NOT NULL UNIQUE,             -- Yahoo Finance symbol, e.g. "VOD.L", "BTC-USD", "EURUSD=X"
    ticker      TEXT     NOT NULL,                    -- display name the user sees, e.g. "VOD", "BTC", "EUR/USD"
    name        TEXT,                                 -- full name, e.g. "Vodafone Group Plc", "Bitcoin USD"
    exchange    TEXT,                                 -- e.g. "LSE", "NASDAQ", "CCY"
    asset_class TEXT     NOT NULL DEFAULT 'stock',    -- stock, etf, crypto, forex, futures, option, other
    currency    TEXT     NOT NULL DEFAULT 'USD',      -- native currency of the instrument
    isin        TEXT,                                 -- optional, for stocks/ETFs
    created_at  TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id                 INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    broker_id          INTEGER  REFERENCES brokers(id),
    instrument_id      INTEGER  REFERENCES instruments(id),
    ticker             TEXT     NOT NULL,
    trade_type         TEXT     NOT NULL,  -- soft reference to trade_types.name; enforced in the route layer
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
);

CREATE TABLE IF NOT EXISTS sell_lots (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    buy_trade_id        INTEGER  NOT NULL REFERENCES trades(id),
    sell_date           TEXT     NOT NULL,
    quantity_sold       REAL     NOT NULL,
    sell_price_per_unit REAL     NOT NULL,
    proceeds            REAL     NOT NULL,
    realized_pnl        REAL     NOT NULL,
    notes               TEXT,
    created_at          TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cash_pool (
    id               INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER  NOT NULL REFERENCES users(id),
    transaction_type TEXT     NOT NULL CHECK (transaction_type IN ('deposit', 'withdrawal', 'sell_proceeds', 'buy_deduction')),
    amount           REAL     NOT NULL,
    reference_id     INTEGER,
    note             TEXT,
    created_at       TEXT     NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS price_cache (
    id         INTEGER  PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT     NOT NULL,                    -- Yahoo Finance symbol, e.g. "VOD.L", "BTC-USD"
    price      REAL     NOT NULL,
    currency   TEXT     NOT NULL DEFAULT 'USD',
    fetched_at TEXT     NOT NULL DEFAULT (datetime('now')),
    source     TEXT     NOT NULL DEFAULT 'yahoo_finance',
    UNIQUE(symbol, source)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT  PRIMARY KEY,
    value TEXT  NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_types (
    id         INTEGER  PRIMARY KEY,
    name       TEXT     NOT NULL UNIQUE,            -- e.g. "Stock", "Call", "Put", "Other"
    is_default INTEGER  NOT NULL DEFAULT 0,         -- 1 = seeded by the app, 0 = user-created
    color      TEXT,                                -- optional "#rrggbb" for charts/badges
    created_at TEXT     NOT NULL DEFAULT (datetime('now'))
);
