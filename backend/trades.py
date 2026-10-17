"""Trade routes: CRUD, bulk add, sell / cover against open lots, CSV export."""
import csv
import datetime
import io
import logging
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import stats_cache
from price_service import normalize_currency
from common import (
    _is_close_row,
    ACTIONS,
    _base_currency,
    _cached_total_count,
    _compute_commission,
    _db,
    _decode_cursor,
    DIRECTIONS,
    _dt_to_storage,
    _encode_cursor,
    _net_total,
    _normalize_trade_type,
    _require_broker,
    _require_instrument,
    _require_trade,
    _require_user,
    _resolve_face_value,
    _resolve_fx,
    _resolve_multiplier,
    _row_to_sell_lot,
    _row_to_trade,
    _TRADE_SELECT,
    _TRADE_SORT_COLUMNS,
    _validate_iso_date,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["trades"])


class TradeCreate(BaseModel):
    ticker: str
    trade_type: str
    action: str
    quantity: float
    price_per_unit: float
    trade_date: datetime.datetime  # full timestamp; a date-only value coerces to midnight
    notes: Optional[str] = None
    broker_id: Optional[int] = None
    commission: Optional[float] = None  # None = auto-calc from broker
    instrument_id: Optional[int] = None  # set when picked from the instrument search
    multiplier: Optional[float] = None   # None = auto (100 for Call/Put, else 1)
    strike_price: Optional[float] = None     # options only
    expiration_date: Optional[datetime.date] = None  # options only
    underlying: Optional[str] = None         # options only, e.g. "AAPL"
    direction: Optional[str] = None      # long (buy-to-open) or short (sell-to-open); inferred from action if omitted
    trade_currency: Optional[str] = None  # native currency; defaults to the instrument's, else base
    fx_rate: Optional[float] = None       # trade_currency -> base; None = auto fetch
    face_value: Optional[float] = None        # bonds: par per bond (default 1000 for Bond)
    coupon_rate: Optional[float] = None       # bonds: annual coupon rate, %
    coupon_frequency: Optional[int] = None    # bonds: payments per year (1, 2, 4, 12)
    maturity_date: Optional[datetime.date] = None  # bonds: maturity date
    accrued_interest: Optional[float] = None  # bonds: accrued paid at purchase, in trade_currency


class BulkTradeCreate(TradeCreate):
    # Same trade fields as TradeCreate, applied to every user in user_ids.
    user_ids: List[int]


class TradeUpdate(BaseModel):
    ticker: Optional[str] = None
    trade_type: Optional[str] = None
    action: Optional[str] = None
    quantity: Optional[float] = None
    price_per_unit: Optional[float] = None
    trade_date: Optional[datetime.datetime] = None  # full timestamp; date-only coerces to midnight
    notes: Optional[str] = None
    broker_id: Optional[int] = None
    commission: Optional[float] = None
    multiplier: Optional[float] = None
    strike_price: Optional[float] = None
    expiration_date: Optional[datetime.date] = None
    underlying: Optional[str] = None
    fx_rate: Optional[float] = None
    face_value: Optional[float] = None
    coupon_rate: Optional[float] = None
    coupon_frequency: Optional[int] = None
    maturity_date: Optional[datetime.date] = None
    accrued_interest: Optional[float] = None


class SellLotCreate(BaseModel):
    quantity_sold: float
    sell_price_per_unit: float
    sell_date: datetime.date
    notes: Optional[str] = None
    commission: Optional[float] = None  # None = auto-calc from the buy trade's broker
    fx_rate: Optional[float] = None     # sell-leg trade_currency -> base; None = auto


class CoverCreate(BaseModel):
    """Buy-to-close against an open short lot."""
    quantity_covered: float
    cover_price_per_unit: float
    cover_date: datetime.date
    notes: Optional[str] = None
    commission: Optional[float] = None  # None = auto-calc from the short trade's broker
    fx_rate: Optional[float] = None     # cover-leg trade_currency -> base; None = auto



# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/trades")
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
        # trade_date now carries a time, so an inclusive day filter must cover the
        # whole day — compare against end-of-day, not bare 'YYYY-MM-DD' (which would
        # drop any same-day trade with a non-midnight time). Keeps the index usable.
        where_sql += " AND t.trade_date <= ?"
        filter_params.append(f"{date_to} 23:59:59")

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


