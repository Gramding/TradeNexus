"""User routes: list, create, delete."""
import logging
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import stats_cache
from common import (
    _db,
    _require_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["users"])


class UserCreate(BaseModel):
    name: str
    email: str


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users")
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


@router.post("/users", status_code=201)
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


@router.delete("/users/{user_id}")
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
