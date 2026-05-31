#!/usr/bin/env python3
"""
Wipe and repopulate the TradeNexus database with realistic mock data.
Run from the project root:  python seed.py
"""
import datetime
import pathlib
import random
import sys

random.seed(42)

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT / "backend"))

from db import get_connection, DB_PATH  # noqa: E402
from init_db import seed_trade_types    # noqa: E402

# Canonical trade-type names pulled from the trade_types table (filled in main()),
# keyed by lowercase so instrument kinds map to the stored names.
TRADE_TYPE_NAMES: dict[str, str] = {}

TODAY = datetime.date.today()
WINDOW_START = TODAY - datetime.timedelta(days=3 * 365)

# ── Ticker universe ───────────────────────────────────────────────────────────

STOCKS = {
    "AAPL": (140.0, 210.0),
    "MSFT": (220.0, 420.0),
    "GOOGL": (85.0, 175.0),
    "NVDA": (200.0, 950.0),
    "AMZN": (85.0, 195.0),
    "TSLA": (110.0, 300.0),
    "META": (90.0, 550.0),
    "JPM":  (115.0, 225.0),
    "BAC":  (25.0, 40.0),
    "V":    (200.0, 275.0),
    "AMD":  (65.0, 190.0),
    "NFLX": (185.0, 700.0),
}

ETFS = {
    "SPY": (370.0, 540.0),
    "QQQ": (280.0, 480.0),
    "IWM": (160.0, 220.0),
    "VTI": (190.0, 255.0),
    "XLF": (32.0, 42.0),
}

OPTIONS = {
    "AAPL": (140.0, 210.0),
    "NVDA": (200.0, 950.0),
    "TSLA": (110.0, 300.0),
    "SPY":  (370.0, 540.0),
    "QQQ":  (280.0, 480.0),
    "MSFT": (220.0, 420.0),
}

# ── Persona definitions ───────────────────────────────────────────────────────

PERSONAS = {
    "conservative": {
        "trade_range": (40, 60),
        "weights":     {"stock": 85, "etf": 15, "call": 0, "put": 0},
        "stock_qty":   (10, 100),
        "etf_qty":     (10, 200),
        "option_qty":  (1, 5),
    },
    "active": {
        "trade_range": (80, 120),
        "weights":     {"stock": 50, "etf": 20, "call": 15, "put": 15},
        "stock_qty":   (5, 50),
        "etf_qty":     (5, 100),
        "option_qty":  (1, 20),
    },
    "options": {
        "trade_range": (50, 80),
        "weights":     {"stock": 20, "etf": 10, "call": 40, "put": 30},
        "stock_qty":   (5, 30),
        "etf_qty":     (5, 50),
        "option_qty":  (1, 20),
    },
    "mixed": {
        "trade_range": (60, 90),
        "weights":     {"stock": 40, "etf": 25, "call": 18, "put": 17},
        "stock_qty":   (5, 75),
        "etf_qty":     (10, 150),
        "option_qty":  (1, 15),
    },
}

USERS = [
    # name, email, persona
    ("Alice Chen",        "alice.chen@email.com",       "conservative"),
    ("Robert Morrison",   "r.morrison@outlook.com",     "conservative"),
    ("Patricia Sullivan", "psullivan@gmail.com",        "conservative"),
    ("Jake Torres",       "jake.torres@gmail.com",      "active"),
    ("Mia Patel",         "mia.patel@icloud.com",       "active"),
    ("Tyler Brooks",      "tbrooks.trades@gmail.com",   "active"),
    ("Derek Huang",       "derek.huang@proton.me",      "options"),
    ("Samantha Cole",     "sam.cole@yahoo.com",         "options"),
    ("Marcus Webb",       "mwebb.finance@outlook.com",  "options"),
    ("Elena Rodriguez",   "elena.rod@gmail.com",        "mixed"),
    ("James Whitfield",   "jwhitfield@hotmail.com",     "mixed"),
    ("Chloe Nakamura",    "chloe.n@email.com",          "mixed"),
]