def _validate_trade_body(body) -> str:
    """Validate the user-independent fields of an opening-trade body and return the
    resolved direction. Shared by create_trade and the bulk endpoint.

    An opening trade's direction is inferred from its action (buy = long,
    sell = short to open) unless explicitly given, in which case the two must
    agree. Closing a position is done via the /sell and /cover endpoints, so an
    opening trade only ever opens a long or a short.
    """
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
    if body.strike_price is not None and body.strike_price < 0:
        raise HTTPException(status_code=422, detail="strike_price must be >= 0.")

    inferred_direction = "long" if body.action == "buy" else "short"
    direction = (body.direction or inferred_direction)
    if direction not in DIRECTIONS:
        raise HTTPException(status_code=422, detail=f"direction must be one of: {', '.join(sorted(DIRECTIONS))}.")
    if direction != inferred_direction:
        raise HTTPException(
            status_code=422,
            detail="direction must be 'long' for a buy and 'short' for a sell. "
                   "Close existing positions with the sell/cover actions.",
        )
    return direction


def _create_trade_row(conn, cur: sqlite3.Cursor, user_id: int, body, direction: str) -> int:
    """Insert one opening trade plus its cash-pool row for user_id, using an
    already-open cursor. Does NOT commit or invalidate the stats cache — the caller
    owns the transaction so a single create and a bulk fan-out share this code path.
    Assumes body has already passed _validate_trade_body. Returns the new trade id.
    """
    _require_user(cur, user_id)
    trade_type = _normalize_trade_type(cur, body.trade_type)
    if body.broker_id is not None:
        _require_broker(cur, body.broker_id)
    instr_currency = None
    if body.instrument_id is not None:
        _require_instrument(cur, body.instrument_id)
        row = cur.execute("SELECT currency FROM instruments WHERE id = ?", (body.instrument_id,)).fetchone()
        instr_currency = row[0] if row else None

    # total_value is the full notional: per-unit price × quantity × contract
    # multiplier (100 for an equity option, face_value/100 for a bond, 1 for
    # a share). Every downstream value (net_total_value, cash deduction, stats
    # volume) derives from this.
    face_value  = _resolve_face_value(trade_type, body.face_value)
    multiplier  = _resolve_multiplier(trade_type, body.multiplier, face_value)
    total_value = round(body.quantity * body.price_per_unit * multiplier, 10)
    expiration  = body.expiration_date.isoformat() if body.expiration_date is not None else None
    underlying  = body.underlying.strip().upper() if body.underlying else None
    maturity    = body.maturity_date.isoformat() if body.maturity_date is not None else None
    accrued     = round(float(body.accrued_interest), 10) if body.accrued_interest else 0.0
    if accrued < 0:
        raise HTTPException(status_code=422, detail="accrued_interest must be >= 0.")

    # Native currency: explicit > the instrument's > the base currency. fx_rate
    # converts the native amounts into base; the cash pool is kept in base.
    trade_currency = normalize_currency(body.trade_currency or instr_currency or _base_currency(cur)) or "USD"
    fx_rate        = _resolve_fx(conn, cur, trade_currency, body.fx_rate)

    commission      = _compute_commission(conn, cur, body.broker_id, body.quantity, body.commission,
                                          trade_currency, fx_rate)
    net_total_value = _net_total(body.action, total_value, commission)
    # Bonds: the buyer pays accrued interest on top of the clean price; the
    # seller receives it. Bundled into the cash flow so the broker's debit
    # matches reality, but kept out of total_value/cost basis so realized P&L
    # reflects principal gain/loss only.
    cash_native     = net_total_value + (accrued if body.action == "buy" else -accrued)
    net_total_base  = round(cash_native * fx_rate, 10)

    cur.execute(
        "INSERT INTO trades "
        "(user_id, broker_id, instrument_id, ticker, trade_type, action, quantity, price_per_unit, "
        "total_value, trade_date, notes, remaining_quantity, commission, net_total_value, "
        "multiplier, strike_price, expiration_date, underlying, direction, trade_currency, fx_rate, "
        "face_value, coupon_rate, coupon_frequency, maturity_date, accrued_interest) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id, body.broker_id, body.instrument_id, body.ticker.strip().upper(),
            trade_type, body.action, body.quantity, body.price_per_unit, total_value,
            _dt_to_storage(body.trade_date), body.notes, body.quantity,
            commission, net_total_value,
            multiplier, body.strike_price, expiration, underlying, direction,
            trade_currency, fx_rate,
            face_value, body.coupon_rate, body.coupon_frequency, maturity, accrued,
        ),
    )
    trade_id = cur.lastrowid

    if body.action == "buy":
        # Long open: deduct the commission-inclusive net (in base currency) so the
        # cash pool matches what the broker actually debits (gross cost + commission
        # + bond accrued interest).
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id, reference_kind) "
            "VALUES (?, 'buy_deduction', ?, ?, 'trade')",
            (user_id, -net_total_base, trade_id),
        )
    else:
        # Short open (sell-to-open): credit the proceeds net of commission, as the
        # broker deposits the sale proceeds into the account. The liability to buy
        # the shares back is tracked by the open short lot, not the cash pool.
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id, reference_kind) "
            "VALUES (?, 'sell_proceeds', ?, ?, 'trade')",
            (user_id, net_total_base, trade_id),
        )

    return trade_id


