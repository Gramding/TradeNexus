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
    quote_url_template  TEXT,                            -- URL with a single {value} placeholder, e.g. "https://robinhood.com/stocks/{value}"
    quote_url_key       TEXT     DEFAULT 'symbol',       -- which instrument id fills {value}: 'symbol' | 'ticker' | 'isin'
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
    direction          TEXT     NOT NULL DEFAULT 'long' CHECK (direction IN ('long', 'short')),
    multiplier         REAL     NOT NULL DEFAULT 1 CHECK (multiplier > 0),
    strike_price       REAL,
    expiration_date    TEXT,
    underlying         TEXT,
    trade_currency     TEXT     NOT NULL DEFAULT 'USD',
    fx_rate            REAL     NOT NULL DEFAULT 1 CHECK (fx_rate > 0),
    face_value         REAL,                  -- bonds: par per unit (e.g. 1000)
    coupon_rate        REAL,                  -- bonds: annual coupon rate, %
    coupon_frequency   INTEGER,               -- bonds: payments per year (1, 2, 4, 12)
    maturity_date      TEXT,                  -- bonds: ISO date
    accrued_interest   REAL,                  -- bonds: accrued at purchase, in trade_currency
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
    transaction_type TEXT     NOT NULL CHECK (transaction_type IN ('deposit', 'withdrawal', 'sell_proceeds', 'buy_deduction', 'dividend', 'interest', 'fee')),
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

-- Income, distribution, and corporate-action events that affect a user's portfolio
-- without being a buy/sell trade. Wired up by Phase 5; created here so the schema
-- is in place for migrations and forward compatibility.
--   dividend : amount is cash-per-share on event_date; instrument_id required
--   split    : ratio is new/old (2.0 = 2-for-1, 0.5 = reverse 1-for-2); instrument required
--   interest : amount is total cash credit; instrument optional
--   fee      : amount is total cash debit; instrument optional
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
);

-- FX-rate cache: 1 unit of from_currency = `rate` units of to_currency at `fetched_at`.
-- Used by Phase 4 to convert trade-currency amounts into the user's base currency.
CREATE TABLE IF NOT EXISTS fx_rates (
    id            INTEGER  PRIMARY KEY AUTOINCREMENT,
    from_currency TEXT     NOT NULL,
    to_currency   TEXT     NOT NULL,
    rate          REAL     NOT NULL CHECK (rate > 0),
    fetched_at    TEXT     NOT NULL DEFAULT (datetime('now')),
    source        TEXT     NOT NULL DEFAULT 'yahoo_finance',
    UNIQUE(from_currency, to_currency, source)
);
