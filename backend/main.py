import base64
import csv
import io
import json
import logging
import sqlite3
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import datetime

from db import get_connection
from backup import run_startup_backup
from init_db import ensure_initialized
import brokers as brokers_module
import instruments as instruments_module
import prices as prices_module
import quote_links as quote_links_module
import settings as settings_module
import stats_cache
import trade_types as trade_types_module

logger = logging.getLogger(__name__)

# Snapshot the existing database before any migration, then make sure the schema
# and default settings/trade-types exist. On a fresh install this creates an empty
# but fully working database (no users) — see ensure_initialized().
try:
    run_startup_backup()
except Exception:
    logger.exception("Startup backup failed; continuing without a backup")

try:
    ensure_initialized()
except Exception:
    logger.exception("Database initialization failed; the app may not work")

app = FastAPI(title="TradeNexus")
app.include_router(brokers_module.router)
app.include_router(instruments_module.router)
app.include_router(prices_module.router)
app.include_router(quote_links_module.router)
app.include_router(settings_module.router)
app.include_router(trade_types_module.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost:8765", "http://127.0.0.1:8765"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ACTIONS = {"buy", "sell"}


def _normalize_trade_type(cur: sqlite3.Cursor, value: str) -> str:
    """Validate a trade_type against the trade_types table (case-insensitively)
    and return the canonical stored name. Raises 422 if it is not a known type.

    This replaces the old DB-level CHECK constraint: the constraint is enforced
    here, in the route layer, against the trade_types table.
    """
    cur.execute("SELECT name FROM trade_types")
    by_lower = {row[0].lower(): row[0] for row in cur.fetchall()}
    canonical = by_lower.get((value or "").strip().lower())
    if canonical is None:
        raise HTTPException(status_code=400, detail="Unknown trade type")
    return canonical


# ---------------------------------------------------------------------------
# Global error handlers
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    try:
        return get_connection()
    except sqlite3.OperationalError as exc:
        logger.error("DB open failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not open the database.")


def _validate_iso_date(value, field: str):
    """Return a normalized ISO date string, None for empty, or raise 400 if invalid."""
    if value is None or value == "":
        return None
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"{field} must be an ISO date (YYYY-MM-DD).")


# Reusable SELECT that joins broker name + color and the linked instrument; used
# by list/create/update trade routes.
# Columns: 0=id 1=user_id 2=ticker 3=trade_type 4=action 5=quantity
#          6=price_per_unit 7=total_value 8=trade_date 9=notes 10=created_at
#          11=status 12=remaining_quantity 13=broker_id 14=broker_name 15=broker_color
#          16=commission 17=net_total_value
#          18=instr_symbol 19=instr_name 20=instr_exchange 21=instr_asset_class 22=instr_currency
_TRADE_SELECT = (
    "SELECT t.id, t.user_id, t.ticker, t.trade_type, t.action, t.quantity, "
    "t.price_per_unit, t.total_value, t.trade_date, t.notes, t.created_at, "
    "t.status, t.remaining_quantity, t.broker_id, b.name, b.color, "
    "t.commission, t.net_total_value, "
    "i.symbol, i.name, i.exchange, i.asset_class, i.currency "
    "FROM trades t LEFT JOIN brokers b ON t.broker_id = b.id "
    "LEFT JOIN instruments i ON t.instrument_id = i.id"
)


# Sort fields the paginated trades endpoint accepts -> their SQL column.
_TRADE_SORT_COLUMNS = {
    "trade_date":     "t.trade_date",
    "ticker":         "t.ticker",
    "total_value":    "t.total_value",
    "price_per_unit": "t.price_per_unit",
    "quantity":       "t.quantity",
}

# In-memory cache of total_count per (user_id, filter) for 30s, so paging through
# results doesn't re-run COUNT(*) on every request.
_COUNT_CACHE: dict = {}
_COUNT_CACHE_TTL = 30.0