@router.post("/users/{user_id}/trades", status_code=201)
def create_trade(user_id: int, body: TradeCreate):
    direction = _validate_trade_body(body)

    conn = _db()
    try:
        cur = conn.cursor()
        trade_id = _create_trade_row(conn, cur, user_id, body, direction)
        conn.commit()
        stats_cache.invalidate(user_id)
        cur.execute(_TRADE_SELECT + " WHERE t.id = ?", (trade_id,))
        row = cur.fetchone()
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("create_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create trade.")
    finally:
        conn.close()

    return _row_to_trade(row)


@router.post("/trades/bulk", status_code=201)
def bulk_create_trades(body: BulkTradeCreate):
    """Apply one identical opening trade to several users at once. All-or-nothing:
    every user's trade is inserted in a single transaction, so if any one fails
    validation (unknown user, broker, trade type, …) nothing is written."""
    if not body.user_ids:
        raise HTTPException(status_code=422, detail="Select at least one user.")
    # Dedupe while preserving order so a repeated id can't double-insert for a user.
    user_ids = list(dict.fromkeys(body.user_ids))
    direction = _validate_trade_body(body)

    conn = _db()
    created = []
    try:
        cur = conn.cursor()
        for uid in user_ids:
            trade_id = _create_trade_row(conn, cur, uid, body, direction)
            created.append({"user_id": uid, "trade_id": trade_id})
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("bulk_create_trades DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create trades.")
    finally:
        conn.close()

    for item in created:
        stats_cache.invalidate(item["user_id"])
    return {"created": created, "count": len(created)}


def _fields_set(body) -> set:
    """Fields the client actually sent (an explicit null counts), on pydantic v1 or v2."""
    fields = getattr(body, "model_fields_set", None)
    return set(fields if fields is not None else body.__fields_set__)


def _norm_stored_dt(value) -> str:
    """Stored trade dates are 'YYYY-MM-DD HH:MM:SS'; sale and cover rows store a
    bare 'YYYY-MM-DD'. Normalize so the two compare equal to an edit's value."""
    v = (value or "").strip()
    return f"{v} 00:00:00" if len(v) == 10 else v


def _differs(new, old, tol: float = 1e-9) -> bool:
    if new is None:
        return False
    if old is None:
        return True
    return abs(float(new) - float(old)) > tol


def _changed_fields(conn, cur: sqlite3.Cursor, body: "TradeUpdate", existing: tuple) -> set:
    """Names of the trade fields this edit actually changes. The edit form sends
    every field, so presence alone says nothing; values are compared instead."""
    changed = set()
    if body.ticker is not None and body.ticker.strip().upper() != existing[2]:
        changed.add("ticker")
    if body.trade_type is not None and _normalize_trade_type(cur, body.trade_type) != existing[3]:
        changed.add("trade_type")
    if body.action is not None and body.action != existing[4]:
        changed.add("action")
    if _differs(body.quantity, existing[5]):
        changed.add("quantity")
    if _differs(body.price_per_unit, existing[6]):
        changed.add("price_per_unit")
    if body.trade_date is not None and _dt_to_storage(body.trade_date) != _norm_stored_dt(existing[8]):
        changed.add("trade_date")
    if body.broker_id is not None and body.broker_id != existing[13]:
        changed.add("broker_id")
    if "commission" in _fields_set(body):
        new_commission = body.commission
        if new_commission is None:   # explicit null = back to the broker's auto commission
            new_commission = _compute_commission(
                conn, cur, body.broker_id if body.broker_id is not None else existing[13],
                body.quantity if body.quantity is not None else float(existing[5]),
                None, existing[20], body.fx_rate or existing[21],
            )
        if _differs(new_commission, existing[14], tol=0.005):
            changed.add("commission")
    if _differs(body.multiplier, existing[15]):
        changed.add("multiplier")
    if _differs(body.strike_price, existing[16]):
        changed.add("strike_price")
    if body.expiration_date is not None and body.expiration_date.isoformat() != existing[17]:
        changed.add("expiration_date")
    if body.underlying is not None and body.underlying.strip().upper() != (existing[18] or ""):
        changed.add("underlying")
    if _differs(body.fx_rate, existing[21]):
        changed.add("fx_rate")
    if _differs(body.accrued_interest, existing[22]):
        changed.add("accrued_interest")
    return changed


