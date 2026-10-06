"""Corporate and account events: dividends, splits, interest, fees."""
import datetime
import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import stats_cache
from common import (
    _base_currency,
    _db,
    _dt_to_storage,
    _require_instrument,
    _require_user,
    _resolve_fx,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])


# ---------------------------------------------------------------------------
# Events: dividends, splits, interest, fees
# ---------------------------------------------------------------------------

EVENT_TYPES = {"dividend", "split", "interest", "fee"}

# How each event posts to the cash pool (split has no cash effect).
_EVENT_CASH_TYPE = {"dividend": "dividend", "interest": "interest", "fee": "fee"}


class EventCreate(BaseModel):
    event_type: str
    event_date: datetime.datetime  # full timestamp; a date-only value coerces to midnight
    instrument_id: Optional[int] = None
    ticker: Optional[str] = None        # free-text fallback when instrument_id is None
    amount: Optional[float] = None      # dividend: per-share; interest/fee: total
    ratio: Optional[float] = None       # split only: new/old (2.0 = 2-for-1, 0.5 = 1-for-2 reverse)
    currency: Optional[str] = None      # native; defaults to instrument's, else base
    fx_rate: Optional[float] = None     # native -> base; None = auto
    note: Optional[str] = None


def _shares_held(cur: sqlite3.Cursor, user_id: int, instrument_id: int, on_date: str) -> float:
    """Long-lot shares of `instrument_id` the user holds on `on_date`. Dividends
    pay only on open long quantity; shorts and closed lots are excluded."""
    cur.execute(
        "SELECT COALESCE(SUM(remaining_quantity), 0) FROM trades "
        "WHERE user_id = ? AND instrument_id = ? "
        "AND action = 'buy' AND direction = 'long' "
        "AND status IN ('open', 'partial') AND date(trade_date) <= date(?)",
        (user_id, instrument_id, on_date),
    )
    return float(cur.fetchone()[0] or 0)


def _apply_split(cur: sqlite3.Cursor, user_id: int, instrument_id: int, ratio: float, on_date: str) -> int:
    """Scale every open lot of `instrument_id` by `ratio`: quantity and
    remaining_quantity multiply, price_per_unit divides, total_value invariant
    (q * p * multiplier stays equal). Closed sell_lots are realized history and
    untouched. Returns the number of lots adjusted."""
    cur.execute(
        "SELECT id, quantity, remaining_quantity, price_per_unit FROM trades "
        "WHERE user_id = ? AND instrument_id = ? "
        "AND action = 'buy' AND direction = 'long' "
        "AND status IN ('open', 'partial') AND date(trade_date) <= date(?)",
        (user_id, instrument_id, on_date),
    )
    rows = cur.fetchall()
    for trade_id, qty, rem, price in rows:
        new_qty   = round(float(qty) * ratio, 10)
        new_rem   = round(float(rem) * ratio, 10)
        new_price = round(float(price) / ratio, 10)
        cur.execute(
            "UPDATE trades SET quantity = ?, remaining_quantity = ?, price_per_unit = ? WHERE id = ?",
            (new_qty, new_rem, new_price, trade_id),
        )
    return len(rows)


def _event_to_row(r) -> dict:
    return {
        "id":            r[0],
        "user_id":       r[1],
        "instrument_id": r[2],
        "event_type":    r[3],
        "event_date":    r[4],
        "amount":        float(r[5]) if r[5] is not None else None,
        "ratio":         float(r[6]) if r[6] is not None else None,
        "currency":      r[7],
        "fx_rate":       float(r[8]) if r[8] is not None else 1.0,
        "note":          r[9],
        "created_at":    r[10],
        "ticker":        r[11],   # joined from instruments when present
    }


_EVENT_SELECT = (
    "SELECT e.id, e.user_id, e.instrument_id, e.event_type, e.event_date, "
    "e.amount, e.ratio, e.currency, e.fx_rate, e.note, e.created_at, i.ticker "
    "FROM events e LEFT JOIN instruments i ON e.instrument_id = i.id"
)


