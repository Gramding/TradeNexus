"""Global search across trades, positions and cash transactions."""
import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from common import (
    _db,
    _decode_cursor,
    _encode_cursor,
    _require_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


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
    """Open/partial lots (long opens + short opens) whose ticker matches, grouped
    by (ticker, trade_type, direction).

    Mirrors get_positions: the same ticker held in two trade types or in opposite
    directions is two distinct positions, not one merged row. Positions are
    aggregates with no row id, so the keyset runs on the (ticker, trade_type,
    direction) tuple stored in the cursor's last_val (last_id is unused)."""
    sql = (
        "SELECT ticker, trade_type, direction, "
        "SUM(remaining_quantity) AS rem, "
        "SUM(remaining_quantity * price_per_unit) AS raw_cost, "
        "SUM(remaining_quantity * price_per_unit * multiplier) AS basis "
        "FROM trades "
        "WHERE user_id = ? AND status IN ('open', 'partial') "
        "AND ((action = 'buy' AND direction = 'long') OR (action = 'sell' AND direction = 'short')) "
        "AND ticker LIKE ?"
    )
    params = [user_id, like]
    if cursor is not None:
        last_val, _ = _decode_cursor(cursor)
        last_ticker, last_type, last_dir = last_val
        sql += " AND (ticker, trade_type, direction) > (?, ?, ?)"
        params.extend([last_ticker, last_type, last_dir])
    sql += " GROUP BY ticker, trade_type, direction ORDER BY ticker ASC, trade_type ASC, direction ASC LIMIT ?"
    params.append(_SEARCH_LIMIT + 1)

    cur.execute(sql, params)
    rows = cur.fetchall()
    has_more = len(rows) > _SEARCH_LIMIT
    rows = rows[:_SEARCH_LIMIT]
    results = []
    for r in rows:
        rem = float(r[3] or 0)
        raw_cost = float(r[4] or 0)
        basis = float(r[5] or 0)
        results.append({
            "ticker":                   r[0],
            "trade_type":               r[1],
            "direction":                r[2] or "long",
            "total_remaining_quantity": round(rem, 10),
            "avg_cost_per_unit":        round(raw_cost / rem, 10) if rem else 0.0,
            "total_cost_basis":         round(basis, 10),
        })
    next_cursor = (
        _encode_cursor([results[-1]["ticker"], results[-1]["trade_type"], results[-1]["direction"]], 0)
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


@router.get("/search")
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