# Fields that can change on a position that already has sales or covers against
# it. Everything else feeds the realized P&L already booked on those closes.
_EDITABLE_WITH_CLOSES = {"trade_date", "strike_price", "expiration_date", "underlying"}


@router.put("/trades/{trade_id}")
def update_trade(trade_id: int, body: TradeUpdate):
    if body.action is not None and body.action not in ACTIONS:
        raise HTTPException(status_code=422, detail=f"action must be one of: {', '.join(sorted(ACTIONS))}.")
    if body.quantity is not None and body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be greater than 0.")
    if body.price_per_unit is not None and body.price_per_unit < 0:
        raise HTTPException(status_code=422, detail="price_per_unit must be >= 0.")
    if body.commission is not None and body.commission < 0:
        raise HTTPException(status_code=422, detail="commission must be >= 0.")
    if body.strike_price is not None and body.strike_price < 0:
        raise HTTPException(status_code=422, detail="strike_price must be >= 0.")
    if body.ticker is not None and not body.ticker.strip():
        raise HTTPException(status_code=422, detail="Ticker cannot be empty.")
    if body.accrued_interest is not None and body.accrued_interest < 0:
        raise HTTPException(status_code=422, detail="accrued_interest must be >= 0.")

    conn = _db()
    try:
        cur = conn.cursor()
        existing = _require_trade(cur, trade_id)
        user_id   = existing[1]
        direction = existing[19] or "long"
        if body.broker_id is not None:
            _require_broker(cur, body.broker_id)

        changed = _changed_fields(conn, cur, body, existing)
        if "action" in changed:
            raise HTTPException(
                status_code=422,
                detail="A trade can't be switched between buy and sell. Delete it and add it again.",
            )

        # A sale or cover row: its numbers are booked into a sell lot, the opening
        # position and the cash pool, so only the note can change here.
        if _is_close_row(existing[4], direction):
            if changed:
                raise HTTPException(
                    status_code=409,
                    detail="This row records a sale or cover and can't be edited. "
                           "Delete it to undo the sale, then record it again.",
                )
            if body.notes is not None:
                cur.execute("UPDATE trades SET notes = ? WHERE id = ?", (body.notes, trade_id))
                if existing[23] is not None:
                    cur.execute("UPDATE sell_lots SET notes = ? WHERE id = ?", (body.notes, existing[23]))
            conn.commit()
            stats_cache.invalidate(user_id)
            row = cur.execute(_TRADE_SELECT + " WHERE t.id = ?", (trade_id,)).fetchone()
            return _row_to_trade(row)

        close_count = cur.execute(
            "SELECT COUNT(*) FROM sell_lots WHERE buy_trade_id = ?", (trade_id,)
        ).fetchone()[0]
        locked = changed - _EDITABLE_WITH_CLOSES
        if close_count and locked:
            raise HTTPException(
                status_code=409,
                detail=f"This position has {close_count} sale(s) or cover(s) recorded against it. "
                       f"Delete those first to change: {', '.join(sorted(locked))}.",
            )

        ticker         = body.ticker.strip().upper() if body.ticker is not None else existing[2]
        trade_type     = _normalize_trade_type(cur, body.trade_type) if body.trade_type is not None else existing[3]
        action         = existing[4]
        old_quantity   = float(existing[5])
        quantity       = body.quantity                      if body.quantity       is not None else old_quantity
        price_per_unit = body.price_per_unit                if body.price_per_unit is not None else float(existing[6])
        trade_date     = _dt_to_storage(body.trade_date)    if body.trade_date     is not None else existing[8]
        notes          = body.notes                         if body.notes          is not None else existing[9]
        broker_id      = body.broker_id                     if body.broker_id      is not None else existing[13]
        trade_currency = existing[20] or "USD"
        accrued        = (round(float(body.accrued_interest), 10) if body.accrued_interest is not None
                          else float(existing[22] or 0))

        # Open quantity follows the edit: with no closes recorded, remaining moves
        # by the same amount as quantity (splits scale both together).
        remaining = round(float(existing[12] if existing[12] is not None else old_quantity)
                          + (quantity - old_quantity), 10)

        # Multiplier: explicit override wins; else re-resolve when the trade_type
        # changed (so switching to/from Call/Put updates the 100x); otherwise keep
        # the stored multiplier. total_value always reflects the current multiplier.
        existing_multiplier  = float(existing[15]) if existing[15] is not None else 1.0
        if body.multiplier is not None:
            multiplier = _resolve_multiplier(trade_type, body.multiplier)
        elif "trade_type" in changed:
            multiplier = _resolve_multiplier(trade_type, None)
        else:
            multiplier = existing_multiplier
        total_value    = round(quantity * price_per_unit * multiplier, 10)

        # FX: an explicit override wins; otherwise keep the trade's stored rate.
        existing_fx     = float(existing[21]) if existing[21] is not None else 1.0
        fx_rate         = _resolve_fx(conn, cur, trade_currency, body.fx_rate) if body.fx_rate is not None else existing_fx

        # Commission: an explicit value wins; an explicit null (or a changed broker
        # or quantity) re-derives the broker's commission; otherwise keep it.
        if body.commission is not None:
            commission = round(float(body.commission), 10)
        elif "commission" in _fields_set(body) or "broker_id" in changed or "quantity" in changed:
            commission = _compute_commission(conn, cur, broker_id, quantity, None, trade_currency, fx_rate)
        else:
            commission = float(existing[14] or 0)
        net_total_value = _net_total(action, total_value, commission)
        # Same cash rule as on create: bond accrued interest rides on the cash leg.
        cash_native     = net_total_value + (accrued if action == "buy" else -accrued)
        net_total_base  = round(cash_native * fx_rate, 10)

        strike_price    = body.strike_price if body.strike_price is not None else existing[16]
        expiration_date = (body.expiration_date.isoformat()
                           if body.expiration_date is not None else existing[17])
        underlying      = (body.underlying.strip().upper()
                           if body.underlying else existing[18])

        cur.execute(
            "UPDATE trades SET ticker=?, trade_type=?, quantity=?, remaining_quantity=?, "
            "price_per_unit=?, total_value=?, trade_date=?, notes=?, broker_id=?, "
            "commission=?, net_total_value=?, multiplier=?, strike_price=?, "
            "expiration_date=?, underlying=?, fx_rate=?, accrued_interest=? WHERE id=?",
            (ticker, trade_type, quantity, remaining, price_per_unit, total_value, trade_date,
             notes, broker_id, commission, net_total_value, multiplier, strike_price,
             expiration_date, underlying, fx_rate, accrued, trade_id),
        )

        # Re-post this opening trade's own cash row (a long's debit or a short's
        # credit) for the new totals. Scoped by kind and user so it can never touch
        # another row that happens to share the same reference id.
        cur.execute(
            "DELETE FROM cash_pool WHERE reference_kind = 'trade' AND reference_id = ? AND user_id = ?",
            (trade_id, user_id),
        )
        if direction == "short":
            cur.execute(
                "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id, reference_kind) "
                "VALUES (?, 'sell_proceeds', ?, ?, 'trade')",
                (user_id, net_total_base, trade_id),
            )
        else:
            cur.execute(
                "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id, reference_kind) "
                "VALUES (?, 'buy_deduction', ?, ?, 'trade')",
                (user_id, -net_total_base, trade_id),
            )

        conn.commit()
        stats_cache.invalidate(user_id)
        cur.execute(_TRADE_SELECT + " WHERE t.id = ?", (trade_id,))
        row = cur.fetchone()
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("update_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update trade.")
    finally:
        conn.close()

    return _row_to_trade(row)


