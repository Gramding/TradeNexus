#!/usr/bin/env python3
"""
Stress / performance seed: build a LARGE database (default 100,000 trades per user).

Use this to test how the app behaves with a heavy dataset. It reuses the ticker
universe, brokers, personas, and P&L logic from seed.py, but inserts in bulk
(executemany with explicit ids) so 100k+ rows per user complete in seconds.

Usage:
    python seed_large.py                  # 3 users x 100,000 trades each
    python seed_large.py 1                # 1 user  x 100,000 trades
    python seed_large.py 5 250000         # 5 users x 250,000 trades each

WARNING: like seed.py, this WIPES existing users/brokers/trades/sell-lots/cash
before repopulating. Do not run it against a database you care about.
"""
import datetime
import random
import sys
import pathlib
import time

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT / "backend"))

from db import get_connection, DB_PATH          # noqa: E402
from init_db import seed_trade_types            # noqa: E402
import seed as S                                # reuse data + helpers  # noqa: E402

random.seed(20240601)

DEFAULT_USERS = 3
DEFAULT_TRADES_PER_USER = 100_000

# Roughly 60% of buys get (partly) sold, mirroring seed.py.
SELL_FRACTION = 0.60


def _apply_fast_pragmas(conn):
    """Speed up the bulk load. Safe for a throwaway stress database."""
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")   # ~200 MB page cache


def seed_user_bulk(conn, name, email, persona, broker_cfg, n_trades, id_state):
    """Insert one user with n_trades buys (+ sell lots + cash) using bulk inserts.

    id_state carries running 'trade' and 'sell' id counters so explicit ids stay
    unique across users (which lets us avoid a lastrowid round-trip per row).
    Returns (n_trades, n_sell_lots, n_cash_rows).
    """
    cfg = S.PERSONAS[persona]
    broker_ids = list(broker_cfg)
    cur = conn.cursor()

    cur.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
    user_id = cur.lastrowid

    # ── Generate trades (sorted oldest-first by date) ──────────────────────────
    generated = []
    for _ in range(n_trades):
        ticker, ttype, price, qty = S.pick_trade(cfg)
        generated.append((S.recent_date(), ticker, ttype, price, qty))
    generated.sort(key=lambda x: x[0])

    trade_rows = []
    trade_meta = []          # (tid, ttype, price, qty, total, commission, date, broker_id)
    cash_rows = []
    buy_total_sum = 0.0

    tid = id_state["trade"]
    for (date, ticker, ttype, price, qty) in generated:
        broker_id = random.choice(broker_ids)
        total = round(price * qty, 2)
        commission = S.broker_commission(broker_cfg[broker_id], ttype, qty)
        net_total = round(total + commission, 2)

        if ttype.lower() in ("call", "put"):
            note = S.make_option_note(ticker, ttype, date, price)
        elif random.random() < 0.25:
            note = random.choice(S.BUY_NOTES)
        else:
            note = None

        trade_rows.append((
            tid, user_id, broker_id, ticker, ttype, "buy", qty, price, total,
            date.isoformat(), note, "open", qty, commission, net_total,
        ))
        trade_meta.append((tid, ttype, price, qty, total, commission, date, broker_id))
        cash_rows.append((user_id, "buy_deduction", -total, tid, None, S._dt(date, "10:00:00")))
        buy_total_sum += total
        tid += 1
    id_state["trade"] = tid

    cur.executemany(
        "INSERT INTO trades "
        "(id, user_id, broker_id, ticker, trade_type, action, quantity, price_per_unit, "
        "total_value, trade_date, notes, status, remaining_quantity, commission, net_total_value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        trade_rows,
    )

    # ── Sell lots for ~SELL_FRACTION of buys ───────────────────────────────────
    sell_rows = []
    sell_updates = []
    sid = id_state["sell"]
    for idx in random.sample(range(n_trades), int(n_trades * SELL_FRACTION)):
        tid_, ttype, price, qty, total, commission, date, broker_id = trade_meta[idx]

        sell_date = min(date + datetime.timedelta(days=random.randint(3, 365)), S.TODAY)
        sell_price = round(price * random.uniform(0.70, 1.60), 2)

        if random.random() < 0.70:
            qty_sold, remaining, status = qty, 0.0, "closed"
        else:
            qty_sold = round(qty * random.uniform(0.30, 0.80), 4)
            remaining = round(qty - qty_sold, 4)
            status = "partial"

        proceeds = round(qty_sold * sell_price, 2)
        sell_commission = S.broker_commission(broker_cfg[broker_id], ttype, qty_sold)
        prop_buy_commission = round((qty_sold / qty) * commission, 2)
        pnl = round((proceeds - sell_commission) - (qty_sold * price + prop_buy_commission), 2)

        sell_rows.append((sid, tid_, sell_date.isoformat(), qty_sold, sell_price, proceeds, pnl))
        sell_updates.append((status, remaining, tid_))
        cash_rows.append((user_id, "sell_proceeds", proceeds, sid, None, S._dt(sell_date, "14:00:00")))
        sid += 1
    id_state["sell"] = sid

    cur.executemany(
        "INSERT INTO sell_lots "
        "(id, buy_trade_id, sell_date, quantity_sold, sell_price_per_unit, proceeds, realized_pnl) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        sell_rows,
    )
    cur.executemany(
        "UPDATE trades SET status = ?, remaining_quantity = ? WHERE id = ?",
        sell_updates,
    )

    # ── Cash pool: one big initial deposit covering the buys, plus the buy/sell
    #    movements collected above. ─────────────────────────────────────────────
    earliest = generated[0][0]
    deposit = round(buy_total_sum * random.uniform(1.0, 1.3), 2)
    cash_rows.append((
        user_id, "deposit", deposit, None, "Initial deposit",
        S._dt(earliest - datetime.timedelta(days=10), "09:00:00"),
    ))

    cur.executemany(
        "INSERT INTO cash_pool "
        "(user_id, transaction_type, amount, reference_id, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        cash_rows,
    )

    conn.commit()
    return n_trades, len(sell_rows), len(cash_rows)


