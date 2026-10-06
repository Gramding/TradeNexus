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
from common import (
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
    trade_currency = ((body.trade_currency or instr_currency or _base_currency(cur)) or "USD").strip().upper()
    fx_rate        = _resolve_fx(conn, cur, trade_currency, body.fx_rate)

    commission      = _compute_commission(cur, body.broker_id, body.quantity, body.commission)
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
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
            "VALUES (?, 'buy_deduction', ?, ?)",
            (user_id, -net_total_base, trade_id),
        )
    else:
        # Short open (sell-to-open): credit the proceeds net of commission, as the
        # broker deposits the sale proceeds into the account. The liability to buy
        # the shares back is tracked by the open short lot, not the cash pool.
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
            "VALUES (?, 'sell_proceeds', ?, ?)",
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
        trade_date     = _dt_to_storage(body.trade_date)    if body.trade_date     is not None else existing[8]
        notes          = body.notes                         if body.notes          is not None else existing[9]
        broker_id      = body.broker_id                     if body.broker_id      is not None else existing[13]

        # Multiplier: explicit override wins; else re-resolve when the trade_type
        # changed (so switching to/from Call/Put updates the 100x); otherwise keep
        # the stored multiplier. total_value always reflects the current multiplier.
        existing_multiplier  = float(existing[15]) if existing[15] is not None else 1.0
        existing_strike      = existing[16]
        existing_expiration  = existing[17]
        existing_underlying  = existing[18]
        if body.multiplier is not None:
            multiplier = _resolve_multiplier(trade_type, body.multiplier)
        elif body.trade_type is not None:
            multiplier = _resolve_multiplier(trade_type, None)
        else:
            multiplier = existing_multiplier
        total_value    = round(quantity * price_per_unit * multiplier, 10)

        # Commission: explicit override wins; else recompute when broker or quantity
        # changed; otherwise keep the existing value untouched.
        if body.commission is not None:
            commission = round(float(body.commission), 10)
        elif body.broker_id is not None or body.quantity is not None:
            commission = _compute_commission(cur, broker_id, quantity, None)
        else:
            commission = float(existing[14] or 0)
        net_total_value = _net_total(action, total_value, commission)

        # FX: an explicit override wins; otherwise keep the trade's stored rate.
        # trade_currency is not edited here. net_total_base drives the cash pool.
        existing_fx     = float(existing[21]) if existing[21] is not None else 1.0
        fx_rate         = _resolve_fx(conn, cur, existing[20] or "USD", body.fx_rate) if body.fx_rate is not None else existing_fx
        net_total_base  = round(net_total_value * fx_rate, 10)

        # Option metadata: each field is replaced only when supplied, else preserved.
        strike_price    = body.strike_price                          if body.strike_price    is not None else existing_strike
        expiration_date = (body.expiration_date.isoformat()
                           if body.expiration_date is not None else existing_expiration)
        underlying      = (body.underlying.strip().upper()
                           if body.underlying else existing_underlying)

        cur.execute(
            "UPDATE trades SET ticker=?, trade_type=?, action=?, quantity=?, "
            "price_per_unit=?, total_value=?, trade_date=?, notes=?, broker_id=?, "
            "commission=?, net_total_value=?, multiplier=?, strike_price=?, "
            "expiration_date=?, underlying=?, fx_rate=? WHERE id=?",
            (ticker, trade_type, action, quantity, price_per_unit, total_value, trade_date, notes, broker_id,
             commission, net_total_value, multiplier, strike_price, expiration_date, underlying, fx_rate, trade_id),
        )

        # Keep the cash pool in sync with the edit. An opening trade has exactly one
        # cash row keyed by its trade_id: a long open's buy_deduction (negative) or a
        # short open's sell_proceeds (positive). Drop and re-insert that one row for
        # the new net total. Close-side cash rows are keyed by sell-lot id and left
        # untouched. The row type follows the trade's direction (not editable here),
        # so the delete stays scoped to this trade's own open-side row.
        direction = existing[19] or "long"
        open_cash_type = "sell_proceeds" if direction == "short" else "buy_deduction"
        cur.execute(
            "DELETE FROM cash_pool WHERE transaction_type = ? AND reference_id = ?",
            (open_cash_type, trade_id),
        )
        if direction == "short":
            cur.execute(
                "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
                "VALUES (?, 'sell_proceeds', ?, ?)",
                (existing[1], net_total_base, trade_id),
            )
        else:
            cur.execute(
                "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
                "VALUES (?, 'buy_deduction', ?, ?)",
                (existing[1], -net_total_base, trade_id),
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


@router.delete("/trades/{trade_id}")
def delete_trade(trade_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        existing = _require_trade(cur, trade_id)

        # Remove dependent rows before the trade itself, so the sell_lots -> trades
        # foreign key doesn't block the delete, and reverse this trade's cash-pool
        # effects so the balance stays correct. This handles both long opens (closed
        # by sells) and short opens (closed by covers): the close ledger lives in
        # sell_lots keyed by this opening trade's id either way.
        sell_lot_ids = [
            r[0] for r in cur.execute(
                "SELECT id FROM sell_lots WHERE buy_trade_id = ?", (trade_id,)
            ).fetchall()
        ]
        if sell_lot_ids:
            placeholders = ",".join("?" * len(sell_lot_ids))
            # Close-side cash rows reference the sell_lot id: sell_proceeds when a
            # long was sold, buy_deduction when a short was covered.
            cur.execute(
                f"DELETE FROM cash_pool WHERE reference_id IN ({placeholders}) "
                f"AND transaction_type IN ('sell_proceeds', 'buy_deduction')",
                sell_lot_ids,
            )
            cur.execute("DELETE FROM sell_lots WHERE buy_trade_id = ?", (trade_id,))

        # The opening trade's own cash row references the trade id: a long open's
        # buy_deduction or a short open's sell_proceeds.
        direction = existing[19] or "long"
        open_cash_type = "sell_proceeds" if direction == "short" else "buy_deduction"
        cur.execute(
            "DELETE FROM cash_pool WHERE transaction_type = ? AND reference_id = ?",
            (open_cash_type, trade_id),
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
        if trade[4] != "buy":
            raise HTTPException(status_code=400, detail="Trade is not a buy trade.")

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
        sell_fx           = _resolve_fx(conn, cur, trade_currency, body.fx_rate)

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
        sell_commission = _compute_commission(cur, buy_broker_id, body.quantity_sold, body.commission)
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
            "multiplier, trade_currency, fx_rate) "
            "VALUES (?, ?, ?, ?, 'sell', ?, ?, ?, ?, ?, 'closed', 0, ?, ?, ?, ?, ?)",
            (
                trade[1], trade[13], trade[2], trade[3],
                body.quantity_sold, body.sell_price_per_unit, proceeds,
                body.sell_date.isoformat(), body.notes, sell_commission, sell_net_total,
                multiplier, trade_currency, sell_fx,
            ),
        )

        # 7. Insert cash_pool row in base currency: credit the proceeds net of the
        #    sell commission, converted at the sell-leg fx rate.
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
            "VALUES (?, 'sell_proceeds', ?, ?)",
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
        cover_fx          = _resolve_fx(conn, cur, trade_currency, body.fx_rate)

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
        cover_commission = _compute_commission(cur, short_broker_id, body.quantity_covered, body.commission)
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
            "multiplier, direction, trade_currency, fx_rate) "
            "VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, 'closed', 0, ?, ?, ?, 'short', ?, ?)",
            (
                trade[1], trade[13], trade[2], trade[3],
                body.quantity_covered, body.cover_price_per_unit, cover_cost,
                body.cover_date.isoformat(), body.notes, cover_commission, cover_net_total,
                multiplier, trade_currency, cover_fx,
            ),
        )

        # Debit the buy-back cost (net of commission) from the cash pool in base
        # currency, keyed to the cover lot id (mirrors how a long sell credits it).
        cur.execute(
            "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id) "
            "VALUES (?, 'buy_deduction', ?, ?)",
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