def _unlinked_close_has_lot(cur: sqlite3.Cursor, close_row: tuple) -> bool:
    """For a close row with no sell_lot_id (recorded before the link existed and
    not matched by the migration): is there still a sell lot it could belong to?
    If not, the row is an orphan left behind by an earlier delete."""
    lot_dir = "long" if close_row[4] == "sell" else "short"
    return cur.execute(
        "SELECT 1 FROM sell_lots sl JOIN trades t ON sl.buy_trade_id = t.id "
        "WHERE t.user_id = ? AND COALESCE(t.direction, 'long') = ? "
        "AND ABS(sl.quantity_sold - ?) < 1e-9 AND ABS(sl.sell_price_per_unit - ?) < 1e-9 "
        "AND date(sl.sell_date) = date(?) "
        "AND NOT EXISTS (SELECT 1 FROM trades c WHERE c.sell_lot_id = sl.id) LIMIT 1",
        (close_row[1], lot_dir, close_row[5], close_row[6], close_row[8]),
    ).fetchone() is not None


@router.delete("/trades/{trade_id}")
def delete_trade(trade_id: int):
    """Delete an opening trade together with everything recorded against it, or
    undo a single sale / cover (delete its close row) and give the quantity back
    to the position."""
    conn = _db()
    try:
        cur = conn.cursor()
        existing = _require_trade(cur, trade_id)
        user_id   = existing[1]
        direction = existing[19] or "long"

        if _is_close_row(existing[4], direction):
            _undo_close(cur, existing)
        else:
            # Everything closed against this position: the sell lots, their close
            # rows and their cash rows. Then the opening trade and its own cash row.
            lot_ids = [r[0] for r in cur.execute(
                "SELECT id FROM sell_lots WHERE buy_trade_id = ?", (trade_id,)
            ).fetchall()]
            if lot_ids:
                marks = ",".join("?" * len(lot_ids))
                cur.execute(
                    f"DELETE FROM cash_pool WHERE reference_kind = 'sell_lot' "
                    f"AND reference_id IN ({marks}) AND user_id = ?",
                    lot_ids + [user_id],
                )
                cur.execute(f"DELETE FROM trades WHERE sell_lot_id IN ({marks})", lot_ids)
                cur.execute("DELETE FROM sell_lots WHERE buy_trade_id = ?", (trade_id,))
            cur.execute(
                "DELETE FROM cash_pool WHERE reference_kind = 'trade' AND reference_id = ? AND user_id = ?",
                (trade_id, user_id),
            )
            cur.execute("DELETE FROM trades WHERE id = ?", (trade_id,))

        conn.commit()
        stats_cache.invalidate(user_id)
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("delete_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete trade.")
    finally:
        conn.close()

    return {"detail": f"Trade {trade_id} deleted."}