def _parse_args(argv):
    users = int(argv[0]) if len(argv) >= 1 else DEFAULT_USERS
    per_user = int(argv[1]) if len(argv) >= 2 else DEFAULT_TRADES_PER_USER
    if users < 1 or per_user < 1:
        sys.exit("users and trades_per_user must be >= 1")
    return users, per_user


def main() -> None:
    n_users, per_user = _parse_args(sys.argv[1:])

    conn = get_connection()
    print(f"Resetting database at {DB_PATH} ...")
    S.reset_schema(conn)
    _apply_fast_pragmas(conn)

    seed_trade_types(conn)
    S.TRADE_TYPE_NAMES.update(
        {row[0].lower(): row[0] for row in conn.execute("SELECT name FROM trade_types")}
    )

    broker_cfg = S.seed_brokers(conn)
    print(f"  Seeded {len(broker_cfg)} brokers")
    print(f"  Target: {n_users} user(s) x {per_user:,} trades each\n")

    personas = list(S.PERSONAS)
    id_state = {"trade": 1, "sell": 1}
    total_trades = total_sells = total_cash = 0
    t0 = time.monotonic()

    for i in range(1, n_users + 1):
        # Reuse the friendly demo names for the first dozen users; generate the rest.
        if i <= len(S.USERS):
            name, _email, persona = S.USERS[i - 1]
        else:
            name, persona = f"Stress User {i:03d}", personas[i % len(personas)]
        email = f"stress{i:03d}@example.com"

        u0 = time.monotonic()
        print(f"  User {i:>2}/{n_users}: {name:<22} ({persona:<12}) ...", end="", flush=True)
        nt, ns, nc = seed_user_bulk(conn, name, email, persona, broker_cfg, per_user, id_state)
        total_trades += nt
        total_sells += ns
        total_cash += nc
        print(f" {nt:,} trades, {ns:,} sells, {nc:,} cash  [{time.monotonic() - u0:.1f}s]")

    conn.close()
    elapsed = time.monotonic() - t0
    total_rows = total_trades + total_sells + total_cash

    print("\n" + "=" * 60)
    print("  Large seed complete!")
    print(f"  Users:               {n_users}")
    print(f"  Trades:              {total_trades:,}")
    print(f"  Sell lots:           {total_sells:,}")
    print(f"  Cash transactions:   {total_cash:,}")
    print(f"  Total rows:          {total_rows:,}")
    print(f"  Elapsed:             {elapsed:.1f}s  ({total_rows / max(elapsed, 0.001):,.0f} rows/s)")
    print(f"  Database:            {DB_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