@router.post("/users/{user_id}/events", status_code=201)
def create_event(user_id: int, body: EventCreate):
    """Record a dividend, split, interest, or fee event.

    dividend : per-share `amount` × shares held on `event_date` (long only),
               credited to the cash pool in base currency. instrument required.
    split    : multiplies every open long lot's quantity by `ratio` and divides
               its price_per_unit, so total notional is invariant. No cash move.
    interest : flat `amount` credited to cash. instrument optional.
    fee      : flat `amount` debited from cash. instrument optional."""
    if body.event_type not in EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"event_type must be one of: {', '.join(sorted(EVENT_TYPES))}.")
    if body.event_type in ("dividend", "split") and body.instrument_id is None:
        raise HTTPException(status_code=422, detail=f"{body.event_type} requires instrument_id.")
    if body.event_type == "split":
        if body.ratio is None or body.ratio <= 0:
            raise HTTPException(status_code=422, detail="split ratio must be > 0 (e.g. 2.0 for 2-for-1, 0.5 for 1-for-2).")
    else:
        if body.amount is None or body.amount <= 0:
            raise HTTPException(status_code=422, detail=f"{body.event_type} amount must be > 0.")

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        instr_currency = None
        if body.instrument_id is not None:
            _require_instrument(cur, body.instrument_id)
            row = cur.execute("SELECT currency FROM instruments WHERE id = ?", (body.instrument_id,)).fetchone()
            instr_currency = row[0] if row else None

        currency = ((body.currency or instr_currency or _base_currency(cur)) or "USD").strip().upper()
        fx_rate  = _resolve_fx(conn, cur, currency, body.fx_rate)
        event_date_iso = _dt_to_storage(body.event_date)

        cur.execute(
            "INSERT INTO events (user_id, instrument_id, event_type, event_date, "
            "amount, ratio, currency, fx_rate, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, body.instrument_id, body.event_type, event_date_iso,
             body.amount, body.ratio, currency, fx_rate, body.note),
        )
        event_id = cur.lastrowid

        if body.event_type == "split":
            _apply_split(cur, user_id, body.instrument_id, float(body.ratio), event_date_iso)
        else:
            # Cash effect in base currency. Dividends are paid on the long shares
            # held on event_date; interest/fee are total amounts entered by the user.
            if body.event_type == "dividend":
                shares = _shares_held(cur, user_id, body.instrument_id, event_date_iso)
                gross_native = round(float(body.amount) * shares, 10)
            else:
                gross_native = round(float(body.amount), 10)
            signed_base = round(gross_native * fx_rate * (-1 if body.event_type == "fee" else 1), 10)
            cur.execute(
                "INSERT INTO cash_pool (user_id, transaction_type, amount, reference_id, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, _EVENT_CASH_TYPE[body.event_type], signed_base, event_id, body.note),
            )

        conn.commit()
        stats_cache.invalidate(user_id)
        row = cur.execute(_EVENT_SELECT + " WHERE e.id = ?", (event_id,)).fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("create_event DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to record event.")
    finally:
        conn.close()
    return _event_to_row(row)


@router.get("/users/{user_id}/events")
def list_events(user_id: int, event_type: Optional[str] = Query(None)):
    if event_type is not None and event_type not in EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"event_type must be one of: {', '.join(sorted(EVENT_TYPES))}.")
    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        sql = _EVENT_SELECT + " WHERE e.user_id = ?"
        params: list = [user_id]
        if event_type is not None:
            sql += " AND e.event_type = ?"
            params.append(event_type)
        sql += " ORDER BY e.event_date DESC, e.id DESC"
        rows = cur.execute(sql, params).fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("list_events DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load events.")
    finally:
        conn.close()
    return [_event_to_row(r) for r in rows]


@router.delete("/events/{event_id}")
def delete_event(event_id: int):
    """Reverse an event: remove its cash row (dividend/interest/fee), or undo a
    split by inverting the ratio on all open lots of that instrument."""
    conn = _db()
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT user_id, instrument_id, event_type, event_date, ratio "
            "FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")
        user_id, instrument_id, event_type, event_date, ratio = row

        if event_type == "split":
            # Inverting the ratio reverses the in-place adjustment exactly, provided
            # no later lots were opened post-split — those would get an unwanted
            # inverse, so we reject that case rather than corrupt state.
            after = cur.execute(
                "SELECT COUNT(*) FROM trades WHERE user_id = ? AND instrument_id = ? "
                "AND action = 'buy' AND direction = 'long' AND date(trade_date) > date(?)",
                (user_id, instrument_id, event_date),
            ).fetchone()[0]
            if after:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot delete a split that has trades dated after it; reverse them first.",
                )
            _apply_split(cur, user_id, instrument_id, 1.0 / float(ratio), event_date)
        else:
            cur.execute(
                "DELETE FROM cash_pool WHERE transaction_type = ? AND reference_id = ?",
                (_EVENT_CASH_TYPE[event_type], event_id),
            )

        cur.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        stats_cache.invalidate(user_id)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("delete_event DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete event.")
    finally:
        conn.close()
    return {"detail": f"Event {event_id} deleted."}