def _undo_close(cur: sqlite3.Cursor, close_row: tuple) -> None:
    """Reverse one sale or cover: drop its sell lot, close row and cash row, and
    return the quantity to the opening position."""
    trade_id, user_id = close_row[0], close_row[1]
    lot_id = close_row[23]
    lot = None
    if lot_id is not None:
        lot = cur.execute(
            "SELECT buy_trade_id, quantity_sold, sell_date FROM sell_lots WHERE id = ?", (lot_id,)
        ).fetchone()
    elif _unlinked_close_has_lot(cur, close_row):
        raise HTTPException(
            status_code=409,
            detail="This sale was recorded by an older version and isn't linked to its position, "
                   "so it can't be undone on its own. Delete the opening trade instead.",
        )

    if lot is None:
        # Orphan close row (its sell lot is already gone): just remove it.
        cur.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        return

    buy_trade_id, quantity_sold, sell_date = lot
    opening = _require_trade(cur, buy_trade_id)
    instrument_id = opening[24]
    if instrument_id is not None:
        later_split = cur.execute(
            "SELECT 1 FROM events WHERE user_id = ? AND instrument_id = ? AND event_type = 'split' "
            "AND date(event_date) > date(?) LIMIT 1",
            (user_id, instrument_id, sell_date),
        ).fetchone()
        if later_split:
            raise HTTPException(
                status_code=409,
                detail="A stock split was recorded after this sale. Delete the split first, then undo the sale.",
            )

    original_qty = float(opening[5])
    remaining = round(float(opening[12] or 0) + float(quantity_sold), 10)
    status = "open" if abs(remaining - original_qty) < 1e-9 else "partial"
    cur.execute(
        "UPDATE trades SET remaining_quantity = ?, status = ? WHERE id = ?",
        (remaining, status, buy_trade_id),
    )
    cur.execute(
        "DELETE FROM cash_pool WHERE reference_kind = 'sell_lot' AND reference_id = ? AND user_id = ?",
        (lot_id, user_id),
    )
    cur.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    cur.execute("DELETE FROM sell_lots WHERE id = ?", (lot_id,))


# ---------------------------------------------------------------------------
# Sell lots
# ---------------------------------------------------------------------------