BUY_NOTES = [
    "earnings play",
    "long term hold",
    "hedging position",
    "dip buy",
    "momentum trade",
    "sector rotation",
    "dividend capture",
    "oversold bounce",
    "breakout trade",
    "mean reversion",
    "portfolio diversification",
    "adding to position",
    "technical breakout",
    "risk-off move",
    "rebalancing",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def recent_date() -> datetime.date:
    """Random date within the 3-year window, weighted toward recent dates."""
    x = random.betavariate(2, 5)
    days_ago = int(x * (TODAY - WINDOW_START).days)
    return TODAY - datetime.timedelta(days=days_ago)


def pick_trade(cfg: dict) -> tuple:
    """Return (ticker, trade_type, price, qty) for one random buy."""
    w = cfg["weights"]
    kind = random.choices(list(w), weights=list(w.values()))[0]

    # Map each instrument kind to a canonical trade-type name from trade_types.
    if kind == "stock":
        ticker = random.choice(list(STOCKS))
        lo, hi = STOCKS[ticker]
        qty = float(random.randint(*cfg["stock_qty"]))
        trade_type = TRADE_TYPE_NAMES["stock"]
    elif kind == "etf":
        ticker = random.choice(list(ETFS))
        lo, hi = ETFS[ticker]
        qty = float(random.randint(*cfg["etf_qty"]))
        trade_type = TRADE_TYPE_NAMES["other"]
    else:  # "call" or "put"
        ticker = random.choice(list(OPTIONS))
        lo, hi = OPTIONS[ticker]
        qty = float(random.randint(*cfg["option_qty"]))
        trade_type = TRADE_TYPE_NAMES[kind]

    price = round(random.uniform(lo, hi), 2)
    return ticker, trade_type, price, qty


def make_option_note(ticker: str, trade_type: str, trade_date: datetime.date, price: float) -> str:
    strike = max(round(price / 5) * 5 + random.choice([-10, -5, 0, 5, 10]), 1)
    expiry = trade_date + datetime.timedelta(days=random.randint(30, 180))
    label = "Call" if trade_type.lower() == "call" else "Put"
    return f"{ticker} ${strike} {label} exp {expiry.strftime('%Y-%m-%d')}"


def _dt(d: datetime.date, time: str) -> str:
    """Format a date + time string for created_at columns."""
    return f"{d.isoformat()} {time}"


# ── Broker definitions ────────────────────────────────────────────────────────

# Each broker carries a single commission_flat + commission_per_unit pair (the
# stored columns), plus the per-instrument rates used to compute realistic
# per-trade commissions during seeding. commission_per_unit is stored as the
# headline options/contract rate, which is what the frontend estimate uses.
BROKERS = [
    {
        "name": "Interactive Brokers",
        "notes": "Full-service broker with wide instrument coverage",
        "flat": 0.0, "options_per_contract": 0.65, "stock_per_share": 0.005,
    },
    {
        "name": "Robinhood",
        "notes": "Commission-free retail trading app",
        "flat": 0.0, "options_per_contract": 0.0, "stock_per_share": 0.0,
    },
    {
        "name": "TD Ameritrade",
        "notes": "Acquired by Schwab; thinkorswim platform",
        "flat": 0.0, "options_per_contract": 0.65, "stock_per_share": 0.0,
    },
    {
        "name": "Fidelity",
        "notes": "Full-service broker with strong research tools",
        "flat": 0.0, "options_per_contract": 0.65, "stock_per_share": 0.0,
    },
    {
        "name": "Charles Schwab",
        "notes": "Large retail and institutional broker",
        "flat": 0.0, "options_per_contract": 0.65, "stock_per_share": 0.0,
    },
]


def broker_commission(cfg: dict, trade_type: str, quantity: float) -> float:
    """Realistic per-trade commission: flat fee + a per-unit fee that depends on
    instrument type (per-contract for options, per-share for stocks/ETFs)."""
    if trade_type.lower() in ("call", "put"):
        per_unit = cfg["options_per_contract"]
    else:  # stock, or 'other' (ETFs)
        per_unit = cfg["stock_per_share"]
    return round(cfg["flat"] + per_unit * quantity, 2)

# ── Schema reset ──────────────────────────────────────────────────────────────

def reset_schema(conn) -> None:
    schema = (ROOT / "backend" / "schema.sql").read_text()
    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        DROP TABLE IF EXISTS price_cache;
        DROP TABLE IF EXISTS sell_lots;
        DROP TABLE IF EXISTS cash_pool;
        DROP TABLE IF EXISTS trades;
        DROP TABLE IF EXISTS brokers;
        DROP TABLE IF EXISTS users;
        PRAGMA foreign_keys = ON;
    """)
    conn.executescript(schema)
    conn.commit()


# ── Broker seed ───────────────────────────────────────────────────────────────

def seed_brokers(conn) -> dict[int, dict]:
    """Insert default brokers; return a map of broker_id -> commission config."""
    cur = conn.cursor()
    cfg_by_id: dict[int, dict] = {}
    for cfg in BROKERS:
        cur.execute(
            "INSERT INTO brokers (name, price_source, notes, commission_flat, commission_per_unit) "
            "VALUES (?, 'yahoo_finance', ?, ?, ?)",
            (cfg["name"], cfg["notes"], cfg["flat"], cfg["options_per_contract"]),
        )
        cfg_by_id[cur.lastrowid] = cfg
    conn.commit()
    return cfg_by_id


# ── Per-user seed ─────────────────────────────────────────────────────────────

def seed_user(conn, name: str, email: str, persona: str, broker_cfg: dict[int, dict]) -> tuple[int, int, int]:
    """Insert one user with all their trades, sell lots, and cash pool rows.

    Returns (n_trades, n_sell_lots, n_cash_transactions).
    Everything is committed in one shot at the end.
    """
    cfg = PERSONAS[persona]
    cur = conn.cursor()

    cur.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
    user_id = cur.lastrowid

    # ── Build trade list ──────────────────────────────────────────────────────
    n_trades = random.randint(*cfg["trade_range"])
    trades = []

    for _ in range(n_trades):
        ticker, trade_type, price, qty = pick_trade(cfg)
        date = recent_date()
        total = round(price * qty, 2)

        if trade_type.lower() in ("call", "put"):
            note = make_option_note(ticker, trade_type, date, price)
        elif random.random() < 0.40:
            note = random.choice(BUY_NOTES)
        else:
            note = None

        trades.append({
            "date": date, "ticker": ticker, "type": trade_type,
            "price": price, "qty": qty, "total": total, "note": note,
            "broker_id": random.choice(list(broker_cfg)),
        })

    trades.sort(key=lambda t: t["date"])

    # ── Insert trades ─────────────────────────────────────────────────────────
    trade_ids: list[int] = []
    for t in trades:
        commission = broker_commission(broker_cfg[t["broker_id"]], t["type"], t["qty"])
        net_total  = round(t["total"] + commission, 2)  # buys add commission to cost
        t["commission"] = commission  # stashed for the sell-lot P&L calc below
        cur.execute(
            """
            INSERT INTO trades
                (user_id, broker_id, ticker, trade_type, action, quantity, price_per_unit,
                 total_value, trade_date, notes, status, remaining_quantity,
                 commission, net_total_value)
            VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                user_id, t["broker_id"], t["ticker"], t["type"], t["qty"], t["price"],
                t["total"], t["date"].isoformat(), t["note"], t["qty"],
                commission, net_total,
            ),
        )
        trade_ids.append(cur.lastrowid)

    # ── Sell lots — close roughly 60 % of buys ────────────────────────────────
    sell_indices = random.sample(range(n_trades), int(n_trades * 0.60))
    sell_records: list[dict] = []

    for idx in sell_indices:
        t = trades[idx]
        trade_id = trade_ids[idx]

        sell_date = min(
            t["date"] + datetime.timedelta(days=random.randint(3, 365)),
            TODAY,
        )
        sell_price = round(t["price"] * random.uniform(0.70, 1.60), 2)

        if random.random() < 0.70:
            qty_sold, remaining, status = t["qty"], 0.0, "closed"
        else:
            fraction = random.uniform(0.30, 0.80)
            qty_sold = round(t["qty"] * fraction, 4)
            remaining = round(t["qty"] - qty_sold, 4)
            status = "partial"

        proceeds = round(qty_sold * sell_price, 2)

        # Commission-adjusted realized P&L, mirroring the backend sell route:
        #   (proceeds - sell commission) - (lot cost basis + proportional buy commission)
        sell_commission     = broker_commission(broker_cfg[t["broker_id"]], t["type"], qty_sold)
        prop_buy_commission = round((qty_sold / t["qty"]) * t["commission"], 2)
        buy_cost_for_lot    = qty_sold * t["price"]
        pnl = round(
            (proceeds - sell_commission) - (buy_cost_for_lot + prop_buy_commission), 2
        )

        cur.execute(
            """
            INSERT INTO sell_lots
                (buy_trade_id, sell_date, quantity_sold, sell_price_per_unit,
                 proceeds, realized_pnl)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (trade_id, sell_date.isoformat(), qty_sold, sell_price, proceeds, pnl),
        )
        sell_lot_id = cur.lastrowid
        sell_records.append({"id": sell_lot_id, "proceeds": proceeds, "date": sell_date})

        cur.execute(
            "UPDATE trades SET status = ?, remaining_quantity = ? WHERE id = ?",
            (status, remaining, trade_id),
        )

    # ── Cash pool ─────────────────────────────────────────────────────────────
    total_buy_cost = sum(t["total"] for t in trades)
    deposit_total = total_buy_cost * random.uniform(0.8, 1.5)
    earliest: datetime.date = trades[0]["date"]
    cash_count = 0

    # 1–3 initial deposits spread across the 90 days before first trade
    n_init = random.randint(1, 3)
    raw_weights = [random.random() for _ in range(n_init)]
    w_sum = sum(raw_weights)
    for j, w in enumerate(raw_weights):
        amount = round(deposit_total * (w / w_sum), 2)
        days_before = random.randint(5 + j * 15, 90 + j * 15)
        dep_date = earliest - datetime.timedelta(days=days_before)
        cur.execute(
            """
            INSERT INTO cash_pool (user_id, transaction_type, amount, note, created_at)
            VALUES (?, 'deposit', ?, 'Initial deposit', ?)
            """,
            (user_id, amount, _dt(dep_date, "09:00:00")),
        )
        cash_count += 1

    # buy_deduction for every buy trade
    for trade_id, t in zip(trade_ids, trades):
        cur.execute(
            """
            INSERT INTO cash_pool
                (user_id, transaction_type, amount, reference_id, created_at)
            VALUES (?, 'buy_deduction', ?, ?, ?)
            """,
            (user_id, -t["total"], trade_id, _dt(t["date"], "10:00:00")),
        )
        cash_count += 1

    # sell_proceeds for every sell lot
    for s in sell_records:
        cur.execute(
            """
            INSERT INTO cash_pool
                (user_id, transaction_type, amount, reference_id, created_at)
            VALUES (?, 'sell_proceeds', ?, ?, ?)
            """,
            (user_id, s["proceeds"], s["id"], _dt(s["date"], "14:00:00")),
        )
        cash_count += 1

    # 30 % of users get 1–2 extra mid-history top-up deposits
    if random.random() < 0.30:
        history_days = (TODAY - earliest).days
        if history_days > 60:
            for _ in range(random.randint(1, 2)):
                extra = round(random.uniform(5_000, 50_000), 2)
                offset = random.randint(30, max(31, history_days // 2))
                topup_date = earliest + datetime.timedelta(days=offset)
                cur.execute(
                    """
                    INSERT INTO cash_pool
                        (user_id, transaction_type, amount, note, created_at)
                    VALUES (?, 'deposit', ?, 'Top-up deposit', ?)
                    """,
                    (user_id, extra, _dt(topup_date, "09:00:00")),
                )
                cash_count += 1

    conn.commit()
    return n_trades, len(sell_records), cash_count


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    conn = get_connection()

    print(f"Resetting database at {DB_PATH} ...")
    reset_schema(conn)
    print()

    # Seed trade types and pull their canonical names so trade generation uses the
    # table rather than a hardcoded list.
    seed_trade_types(conn)
    TRADE_TYPE_NAMES.update(
        {row[0].lower(): row[0] for row in conn.execute("SELECT name FROM trade_types")}
    )

    broker_cfg = seed_brokers(conn)
    print(f"  Seeded {len(broker_cfg)} brokers: {', '.join(b['name'] for b in BROKERS)}")
    print()

    total_trades = total_sells = total_cash = 0

    for i, (name, email, persona) in enumerate(USERS, 1):
        label = f"{name} ({persona})"
        print(f"  Seeding user {i:>2}/{len(USERS)}: {label:<35}", end="", flush=True)
        n_trades, n_sells, n_cash = seed_user(conn, name, email, persona, broker_cfg)
        print(f"  {n_trades:>3} trades   {n_sells:>2} sells")
        total_trades += n_trades
        total_sells += n_sells
        total_cash += n_cash

    conn.close()

    print()
    print("═" * 52)
    print("  Seed complete!")
    print(f"  Brokers:             {len(broker_cfg)}")
    print(f"  Users:               {len(USERS)}")
    print(f"  Trades:              {total_trades}")
    print(f"  Sell lots:           {total_sells}")
    print(f"  Cash transactions:   {total_cash}")
    print(f"  Database:            {DB_PATH}")
    print("═" * 52)


if __name__ == "__main__":
    main()