def _encode_cursor(last_val, last_id: int) -> str:
    """base64(JSON) of the last row's sort value + id — opaque keyset cursor."""
    raw = json.dumps({"last_val": last_val, "last_id": last_id}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str):
    """Return (last_val, last_id) from an opaque cursor, or 400 if it's malformed."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return data["last_val"], int(data["last_id"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid cursor.")


def _cached_total_count(conn, cache_key, where_sql: str, params: list) -> int:
    """COUNT(*) of matching trades, cached per cache_key for _COUNT_CACHE_TTL seconds."""
    now = time.monotonic()
    cached = _COUNT_CACHE.get(cache_key)
    if cached is not None and now - cached[0] < _COUNT_CACHE_TTL:
        return cached[1]
    count = conn.execute("SELECT COUNT(*) FROM trades t" + where_sql, params).fetchone()[0]
    _COUNT_CACHE[cache_key] = (now, count)
    return count


def _row_to_trade(r) -> dict:
    return {
        "id":                 r[0],
        "user_id":            r[1],
        "ticker":             r[2],
        "trade_type":         r[3],
        "action":             r[4],
        "quantity":           float(r[5]),
        "price_per_unit":     float(r[6]),
        "total_value":        float(r[7]),
        "trade_date":         r[8],
        "notes":              r[9],
        "created_at":         r[10],
        "status":             r[11],
        "remaining_quantity": float(r[12]) if r[12] is not None else None,
        "broker_id":          r[13],
        "broker_name":        r[14],
        "broker_color":       r[15],
        "commission":         float(r[16]) if r[16] is not None else 0.0,
        "net_total_value":    float(r[17]) if r[17] is not None else None,
        "symbol":             r[18],
        "name":               r[19],
        "exchange":           r[20],
        "asset_class":        r[21],
        "currency":           r[22],
    }


def _compute_commission(cur: sqlite3.Cursor, broker_id, quantity: float, override) -> float:
    """Commission for a trade: the user override if given, else the broker's
    flat fee + per-unit fee * quantity. Returns 0 when neither applies."""
    if override is not None:
        return round(float(override), 10)
    if broker_id is None:
        return 0.0
    cur.execute(
        "SELECT commission_flat, commission_per_unit FROM brokers WHERE id = ?",
        (broker_id,),
    )
    row = cur.fetchone()
    if row is None:
        return 0.0
    flat, per_unit = float(row[0] or 0), float(row[1] or 0)
    return round(flat + per_unit * quantity, 10)


def _net_total(action: str, total_value: float, commission: float) -> float:
    """Buys cost more (add commission); sells net less (subtract commission)."""
    return round(total_value + commission if action == "buy" else total_value - commission, 10)


def _row_to_sell_lot(r) -> dict:
    return {
        "id": r[0],
        "buy_trade_id": r[1],
        "sell_date": r[2],
        "quantity_sold": float(r[3]),
        "sell_price_per_unit": float(r[4]),
        "proceeds": float(r[5]),
        "realized_pnl": float(r[6]),
        "notes": r[7],
        "created_at": r[8],
    }


def _require_user(cur: sqlite3.Cursor, user_id: int):
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found.")


def _require_trade(cur: sqlite3.Cursor, trade_id: int) -> tuple:
    # Columns: 0=id 1=user_id 2=ticker 3=trade_type 4=action 5=quantity
    #          6=price_per_unit 7=total_value 8=trade_date 9=notes 10=created_at
    #          11=status 12=remaining_quantity 13=broker_id 14=commission
    cur.execute(
        "SELECT id, user_id, ticker, trade_type, action, quantity, price_per_unit, "
        "total_value, trade_date, notes, created_at, status, remaining_quantity, broker_id, "
        "commission "
        "FROM trades WHERE id = ?",
        (trade_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found.")
    return row


def _require_broker(cur: sqlite3.Cursor, broker_id: int):
    cur.execute("SELECT id FROM brokers WHERE id = ?", (broker_id,))
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Broker {broker_id} not found.")


def _require_instrument(cur: sqlite3.Cursor, instrument_id: int):
    cur.execute("SELECT id FROM instruments WHERE id = ?", (instrument_id,))
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found.")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    name: str
    email: str


class TradeCreate(BaseModel):
    ticker: str
    trade_type: str
    action: str
    quantity: float
    price_per_unit: float
    trade_date: datetime.date
    notes: Optional[str] = None
    broker_id: Optional[int] = None
    commission: Optional[float] = None  # None = auto-calc from broker
    instrument_id: Optional[int] = None  # set when picked from the instrument search


class TradeUpdate(BaseModel):
    ticker: Optional[str] = None
    trade_type: Optional[str] = None
    action: Optional[str] = None
    quantity: Optional[float] = None
    price_per_unit: Optional[float] = None
    trade_date: Optional[datetime.date] = None
    notes: Optional[str] = None
    broker_id: Optional[int] = None
    commission: Optional[float] = None


class SellLotCreate(BaseModel):
    quantity_sold: float
    sell_price_per_unit: float
    sell_date: datetime.date
    notes: Optional[str] = None
    commission: Optional[float] = None  # None = auto-calc from the buy trade's broker


class CashTransaction(BaseModel):
    amount: float
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@app.get("/users")
def list_users():
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, email, created_at FROM users ORDER BY id")
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        logger.error("list_users DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch users.")
    finally:
        conn.close()

    return [{"id": r[0], "name": r[1], "email": r[2], "created_at": r[3]} for r in rows]


@app.post("/users", status_code=201)
def create_user(body: UserCreate):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Name cannot be empty.")
    if not body.email.strip():
        raise HTTPException(status_code=422, detail="Email cannot be empty.")

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (body.name.strip(), body.email.strip()),
        )
        conn.commit()
        user_id = cur.lastrowid
        cur.execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="A user with that email already exists.")
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("create_user DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create user.")
    finally:
        conn.close()

    return {"id": row[0], "name": row[1], "email": row[2], "created_at": row[3]}


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        # sell_lots and cash_pool lack ON DELETE CASCADE, so delete in order
        cur.execute(
            "DELETE FROM sell_lots WHERE buy_trade_id IN "
            "(SELECT id FROM trades WHERE user_id = ?)",
            (user_id,),
        )
        cur.execute("DELETE FROM cash_pool WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM trades    WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM users     WHERE id      = ?", (user_id,))
        conn.commit()
        stats_cache.invalidate(user_id)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("delete_user DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete user.")
    finally:
        conn.close()

    return {"detail": f"User {user_id} and all their trades deleted."}


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/trades")
def list_trades(
    user_id: int,
    limit: int = Query(100, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    trade_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("trade_date"),
    sort_dir: str = Query("desc"),
):
    # trade_date is stored as an ISO 'YYYY-MM-DD' string, so range filters are
    # plain string comparisons. Validate the inputs so a bad value is a clean 400.
    date_from = _validate_iso_date(date_from, "date_from")
    date_to = _validate_iso_date(date_to, "date_to")

    if sort_by not in _TRADE_SORT_COLUMNS:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by must be one of: {', '.join(sorted(_TRADE_SORT_COLUMNS))}.",
        )
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(status_code=422, detail="sort_dir must be 'asc' or 'desc'.")

    sort_col = _TRADE_SORT_COLUMNS[sort_by]

    # WHERE clause + params shared by the data query and the COUNT query (filters
    # only — the keyset cursor condition is appended to the data query alone).
    where_sql = " WHERE t.user_id = ?"
    filter_params: list = [user_id]
    if ticker:
        where_sql += " AND UPPER(t.ticker) = UPPER(?)"
        filter_params.append(ticker)
    if trade_type:
        where_sql += " AND LOWER(t.trade_type) = LOWER(?)"
        filter_params.append(trade_type)
    if action:
        where_sql += " AND t.action = ?"
        filter_params.append(action)
    if status:
        where_sql += " AND t.status = ?"
        filter_params.append(status)
    if date_from:
        where_sql += " AND t.trade_date >= ?"
        filter_params.append(date_from)
    if date_to:
        where_sql += " AND t.trade_date <= ?"
        filter_params.append(date_to)

    # Cache key is the filter set only — independent of sort, cursor, and limit.
    cache_key = (
        user_id,
        ticker.upper() if ticker else None,
        trade_type.lower() if trade_type else None,
        action,
        status,
        date_from,
        date_to,
    )

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)

        query = _TRADE_SELECT + where_sql
        params = list(filter_params)

        # Keyset pagination: rows strictly after the cursor in the sort order.
        if cursor is not None:
            last_val, last_id = _decode_cursor(cursor)
            op = "<" if sort_dir == "desc" else ">"
            query += f" AND ({sort_col}, t.id) {op} (?, ?)"
            params.extend([last_val, last_id])

        direction = "DESC" if sort_dir == "desc" else "ASC"
        # Fetch one extra row to detect whether another page exists.
        query += f" ORDER BY {sort_col} {direction}, t.id {direction} LIMIT ?"
        params.append(limit + 1)

        cur.execute(query, params)
        rows = cur.fetchall()
        total_count = _cached_total_count(conn, cache_key, where_sql, filter_params)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("list_trades DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch trades.")
    finally:
        conn.close()

    has_more = len(rows) > limit
    rows = rows[:limit]
    trades = [_row_to_trade(r) for r in rows]

    next_cursor = None
    if has_more and trades:
        last = trades[-1]
        next_cursor = _encode_cursor(last[sort_by], last["id"])

    return {
        "trades": trades,
        "total_count": int(total_count),
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


@app.post("/users/{user_id}/trades", status_code=201)
def create_trade(user_id: int, body: TradeCreate):
    if not body.ticker.strip():
        raise HTTPException(status_code=422, detail="Ticker cannot be empty.")
    if body.action not in ACTIONS:
        raise HTTPException(status_code=422, detail=f"action must be one of: {', '.join(sorted(ACTIONS))}.")
    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than 0.")
    if body.price_per_unit < 0:
        raise HTTPException(status_code=422, detail="price_per_unit must be >= 0.")
    if body.commission is not None and body.commission < 0:
        raise HTTPException(status_code=422, detail="commission must be >= 0.")

    total_value = round(body.quantity * body.price_per_unit, 10)

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        trade_type = _normalize_trade_type(cur, body.trade_type)
        if body.broker_id is not None:
            _require_broker(cur, body.broker_id)
        if body.instrument_id is not None:
            _require_instrument(cur, body.instrument_id)

        commission      = _compute_commission(cur, body.broker_id, body.quantity, body.commission)
        net_total_value = _net_total(body.action, total_value, commission)

        cur.execute(
            "INSERT INTO trades "
            "(user_id, broker_id, instrument_id, ticker, trade_type, action, quantity, price_per_unit, "
            "total_value, trade_date, notes, remaining_quantity, commission, net_total_value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, body.broker_id, body.instrument_id, body.ticker.strip().upper(),
                trade_type, body.action, body.quantity, body.price_per_unit, total_value,
                body.trade_date.isoformat(), body.notes, body.quantity,
                commission, net_total_value,
            ),
        )
        trade_id = cur.lastrowid

        if body.action == "buy":
            # Deduct the commission-inclusive net so the cash pool matches what the
            # broker actually debits (gross cost + commission).
            cur.execute(
                "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
                "VALUES (?, 'buy_deduction', ?, ?)",
                (user_id, -net_total_value, trade_id),
            )

        conn.commit()
        stats_cache.invalidate(user_id)
        cur.execute(_TRADE_SELECT + " WHERE t.id = ?", (trade_id,))
        row = cur.fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("create_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create trade.")
    finally:
        conn.close()

    return _row_to_trade(row)


@app.put("/trades/{trade_id}")
def update_trade(trade_id: int, body: TradeUpdate):
    if body.action is not None and body.action not in ACTIONS:
        raise HTTPException(status_code=422, detail=f"action must be one of: {', '.join(sorted(ACTIONS))}.")
    if body.quantity is not None and body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than 0.")
    if body.price_per_unit is not None and body.price_per_unit < 0:
        raise HTTPException(status_code=422, detail="price_per_unit must be >= 0.")
    if body.commission is not None and body.commission < 0:
        raise HTTPException(status_code=422, detail="commission must be >= 0.")

    conn = _db()
    try:
        cur = conn.cursor()
        existing = _require_trade(cur, trade_id)

        if body.broker_id is not None:
            _require_broker(cur, body.broker_id)

        ticker         = body.ticker                        if body.ticker         is not None else existing[2]
        trade_type     = _normalize_trade_type(cur, body.trade_type) if body.trade_type is not None else existing[3]
        action         = body.action                        if body.action         is not None else existing[4]
        quantity       = body.quantity                      if body.quantity       is not None else float(existing[5])
        price_per_unit = body.price_per_unit                if body.price_per_unit is not None else float(existing[6])
        trade_date     = body.trade_date.isoformat()        if body.trade_date     is not None else existing[8]
        notes          = body.notes                         if body.notes          is not None else existing[9]
        broker_id      = body.broker_id                     if body.broker_id      is not None else existing[13]
        total_value    = round(quantity * price_per_unit, 10)

        # Commission: explicit override wins; else recompute when broker or quantity
        # changed; otherwise keep the existing value untouched.
        if body.commission is not None:
            commission = round(float(body.commission), 10)
        elif body.broker_id is not None or body.quantity is not None:
            commission = _compute_commission(cur, broker_id, quantity, None)
        else:
            commission = float(existing[14] or 0)
        net_total_value = _net_total(action, total_value, commission)

        cur.execute(
            "UPDATE trades SET ticker=?, trade_type=?, action=?, quantity=?, "
            "price_per_unit=?, total_value=?, trade_date=?, notes=?, broker_id=?, "
            "commission=?, net_total_value=? WHERE id=?",
            (ticker, trade_type, action, quantity, price_per_unit, total_value, trade_date, notes, broker_id,
             commission, net_total_value, trade_id),
        )

        # Keep the cash pool in sync with the edit: drop this trade's old buy
        # deduction and, if it is (still) a buy, re-insert one for the new net total.
        # Sell cash rows are keyed to sell lots rather than the trade, so they are
        # left untouched here.
        cur.execute(
            "DELETE FROM cash_pool WHERE transaction_type = 'buy_deduction' "
            "AND reference_id = ?",
            (trade_id,),
        )
        if action == "buy":
            cur.execute(
                "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
                "VALUES (?, 'buy_deduction', ?, ?)",
                (existing[1], -net_total_value, trade_id),
            )

        conn.commit()
        stats_cache.invalidate(existing[1])
        cur.execute(_TRADE_SELECT + " WHERE t.id = ?", (trade_id,))
        row = cur.fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("update_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update trade.")
    finally:
        conn.close()

    return _row_to_trade(row)


@app.delete("/trades/{trade_id}")
def delete_trade(trade_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        existing = _require_trade(cur, trade_id)

        # Remove dependent rows before the trade itself, so the sell_lots -> trades
        # foreign key doesn't block the delete, and reverse this trade's cash-pool
        # effects so the balance stays correct.
        sell_lot_ids = [
            r[0] for r in cur.execute(
                "SELECT id FROM sell_lots WHERE buy_trade_id = ?", (trade_id,)
            ).fetchall()
        ]
        if sell_lot_ids:
            placeholders = ",".join("?" * len(sell_lot_ids))
            # sell_proceeds cash rows reference the sell_lot id.
            cur.execute(
                f"DELETE FROM cash_pool WHERE transaction_type = 'sell_proceeds' "
                f"AND reference_id IN ({placeholders})",
                sell_lot_ids,
            )
            cur.execute("DELETE FROM sell_lots WHERE buy_trade_id = ?", (trade_id,))

        # The buy's cash deduction references the trade id (no-op for sell rows).
        cur.execute(
            "DELETE FROM cash_pool WHERE transaction_type = 'buy_deduction' "
            "AND reference_id = ?",
            (trade_id,),
        )

        cur.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.commit()
        stats_cache.invalidate(existing[1])
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("delete_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete trade.")
    finally:
        conn.close()

    return {"detail": f"Trade {trade_id} deleted."}


# ---------------------------------------------------------------------------
# Sell lots
# ---------------------------------------------------------------------------

@app.post("/trades/{buy_trade_id}/sell", status_code=201)
def sell_trade(buy_trade_id: int, body: SellLotCreate):
    if body.quantity_sold <= 0:
        raise HTTPException(status_code=422, detail="quantity_sold must be greater than 0.")
    if body.sell_price_per_unit < 0:
        raise HTTPException(status_code=422, detail="sell_price_per_unit must be >= 0.")
    if body.commission is not None and body.commission < 0:
        raise HTTPException(status_code=422, detail="commission must be >= 0.")

    conn = _db()
    try:
        cur = conn.cursor()

        # 1. Fetch and validate the buy trade
        trade = _require_trade(cur, buy_trade_id)
        # indices: 0=id,1=user_id,2=ticker,3=trade_type,4=action,
        #          5=quantity,6=price_per_unit,7=total_value,8=trade_date,
        #          9=notes,10=created_at,11=status,12=remaining_quantity,
        #          13=broker_id,14=commission
        if trade[4] != "buy":
            raise HTTPException(status_code=400, detail="Trade is not a buy trade.")

        original_quantity = float(trade[5])
        buy_price         = float(trade[6])
        buy_broker_id     = trade[13]
        buy_commission    = float(trade[14] or 0)

        remaining = float(trade[12]) if trade[12] is not None else original_quantity
        if body.quantity_sold > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"quantity_sold ({body.quantity_sold}) exceeds remaining_quantity ({remaining}).",
            )

        # 3. Calculate proceeds, commissions, and commission-adjusted realized P&L.
        #    Sell commission: user override, else auto-calc from the buy trade's broker.
        #    Proportional buy commission: the share of the original buy commission
        #    attributable to the quantity being sold.
        proceeds        = round(body.quantity_sold * body.sell_price_per_unit, 10)
        sell_commission = _compute_commission(cur, buy_broker_id, body.quantity_sold, body.commission)
        prop_buy_commission = round(
            (body.quantity_sold / original_quantity) * buy_commission, 10
        ) if original_quantity else 0.0
        buy_cost_basis_for_lot = body.quantity_sold * buy_price
        realized_pnl = round(
            (proceeds - sell_commission) - (buy_cost_basis_for_lot + prop_buy_commission), 10
        )

        # 4. Insert sell_lot
        cur.execute(
            "INSERT INTO sell_lots "
            "(buy_trade_id, sell_date, quantity_sold, sell_price_per_unit, proceeds, realized_pnl, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                buy_trade_id, body.sell_date.isoformat(),
                body.quantity_sold, body.sell_price_per_unit,
                proceeds, realized_pnl, body.notes,
            ),
        )
        sell_lot_id = cur.lastrowid

        # 5. Update buy trade
        new_remaining = round(remaining - body.quantity_sold, 10)
        new_status = "closed" if new_remaining == 0 else "partial"
        cur.execute(
            "UPDATE trades SET remaining_quantity = ?, status = ? WHERE id = ?",
            (new_remaining, new_status, buy_trade_id),
        )

        # 6. Insert a sell trade record so it appears in the Trades tab.
        #    Sells net less, so net_total_value = proceeds - sell_commission.
        sell_net_total = round(proceeds - sell_commission, 10)
        cur.execute(
            "INSERT INTO trades "
            "(user_id, broker_id, ticker, trade_type, action, quantity, price_per_unit, "
            "total_value, trade_date, notes, status, remaining_quantity, commission, net_total_value) "
            "VALUES (?, ?, ?, ?, 'sell', ?, ?, ?, ?, ?, 'closed', 0, ?, ?)",
            (
                trade[1], trade[13], trade[2], trade[3],
                body.quantity_sold, body.sell_price_per_unit, proceeds,
                body.sell_date.isoformat(), body.notes, sell_commission, sell_net_total,
            ),
        )

        # 7. Insert cash_pool row. Credit the proceeds net of the sell commission,
        #    matching what the broker actually deposits.
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
            "VALUES (?, 'sell_proceeds', ?, ?)",
            (trade[1], sell_net_total, sell_lot_id),
        )

        conn.commit()
        stats_cache.invalidate(trade[1])

        cur.execute(
            "SELECT id, buy_trade_id, sell_date, quantity_sold, sell_price_per_unit, "
            "proceeds, realized_pnl, notes, created_at FROM sell_lots WHERE id = ?",
            (sell_lot_id,),
        )
        row = cur.fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("sell_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to record sell lot.")
    finally:
        conn.close()

    return _row_to_sell_lot(row)


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/positions")
def get_positions(user_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        cur.execute(
            "SELECT id, ticker, trade_type, trade_date, remaining_quantity, price_per_unit, status "
            "FROM trades "
            "WHERE user_id = ? AND action = 'buy' AND status IN ('open', 'partial') "
            "ORDER BY ticker, trade_type, trade_date, id",
            (user_id,),
        )
        rows = cur.fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_positions DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch positions.")
    finally:
        conn.close()

    # Group by (ticker, trade_type) in insertion order
    groups: dict[tuple, dict] = {}
    for trade_id, ticker, trade_type, trade_date, remaining_qty, price_per_unit, status in rows:
        remaining_qty = float(remaining_qty)
        price_per_unit = float(price_per_unit)
        key = (ticker, trade_type)
        if key not in groups:
            groups[key] = {
                "ticker": ticker,
                "trade_type": trade_type,
                "total_remaining_quantity": 0.0,
                "total_cost_basis": 0.0,
                "lots": [],
            }
        g = groups[key]
        g["total_remaining_quantity"] += remaining_qty
        g["total_cost_basis"] += remaining_qty * price_per_unit
        g["lots"].append({
            "trade_id": trade_id,
            "trade_date": trade_date,
            "remaining_quantity": remaining_qty,
            "price_per_unit": price_per_unit,
            "status": status,
        })

    positions = []
    for g in groups.values():
        total_qty = g["total_remaining_quantity"]
        cost_basis = g["total_cost_basis"]
        positions.append({
            "ticker": g["ticker"],
            "trade_type": g["trade_type"],
            "total_remaining_quantity": round(total_qty, 10),
            "avg_cost_per_unit": round(cost_basis / total_qty, 10) if total_qty else 0.0,
            "total_cost_basis": round(cost_basis, 10),
            "lots": g["lots"],
        })

    return positions


# ---------------------------------------------------------------------------
# Cash pool
# ---------------------------------------------------------------------------

def _get_balance(cur: sqlite3.Cursor, user_id: int) -> float:
    cur.execute(
        "SELECT COALESCE(SUM(amount), 0.0) FROM cash_pool WHERE user_id = ?",
        (user_id,),
    )
    return float(cur.fetchone()[0])


@app.get("/users/{user_id}/cash")
def get_cash(
    user_id: int,
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
):
    # Shared filter clause for the page query and the COUNT query.
    where_sql = " WHERE user_id = ?"
    filter_params: list = [user_id]
    if transaction_type:
        where_sql += " AND transaction_type = ?"
        filter_params.append(transaction_type)

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)

        # Balance is always the SUM over ALL rows, independent of filter/paging.
        balance = _get_balance(cur, user_id)

        total_count = cur.execute(
            "SELECT COUNT(*) FROM cash_pool" + where_sql, filter_params
        ).fetchone()[0]

        query = (
            "SELECT id, transaction_type, amount, note, created_at, reference_id "
            "FROM cash_pool" + where_sql
        )
        params = list(filter_params)
        if cursor is not None:
            last_val, last_id = _decode_cursor(cursor)
            query += " AND (created_at, id) < (?, ?)"
            params.extend([last_val, last_id])
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit + 1)

        cur.execute(query, params)
        rows = cur.fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_cash DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch cash pool.")
    finally:
        conn.close()

    has_more = len(rows) > limit
    rows = rows[:limit]
    transactions = [
        {
            "id": r[0],
            "transaction_type": r[1],
            "amount": float(r[2]),
            "note": r[3],
            "created_at": r[4],
            "reference_id": r[5],
        }
        for r in rows
    ]

    next_cursor = None
    if has_more and transactions:
        last = transactions[-1]
        next_cursor = _encode_cursor(last["created_at"], last["id"])

    return {
        "balance": balance,
        "transactions": transactions,
        "total_count": int(total_count),
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


@app.post("/users/{user_id}/cash/deposit", status_code=201)
def deposit_cash(user_id: int, body: CashTransaction):
    if body.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be greater than 0.")

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, note) "
            "VALUES (?, 'deposit', ?, ?)",
            (user_id, body.amount, body.note),
        )
        conn.commit()
        balance = _get_balance(cur, user_id)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("deposit_cash DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to record deposit.")
    finally:
        conn.close()

    return {"balance": balance}


@app.post("/users/{user_id}/cash/withdraw", status_code=201)
def withdraw_cash(user_id: int, body: CashTransaction):
    if body.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be greater than 0.")

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        balance = _get_balance(cur, user_id)
        if body.amount > balance:
            raise HTTPException(
                status_code=400,
                detail=f"Withdrawal of {body.amount} exceeds current balance of {balance}.",
            )
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, note) "
            "VALUES (?, 'withdrawal', ?, ?)",
            (user_id, -body.amount, body.note),
        )
        conn.commit()
        balance = _get_balance(cur, user_id)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("withdraw_cash DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to record withdrawal.")
    finally:
        conn.close()

    return {"balance": balance}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/trades/export")
def export_trades(user_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        cur.execute(
            "SELECT id, ticker, trade_type, action, quantity, price_per_unit, "
            "total_value, trade_date, notes, created_at "
            "FROM trades WHERE user_id = ? ORDER BY trade_date DESC, id DESC",
            (user_id,),
        )
        rows = cur.fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("export_trades DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to export trades.")
    finally:
        conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "ticker", "trade_type", "action", "quantity",
                     "price_per_unit", "total_value", "trade_date", "notes", "created_at"])
    for r in rows:
        writer.writerow(r)

    filename = f"trades_user{user_id}_{datetime.date.today()}.csv"
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

# Each search bucket returns at most this many results per page.
_SEARCH_LIMIT = 20


def _bucket(results: list, has_more: bool, next_cursor) -> dict:
    return {"results": results, "has_more": has_more, "next_cursor": next_cursor}


def _search_trades_bucket(cur, user_id, like, cursor) -> dict:
    """Trades whose ticker / notes / trade_type / broker name match, newest first."""
    sql = (
        "SELECT t.id, t.user_id, t.ticker, t.trade_type, t.action, t.quantity, "
        "t.price_per_unit, t.trade_date, t.status, b.name "
        "FROM trades t LEFT JOIN brokers b ON t.broker_id = b.id "
        "WHERE t.user_id = ? AND ("
        "t.ticker LIKE ? OR t.notes LIKE ? OR t.trade_type LIKE ? OR b.name LIKE ?)"
    )
    params = [user_id, like, like, like, like]
    if cursor is not None:
        last_val, last_id = _decode_cursor(cursor)
        sql += " AND (t.trade_date, t.id) < (?, ?)"
        params.extend([last_val, last_id])
    sql += " ORDER BY t.trade_date DESC, t.id DESC LIMIT ?"
    params.append(_SEARCH_LIMIT + 1)

    cur.execute(sql, params)
    rows = cur.fetchall()
    has_more = len(rows) > _SEARCH_LIMIT
    rows = rows[:_SEARCH_LIMIT]
    results = [
        {
            "trade_id":       r[0],
            "user_id":        r[1],
            "ticker":         r[2],
            "trade_type":     r[3],
            "action":         r[4],
            "quantity":       float(r[5]),
            "price_per_unit": float(r[6]),
            "trade_date":     r[7],
            "status":         r[8],
            "broker_name":    r[9],
        }
        for r in rows
    ]
    next_cursor = (
        _encode_cursor(results[-1]["trade_date"], results[-1]["trade_id"])
        if has_more and results else None
    )
    return _bucket(results, has_more, next_cursor)


def _search_positions_bucket(cur, user_id, like, cursor) -> dict:
    """Open/partial buy lots whose ticker matches, grouped by (ticker, trade_type).

    Mirrors the grouping of get_positions: the same ticker held under two trade
    types is two distinct positions, not one merged row. Positions are aggregates
    with no row id, so the keyset runs on the (ticker, trade_type) tuple, stored
    in the cursor's last_val as a [ticker, trade_type] pair (last_id is unused)."""
    sql = (
        "SELECT ticker, trade_type, "
        "SUM(remaining_quantity) AS rem, "
        "SUM(remaining_quantity * price_per_unit) AS basis "
        "FROM trades "
        "WHERE user_id = ? AND action = 'buy' AND status IN ('open', 'partial') "
        "AND ticker LIKE ?"
    )
    params = [user_id, like]
    if cursor is not None:
        last_val, _ = _decode_cursor(cursor)
        last_ticker, last_type = last_val
        sql += " AND (ticker, trade_type) > (?, ?)"
        params.extend([last_ticker, last_type])
    sql += " GROUP BY ticker, trade_type ORDER BY ticker ASC, trade_type ASC LIMIT ?"
    params.append(_SEARCH_LIMIT + 1)

    cur.execute(sql, params)
    rows = cur.fetchall()
    has_more = len(rows) > _SEARCH_LIMIT
    rows = rows[:_SEARCH_LIMIT]
    results = []
    for r in rows:
        rem = float(r[2] or 0)
        basis = float(r[3] or 0)
        results.append({
            "ticker":                   r[0],
            "trade_type":               r[1],
            "total_remaining_quantity": round(rem, 10),
            "avg_cost_per_unit":        round(basis / rem, 10) if rem else 0.0,
            "total_cost_basis":         round(basis, 10),
        })
    next_cursor = (
        _encode_cursor([results[-1]["ticker"], results[-1]["trade_type"]], 0)
        if has_more and results else None
    )
    return _bucket(results, has_more, next_cursor)