@router.post("/trades/{buy_trade_id}/sell", status_code=201)
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
        if not (trade[4] == "buy" and (trade[19] or "long") == "long"):
            raise HTTPException(status_code=400, detail="Trade is not an open long position.")

        original_quantity = float(trade[5])
        buy_price         = float(trade[6])
        buy_broker_id     = trade[13]
        buy_commission    = float(trade[14] or 0)
        # The sell inherits the buy lot's contract multiplier so proceeds and cost
        # basis are scaled by the same factor (e.g. 100 for an equity option).
        multiplier        = float(trade[15]) if trade[15] is not None else 1.0
        trade_currency    = trade[20] or "USD"
        buy_fx            = float(trade[21]) if trade[21] is not None else 1.0
        # The sell leg converts at its own rate (FX may have moved since the buy),
        # which captures currency gain/loss in the realized P&L.
        sell_fx           = _resolve_fx(conn, cur, trade_currency, body.fx_rate, fallback=buy_fx)

        remaining = float(trade[12]) if trade[12] is not None else original_quantity
        if body.quantity_sold > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"quantity_sold ({body.quantity_sold}) exceeds remaining_quantity ({remaining}).",
            )

        # 3. Calculate proceeds, commissions, and commission-adjusted realized P&L.
        #    Sell commission: user override, else auto-calc from the buy trade's broker.
        #    Proportional buy commission: the share of the original buy commission
        #    attributable to the quantity being sold. Proceeds and cost basis both
        #    include the contract multiplier so option P&L is in real dollars.
        #    realized_pnl is stored in BASE currency: each leg converts at its own
        #    fx_rate, so a foreign position's currency move is part of the result.
        proceeds        = round(body.quantity_sold * body.sell_price_per_unit * multiplier, 10)
        sell_commission = _compute_commission(conn, cur, buy_broker_id, body.quantity_sold, body.commission,
                                              trade_currency, sell_fx)
        prop_buy_commission = round(
            (body.quantity_sold / original_quantity) * buy_commission, 10
        ) if original_quantity else 0.0
        buy_cost_basis_for_lot = body.quantity_sold * buy_price * multiplier
        realized_pnl = round(
            (proceeds - sell_commission) * sell_fx
            - (buy_cost_basis_for_lot + prop_buy_commission) * buy_fx, 10
        )

        # 4. Insert sell_lot (realized_pnl already in base currency)
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
        #    Sells net less, so net_total_value = proceeds - sell_commission. The
        #    sell leg's fx_rate is stored so stats convert this row to base too.
        sell_net_total = round(proceeds - sell_commission, 10)
        cur.execute(
            "INSERT INTO trades "
            "(user_id, broker_id, ticker, trade_type, action, quantity, price_per_unit, "
            "total_value, trade_date, notes, status, remaining_quantity, commission, net_total_value, "
            "multiplier, trade_currency, fx_rate, instrument_id, sell_lot_id) "
            "VALUES (?, ?, ?, ?, 'sell', ?, ?, ?, ?, ?, 'closed', 0, ?, ?, ?, ?, ?, ?, ?)",
            (
                trade[1], trade[13], trade[2], trade[3],
                body.quantity_sold, body.sell_price_per_unit, proceeds,
                body.sell_date.isoformat(), body.notes, sell_commission, sell_net_total,
                multiplier, trade_currency, sell_fx, trade[24], sell_lot_id,
            ),
        )

        # 7. Insert cash_pool row in base currency: credit the proceeds net of the
        #    sell commission, converted at the sell-leg fx rate.
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id, reference_kind) "
            "VALUES (?, 'sell_proceeds', ?, ?, 'sell_lot')",
            (trade[1], round(sell_net_total * sell_fx, 10), sell_lot_id),
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


