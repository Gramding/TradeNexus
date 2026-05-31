import json
import logging
import re
import sqlite3
from typing import Optional

_HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["brokers"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    try:
        return get_connection()
    except sqlite3.OperationalError as exc:
        logger.error("DB open failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not open the database.")


def _require_broker(cur: sqlite3.Cursor, broker_id: int) -> tuple:
    # Columns: 0=id 1=name 2=price_source 3=color
    #          4=commission_flat 5=commission_per_unit 6=commission_currency
    #          7=notes 8=created_at
    cur.execute(
        "SELECT id, name, price_source, color, "
        "commission_flat, commission_per_unit, commission_currency, "
        "notes, created_at FROM brokers WHERE id = ?",
        (broker_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Broker {broker_id} not found.")
    return row


def _row_to_broker(r) -> dict:
    return {
        "id":                   r[0],
        "name":                 r[1],
        "price_source":         r[2],
        "color":                r[3],
        "commission_flat":      float(r[4]) if r[4] is not None else 0.0,
        "commission_per_unit":  float(r[5]) if r[5] is not None else 0.0,
        "commission_currency":  r[6] or "USD",
        "notes":                r[7],
        "created_at":           r[8],
    }


def _validate_color(color: Optional[str]) -> Optional[str]:
    if color is None:
        return None
    if not _HEX_COLOR.match(color):
        raise HTTPException(status_code=422, detail="color must be a 6-digit hex value like '#ff5733'.")
    return color


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class BrokerCreate(BaseModel):
    name: str
    price_source: str = "yahoo_finance"
    color: Optional[str] = None
    commission_flat: float = 0.0
    commission_per_unit: float = 0.0
    commission_currency: str = "USD"
    notes: Optional[str] = None
    config: Optional[dict] = None


class BrokerUpdate(BaseModel):
    name: Optional[str] = None
    price_source: Optional[str] = None
    color: Optional[str] = None
    commission_flat: Optional[float] = None
    commission_per_unit: Optional[float] = None
    commission_currency: Optional[str] = None
    notes: Optional[str] = None
    config: Optional[dict] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/brokers")
def list_brokers():
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, price_source, color, "
            "commission_flat, commission_per_unit, commission_currency, "
            "notes, created_at FROM brokers ORDER BY name"
        )
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        logger.error("list_brokers DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch brokers.")
    finally:
        conn.close()
    return [_row_to_broker(r) for r in rows]


@router.post("/brokers", status_code=201)
def create_broker(body: BrokerCreate):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name cannot be empty.")
    if not body.price_source.strip():
        raise HTTPException(status_code=422, detail="price_source cannot be empty.")
    if body.commission_flat < 0:
        raise HTTPException(status_code=422, detail="commission_flat must be >= 0.")
    if body.commission_per_unit < 0:
        raise HTTPException(status_code=422, detail="commission_per_unit must be >= 0.")

    color      = _validate_color(body.color)
    config_str = json.dumps(body.config) if body.config is not None else None

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO brokers "
            "(name, price_source, color, commission_flat, commission_per_unit, commission_currency, config, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (body.name.strip(), body.price_source.strip(), color,
             body.commission_flat, body.commission_per_unit, body.commission_currency,
             config_str, body.notes),
        )
        conn.commit()
        row = _require_broker(cur, cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="A broker with that name already exists.")
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("create_broker DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create broker.")
    finally:
        conn.close()
    return _row_to_broker(row)


@router.put("/brokers/{broker_id}")
def update_broker(broker_id: int, body: BrokerUpdate):
    if body.name is not None and not body.name.strip():
        raise HTTPException(status_code=422, detail="name cannot be empty.")
    if body.price_source is not None and not body.price_source.strip():
        raise HTTPException(status_code=422, detail="price_source cannot be empty.")

    if body.commission_flat is not None and body.commission_flat < 0:
        raise HTTPException(status_code=422, detail="commission_flat must be >= 0.")
    if body.commission_per_unit is not None and body.commission_per_unit < 0:
        raise HTTPException(status_code=422, detail="commission_per_unit must be >= 0.")

    color = _validate_color(body.color)

    conn = _db()
    try:
        cur = conn.cursor()
        # Columns: 0=id 1=name 2=price_source 3=color
        #          4=commission_flat 5=commission_per_unit 6=commission_currency
        #          7=config 8=notes
        cur.execute(
            "SELECT id, name, price_source, color, "
            "commission_flat, commission_per_unit, commission_currency, config, notes "
            "FROM brokers WHERE id = ?",
            (broker_id,),
        )
        existing = cur.fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Broker {broker_id} not found.")

        name                = body.name.strip()         if body.name                is not None else existing[1]
        price_source        = body.price_source.strip() if body.price_source        is not None else existing[2]
        color               = color if body.color is not None else existing[3]
        commission_flat     = body.commission_flat     if body.commission_flat     is not None else float(existing[4] or 0)
        commission_per_unit = body.commission_per_unit if body.commission_per_unit is not None else float(existing[5] or 0)
        commission_currency = body.commission_currency if body.commission_currency is not None else (existing[6] or "USD")
        config_str          = json.dumps(body.config)  if body.config              is not None else existing[7]
        notes               = body.notes               if body.notes               is not None else existing[8]

        cur.execute(
            "UPDATE brokers SET name=?, price_source=?, color=?, "
            "commission_flat=?, commission_per_unit=?, commission_currency=?, "
            "config=?, notes=? WHERE id=?",
            (name, price_source, color,
             commission_flat, commission_per_unit, commission_currency,
             config_str, notes, broker_id),
        )
        conn.commit()
        row = _require_broker(cur, broker_id)
    except HTTPException:
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="A broker with that name already exists.")
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("update_broker DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update broker.")
    finally:
        conn.close()
    return _row_to_broker(row)


@router.delete("/brokers/{broker_id}")
def delete_broker(broker_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        _require_broker(cur, broker_id)

        cur.execute("SELECT COUNT(*) FROM trades WHERE broker_id = ?", (broker_id,))
        count = int(cur.fetchone()[0])
        if count:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete: {count} trade{'s' if count != 1 else ''} "
                       f"reference this broker. Reassign or clear those trades first.",
            )

        cur.execute("DELETE FROM brokers WHERE id = ?", (broker_id,))
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("delete_broker DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete broker.")
    finally:
        conn.close()
    return {"detail": f"Broker {broker_id} deleted."}