def _search_cash_bucket(cur, user_id, like, cursor) -> dict:
    """Cash transactions whose note / transaction_type match, newest first."""
    sql = (
        "SELECT id, user_id, transaction_type, amount, note, created_at "
        "FROM cash_pool "
        "WHERE user_id = ? AND (note LIKE ? OR transaction_type LIKE ?)"
    )
    params = [user_id, like, like]
    if cursor is not None:
        last_val, last_id = _decode_cursor(cursor)
        sql += " AND (created_at, id) < (?, ?)"
        params.extend([last_val, last_id])
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(_SEARCH_LIMIT + 1)

    cur.execute(sql, params)
    rows = cur.fetchall()
    has_more = len(rows) > _SEARCH_LIMIT
    rows = rows[:_SEARCH_LIMIT]
    results = [
        {
            "id":               r[0],
            "user_id":          r[1],
            "transaction_type": r[2],
            "amount":           float(r[3]),
            "note":             r[4],
            "created_at":       r[5],
        }
        for r in rows
    ]
    next_cursor = (
        _encode_cursor(results[-1]["created_at"], results[-1]["id"])
        if has_more and results else None
    )
    return _bucket(results, has_more, next_cursor)


_SEARCH_BUCKETS = {
    "trades": _search_trades_bucket,
    "positions": _search_positions_bucket,
    "cash_transactions": _search_cash_bucket,
}