@router.post("/trades/{short_trade_id}/cover", status_code=201)
def cover_trade(short_trade_id: int, body: CoverCreate):
    """Buy-to-close against an open short lot — the mirror image of sell_trade.

    Realized P&L for a short is the open proceeds (what you received selling the
    borrowed shares) minus the cost to buy them back, both net of commission, so
    a lower cover price is a profit. Proceeds, cost, and basis all carry the
    contract multiplier. The close is recorded in sell_lots (the shared realized-
    P&L ledger) keyed by the short opening trade's id."""
    if body.quantity_covered <= 0:
        raise HTTPException(status_code=422, detail="quantity_covered must be greater than 0.")
    if body.cover_price_per_unit < 0:
        raise HTTPException(status_code=422, detail="cover_price_per_unit must be >= 0.")
    if body.commission is not None and body.commission < 0:
        raise HTTPException(status_code=422, detail="commission must be >= 0.")

    conn = _db()
    try:
        cur = conn.cursor()
        trade = _require_trade(cur, short_trade_id)
        # indices: 4=action 5=quantity 6=price_per_unit 12=remaining_quantity
        #          13=broker_id 14=commission 15=multiplier 19=direction
        if not (trade[4] == "sell" and (trade[19] or "long") == "short"):
            raise HTTPException(status_code=400, detail="Trade is not an open short position.")

        original_quantity = float(trade[5])
        open_price        = float(trade[6])
        short_broker_id   = trade[13]
        open_commission   = float(trade[14] or 0)
        multiplier        = float(trade[15]) if trade[15] is not None else 1.0
        trade_currency    = trade[20] or "USD"
        open_fx           = float(trade[21]) if trade[21] is not None else 1.0
        cover_fx          = _resolve_fx(conn, cur, trade_currency, body.fx_rate, fallback=open_fx)

        remaining = float(trade[12]) if trade[12] is not None else original_quantity
        if body.quantity_covered > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"quantity_covered ({body.quantity_covered}) exceeds remaining_quantity ({remaining}).",
            )

        # Cost to buy the shares back, the open proceeds attributable to this slice,
        # and both commission legs. Profit when the open price beat the cover price.
        # realized_pnl is in BASE currency: the open leg converts at the short's
        # stored fx, the cover leg at its own.
        cover_cost      = round(body.quantity_covered * body.cover_price_per_unit * multiplier, 10)
        cover_commission = _compute_commission(conn, cur, short_broker_id, body.quantity_covered,
                                               body.commission, trade_currency, cover_fx)
        prop_open_commission = round(
            (body.quantity_covered / original_quantity) * open_commission, 10
        ) if original_quantity else 0.0
        open_proceeds_for_lot = body.quantity_covered * open_price * multiplier
        realized_pnl = round(
            (open_proceeds_for_lot - prop_open_commission) * open_fx
            - (cover_cost + cover_commission) * cover_fx, 10
        )

        # Record the close in sell_lots. proceeds stores the buy-back cost here;
        # realized_pnl is the field stats reads, and it is already short-correct.
        cur.execute(
            "INSERT INTO sell_lots "
            "(buy_trade_id, sell_date, quantity_sold, sell_price_per_unit, proceeds, realized_pnl, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                short_trade_id, body.cover_date.isoformat(),
                body.quantity_covered, body.cover_price_per_unit,
                cover_cost, realized_pnl, body.notes,
            ),
        )
        cover_lot_id = cur.lastrowid

        new_remaining = round(remaining - body.quantity_covered, 10)
        new_status = "closed" if new_remaining == 0 else "partial"
        cur.execute(
            "UPDATE trades SET remaining_quantity = ?, status = ? WHERE id = ?",
            (new_remaining, new_status, short_trade_id),
        )

        # Synthetic buy-to-close trade so the cover shows in the Trades tab. It is a
        # buy that nets MORE cash out (cost + commission), and carries direction
        # 'short' so it is never mistaken for a long open by the positions queries.
        cover_net_total = round(cover_cost + cover_commission, 10)
        cur.execute(
            "INSERT INTO trades "
            "(user_id, broker_id, ticker, trade_type, action, quantity, price_per_unit, "
            "total_value, trade_date, notes, status, remaining_quantity, commission, net_total_value, "
            "multiplier, direction, trade_currency, fx_rate, instrument_id, sell_lot_id) "
            "VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, 'closed', 0, ?, ?, ?, 'short', ?, ?, ?, ?)",
            (
                trade[1], trade[13], trade[2], trade[3],
                body.quantity_covered, body.cover_price_per_unit, cover_cost,
                body.cover_date.isoformat(), body.notes, cover_commission, cover_net_total,
                multiplier, trade_currency, cover_fx, trade[24], cover_lot_id,
            ),
        )

        # Debit the buy-back cost (net of commission) from the cash pool in base
        # currency, keyed to the cover lot id (mirrors how a long sell credits it).
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id, reference_kind) "
            "VALUES (?, 'buy_deduction', ?, ?, 'sell_lot')",
            (trade[1], round(-cover_net_total * cover_fx, 10), cover_lot_id),
        )

        conn.commit()
        stats_cache.invalidate(trade[1])

        cur.execute(
            "SELECT id, buy_trade_id, sell_date, quantity_sold, sell_price_per_unit, "
            "proceeds, realized_pnl, notes, created_at FROM sell_lots WHERE id = ?",
            (cover_lot_id,),
        )
        row = cur.fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("cover_trade DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to record cover lot.")
    finally:
        conn.close()

    return _row_to_sell_lot(row)



# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/trades/export")
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
