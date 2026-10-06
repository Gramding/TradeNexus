"""Cash pool routes: balance, ledger, deposits and withdrawals."""
import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from common import (
    _db,
    _decode_cursor,
    _encode_cursor,
    _require_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cash"])


class CashTransaction(BaseModel):
    amount: float
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Cash pool
# ---------------------------------------------------------------------------

def _get_balance(cur: sqlite3.Cursor, user_id: int) -> float:
    cur.execute(
        "SELECT COALESCE(SUM(amount), 0.0) FROM cash_pool WHERE user_id = ?",
        (user_id,),
    )
    return float(cur.fetchone()[0])


@router.get("/users/{user_id}/cash")
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


@router.post("/users/{user_id}/cash/deposit", status_code=201)
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


@router.post("/users/{user_id}/cash/withdraw", status_code=201)
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
