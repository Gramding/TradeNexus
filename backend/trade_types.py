import logging
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["trade-types"])

MAX_NAME_LEN = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    try:
        return get_connection()
    except sqlite3.OperationalError as exc:
        logger.error("DB open failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not open the database.")


def _row_to_type(r) -> dict:
    return {"id": r[0], "name": r[1], "is_default": int(r[2]), "usage_count": int(r[3])}


# A single row joined with its usage count (number of trades using its name).
_SELECT = (
    "SELECT tt.id, tt.name, tt.is_default, "
    "(SELECT COUNT(*) FROM trades WHERE trades.trade_type = tt.name) AS usage_count "
    "FROM trade_types tt"
)


def _fetch_one(cur: sqlite3.Cursor, type_id: int):
    cur.execute(_SELECT + " WHERE tt.id = ?", (type_id,))
    return cur.fetchone()


def _require_type(cur: sqlite3.Cursor, type_id: int):
    row = _fetch_one(cur, type_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Trade type {type_id} not found.")
    return row


def _validate_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise HTTPException(status_code=422, detail="name cannot be empty.")
    if len(n) > MAX_NAME_LEN:
        raise HTTPException(status_code=422, detail=f"name must be at most {MAX_NAME_LEN} characters.")
    return n


def _name_taken(cur: sqlite3.Cursor, name: str, exclude_id=None) -> bool:
    if exclude_id is None:
        cur.execute("SELECT 1 FROM trade_types WHERE LOWER(name) = LOWER(?)", (name,))
    else:
        cur.execute(
            "SELECT 1 FROM trade_types WHERE LOWER(name) = LOWER(?) AND id <> ?",
            (name, exclude_id),
        )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TradeTypeBody(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/trade-types")
def list_trade_types():
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + " ORDER BY tt.is_default DESC, tt.name ASC")
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        logger.error("list_trade_types DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch trade types.")
    finally:
        conn.close()
    return [_row_to_type(r) for r in rows]


@router.post("/trade-types", status_code=201)
def create_trade_type(body: TradeTypeBody):
    name = _validate_name(body.name)
    conn = _db()
    try:
        cur = conn.cursor()
        if _name_taken(cur, name):
            raise HTTPException(status_code=409, detail="A trade type with that name already exists.")
        cur.execute(
            "INSERT INTO trade_types (name, is_default) VALUES (?, 0)",
            (name,),
        )
        conn.commit()
        row = _fetch_one(cur, cur.lastrowid)
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=409, detail="A trade type with that name already exists.")
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("create_trade_type DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create trade type.")
    finally:
        conn.close()
    return _row_to_type(row)


@router.put("/trade-types/{type_id}")
def update_trade_type(type_id: int, body: TradeTypeBody):
    name = _validate_name(body.name)
    conn = _db()
    try:
        cur = conn.cursor()
        existing = _require_type(cur, type_id)
        old_name = existing[1]

        if _name_taken(cur, name, exclude_id=type_id):
            raise HTTPException(status_code=409, detail="A trade type with that name already exists.")

        # Single transaction: rename the type and re-point every trade that used it.
        cur.execute("UPDATE trade_types SET name = ? WHERE id = ?", (name, type_id))
        cur.execute("UPDATE trades SET trade_type = ? WHERE trade_type = ?", (name, old_name))
        trades_updated = cur.rowcount
        conn.commit()

        row = _fetch_one(cur, type_id)
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=409, detail="A trade type with that name already exists.")
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("update_trade_type DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update trade type.")
    finally:
        conn.close()

    result = _row_to_type(row)
    result["trades_updated"] = trades_updated
    return result


@router.delete("/trade-types/{type_id}")
def delete_trade_type(type_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        row = _require_type(cur, type_id)
        is_default, usage_count = int(row[2]), int(row[3])

        if is_default == 1:
            raise HTTPException(status_code=400, detail="Default trade types cannot be deleted.")
        if usage_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete — {usage_count} trades use this type. Reassign them first.",
            )

        cur.execute("DELETE FROM trade_types WHERE id = ?", (type_id,))
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("delete_trade_type DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete trade type.")
    finally:
        conn.close()

    return {"detail": f"Trade type {type_id} deleted."}