@app.get("/search")
def search(
    user_id: int,
    q: str = Query(...),
    type: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
):
    term = (q or "").strip()
    if len(term) < 2:
        raise HTTPException(status_code=400, detail="q must be at least 2 characters.")
    if type is not None and type not in _SEARCH_BUCKETS:
        raise HTTPException(
            status_code=422,
            detail=f"type must be one of: {', '.join(sorted(_SEARCH_BUCKETS))}.",
        )
    like = f"%{term}%"

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)

        if type is not None:
            # Fetch (more of) a single bucket — powers "View all X results".
            return {type: _SEARCH_BUCKETS[type](cur, user_id, like, cursor)}

        # Default: first page of every bucket.
        return {
            name: build(cur, user_id, like, None)
            for name, build in _SEARCH_BUCKETS.items()
        }
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("search DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Search failed.")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _fiscal_start_default(cur) -> int:
    """Read fiscal_year_start_month from app_settings, falling back to 1 (January)."""
    try:
        cur.execute("SELECT value FROM app_settings WHERE key = 'fiscal_year_start_month'")
        row = cur.fetchone()
        if row is not None:
            month = int(row[0])
            if 1 <= month <= 12:
                return month
    except (sqlite3.Error, ValueError, TypeError):
        pass
    return 1


@app.get("/users/{user_id}/stats")
def get_user_stats(
    user_id: int,
    fiscal_year_start_month: Optional[int] = Query(None, ge=1, le=12),
):
    # Only the default request (no explicit fiscal month) is cached; a cache hit
    # serves instantly without touching the database. An explicit override is
    # computed fresh and never read from or written to the cache.
    use_cache = fiscal_year_start_month is None
    if use_cache:
        cached = stats_cache.get_stats(user_id)
        if cached is not None:
            return cached

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)

        # Default the fiscal-year start to the configured app setting.
        if fiscal_year_start_month is None:
            fiscal_year_start_month = _fiscal_start_default(cur)

        # Current fiscal-year window [start, next start): if today is before the
        # start month, the fiscal year began in the previous calendar year.
        today = datetime.date.today()
        fy_year = today.year if today.month >= fiscal_year_start_month else today.year - 1
        fy_start = datetime.date(fy_year, fiscal_year_start_month, 1)
        fy_end = datetime.date(fy_year + 1, fiscal_year_start_month, 1)

        # Each metric is its own focused query — SQLite plans small targeted
        # queries better than one big multi-aggregate scan. Value aggregations use
        # net_total_value (commission-adjusted), falling back to total_value for any
        # legacy row where it is NULL.
        cur.execute("SELECT COUNT(*) FROM trades WHERE user_id = ?", (user_id,))
        total_trades = cur.fetchone()[0]

        cur.execute(
            "SELECT COALESCE(SUM(COALESCE(net_total_value, total_value)), 0) "
            "FROM trades WHERE user_id = ? AND action = 'buy'",
            (user_id,),
        )
        buy_volume = cur.fetchone()[0]

        cur.execute(
            "SELECT COALESCE(SUM(COALESCE(net_total_value, total_value)), 0) "
            "FROM trades WHERE user_id = ? AND action = 'sell'",
            (user_id,),
        )
        sell_volume = cur.fetchone()[0]

        cur.execute(
            "SELECT ticker FROM trades WHERE user_id = ? "
            "GROUP BY ticker ORDER BY COUNT(*) DESC LIMIT 1",
            (user_id,),
        )
        top_row = cur.fetchone()

        cur.execute(
            "SELECT trade_type, COUNT(*), SUM(COALESCE(net_total_value, total_value)) "
            "FROM trades WHERE user_id = ? "
            "GROUP BY trade_type ORDER BY trade_type",
            (user_id,),
        )
        by_type_rows = cur.fetchall()

        cur.execute(
            """
            SELECT strftime('%Y-%m', trade_date) AS month,
                   SUM(COALESCE(net_total_value, total_value)) AS volume
            FROM trades
            WHERE user_id = ?
              AND trade_date >= date('now', 'start of month', '-11 months')
            GROUP BY strftime('%Y-%m', trade_date)
            ORDER BY strftime('%Y-%m', trade_date)
            """,
            (user_id,),
        )
        monthly_rows = cur.fetchall()

        # Total commissions: every trade row carries its own commission (buy rows
        # hold the buy fee, synthetic sell rows hold the sell fee), so a single
        # SUM covers all trades and sell lots.
        cur.execute(
            "SELECT COALESCE(SUM(commission), 0) FROM trades WHERE user_id = ?",
            (user_id,),
        )
        total_commissions = cur.fetchone()[0]

        # Net realized P&L: sell_lots.realized_pnl is already net of both the sell
        # commission and the proportional buy commission.
        cur.execute(
            "SELECT COALESCE(SUM(sl.realized_pnl), 0) "
            "FROM sell_lots sl JOIN trades t ON sl.buy_trade_id = t.id "
            "WHERE t.user_id = ?",
            (user_id,),
        )
        net_realized_pnl = cur.fetchone()[0]

        # Total trade volume within the current fiscal-year window.
        cur.execute(
            "SELECT COALESCE(SUM(COALESCE(net_total_value, total_value)), 0) "
            "FROM trades WHERE user_id = ? AND trade_date >= ? AND trade_date < ?",
            (user_id, fy_start.isoformat(), fy_end.isoformat()),
        )
        this_fiscal_year_volume = cur.fetchone()[0]

    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_user_stats DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load stats.")
    finally:
        conn.close()

    result = {
        "total_trades":       int(total_trades),
        "buy_volume":         float(buy_volume),
        "sell_volume":        float(sell_volume),
        "net_position":       float(sell_volume) - float(buy_volume),
        "total_commissions":  float(total_commissions),
        "net_realized_pnl":   float(net_realized_pnl),
        "this_fiscal_year_volume": float(this_fiscal_year_volume),
        "fiscal_year_start":  fy_start.isoformat(),
        "most_traded_ticker": top_row[0] if top_row else None,
        "by_trade_type": [
            {"trade_type": r[0], "trade_count": int(r[1]), "volume": float(r[2])}
            for r in by_type_rows
        ],
        "monthly_volume": [
            {"month": r[0], "volume": float(r[1])}
            for r in monthly_rows
        ],
        "last_computed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }

    if use_cache:
        stats_cache.set_stats(user_id, result)
    return result


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/stats/growth")
def get_user_growth(
    user_id: int,
    date_from: Optional[str] = Query(
        None,
        description="ISO date; omit for the last year, pass '' for all history.",
    ),
):
    # Resolve the window:
    #   param omitted  -> default first-load view of the last year
    #   param == ''    -> everything (the "All" button)
    #   ISO date       -> only points on/after that date
    if date_from is None:
        cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    elif date_from == "":
        cutoff = None
    else:
        try:
            cutoff = datetime.date.fromisoformat(date_from).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from must be an ISO date (YYYY-MM-DD).")

    # The full (unfiltered) growth series is cached per user; date_from only slices
    # it in Python, so changing the window never re-runs the aggregation.
    full = stats_cache.get_growth(user_id)
    if full is None:
        conn = _db()
        try:
            cur = conn.cursor()
            _require_user(cur, user_id)

            # Both series are running totals over time, so instead of recomputing a
            # full SUM for every event date (O(dates × trades) — the old correlated
            # subqueries), collapse each side to a per-date delta in one pass and
            # accumulate in Python below. A buy contributes a fixed amount on its
            # trade_date (its current remaining value, for open/partial lots); a sell
            # contributes its realized P&L on its sell_date.
            cur.execute(
                """
                WITH user_buys AS (
                    SELECT trade_date, remaining_quantity, net_total_value,
                           total_value, commission, quantity, status
                    FROM   trades
                    WHERE  user_id = ? AND action = 'buy'
                ),
                user_sells AS (
                    SELECT sl.sell_date AS sell_date, sl.realized_pnl AS realized_pnl
                    FROM   sell_lots sl
                    JOIN   trades    t ON sl.buy_trade_id = t.id
                    WHERE  t.user_id = ?
                )
                SELECT date, SUM(cost_basis_delta) AS cost_basis_delta,
                             SUM(realized_pnl_delta) AS realized_pnl_delta
                FROM (
                    SELECT trade_date AS date,
                           SUM(CASE WHEN status IN ('open', 'partial')
                                    THEN remaining_quantity
                                         * COALESCE(net_total_value, total_value + commission)
                                         / NULLIF(quantity, 0)
                                    ELSE 0 END) AS cost_basis_delta,
                           0.0 AS realized_pnl_delta
                    FROM   user_buys
                    GROUP  BY trade_date
                    UNION ALL
                    SELECT sell_date AS date,
                           0.0 AS cost_basis_delta,
                           SUM(realized_pnl) AS realized_pnl_delta
                    FROM   user_sells
                    GROUP  BY sell_date
                )
                GROUP BY date
                ORDER BY date
                """,
                (user_id, user_id),
            )
            rows = cur.fetchall()
        except HTTPException:
            raise
        except sqlite3.Error as exc:
            logger.error("get_user_growth DB error: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to load growth data.")
        finally:
            conn.close()

        # Accumulate the per-date deltas into the running cost-basis / realized-P&L
        # series. Equivalent to the old cumulative SUMs, but single-pass.
        full = []
        cost_basis = 0.0
        realized_pnl = 0.0
        for date, cb_delta, pnl_delta in rows:
            cost_basis   += cb_delta or 0.0
            realized_pnl += pnl_delta or 0.0
            full.append({
                "date":         date,
                "cost_basis":   cost_basis,
                "realized_pnl": realized_pnl,
            })
        stats_cache.set_growth(user_id, full)

    if cutoff is None:
        return full
    # Rows are ordered by date; ISO date strings compare correctly lexicographically.
    return [pt for pt in full if pt["date"] >= cutoff]
