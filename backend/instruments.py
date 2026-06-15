import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db import get_connection
from price_service import search_instruments, resolve_isin, ISIN_RE

logger = logging.getLogger(__name__)
router = APIRouter(tags=["instruments"])

# How many local rows the search returns before it bothers calling Yahoo.
_LOCAL_SEARCH_LIMIT = 5

# Column order shared by every instrument SELECT + _row_to_instrument.
_INSTRUMENT_COLS = "id, symbol, ticker, name, exchange, asset_class, currency, isin, created_at"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    try:
        return get_connection()
    except sqlite3.OperationalError as exc:
        logger.error("DB open failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not open the database.")


def _row_to_instrument(r) -> dict:
    return {
        "id":          r[0],
        "symbol":      r[1],
        "ticker":      r[2],
        "name":        r[3],
        "exchange":    r[4],
        "asset_class": r[5],
        "currency":    r[6],
        "isin":        r[7],
        "created_at":  r[8],
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class InstrumentBody(BaseModel):
    symbol: str
    ticker: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    asset_class: str = "stock"
    currency: str = "USD"
    isin: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/instruments/search")
def search_instrument(q: str = Query(...)):
    """Search the local registry first; only hit Yahoo when nothing matches."""
    term = (q or "").strip()
    if not term:
        return {"results": [], "source": "local"}

    conn = _db()
    try:
        cur = conn.cursor()
        like = f"%{term}%"
        cur.execute(
            f"SELECT {_INSTRUMENT_COLS} FROM instruments "
            "WHERE ticker LIKE ? OR name LIKE ? OR symbol LIKE ? "
            "ORDER BY ticker ASC LIMIT ?",
            (like, like, like, _LOCAL_SEARCH_LIMIT),
        )
        local = [_row_to_instrument(r) for r in cur.fetchall()]
    except sqlite3.Error as exc:
        logger.error("instrument search DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Instrument search failed.")
    finally:
        conn.close()

    # Local hit → return immediately, no live call needed.
    if local:
        return {"results": local, "source": "local"}

    # An ISIN query (e.g. "DE000BASF111") resolves via onvista — this is how the
    # user logs a German instrument by its ISIN in the Add-trade search.
    if ISIN_RE.match(term.upper()):
        try:
            inst = resolve_isin(term)
        except Exception as exc:
            logger.warning("Onvista ISIN resolve failed for %r: %s", term, exc)
            inst = None
        if inst:
            return {"results": [inst], "source": "onvista"}
        return {"results": [], "source": "onvista", "warning": "ISIN not found"}

    # Nothing local → ask Yahoo. On any failure, fall back to the (empty) local
    # results with a warning rather than erroring the whole request.
    try:
        results = search_instruments(term)
    except Exception as exc:
        logger.warning("Yahoo instrument search failed for %r: %s", term, exc)
        return {"results": local, "source": "local_only", "warning": "Live search unavailable"}

    return {"results": results, "source": "yahoo"}


@router.post("/instruments", status_code=201)
def upsert_instrument(body: InstrumentBody):
    """Upsert an instrument keyed by symbol; called when the user confirms a pick."""
    symbol = body.symbol.strip().upper()
    ticker = body.ticker.strip()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol cannot be empty.")
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker cannot be empty.")

    conn = _db()
    try:
        cur = conn.cursor()
        # ON CONFLICT ... DO UPDATE rather than INSERT OR REPLACE: REPLACE deletes
        # the conflicting row and re-inserts it with a NEW id, which would orphan
        # every trades.instrument_id pointing at it. DO UPDATE keeps the id stable.
        cur.execute(
            "INSERT INTO instruments (symbol, ticker, name, exchange, asset_class, currency, isin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "ticker = excluded.ticker, name = excluded.name, exchange = excluded.exchange, "
            "asset_class = excluded.asset_class, currency = excluded.currency, isin = excluded.isin",
            (symbol, ticker, body.name, body.exchange, body.asset_class, body.currency, body.isin),
        )
        conn.commit()
        cur.execute(f"SELECT {_INSTRUMENT_COLS} FROM instruments WHERE symbol = ?", (symbol,))
        row = cur.fetchone()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("upsert_instrument DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save instrument.")
    finally:
        conn.close()

    return _row_to_instrument(row)


@router.get("/instruments")
def list_instruments():
    """All instruments (ticker A-Z), each with how many trades reference it."""
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_INSTRUMENT_COLS}, "
            "(SELECT COUNT(*) FROM trades WHERE trades.instrument_id = instruments.id) AS usage_count "
            "FROM instruments ORDER BY ticker ASC"
        )
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        logger.error("list_instruments DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch instruments.")
    finally:
        conn.close()

    out = []
    for r in rows:
        inst = _row_to_instrument(r)
        inst["usage_count"] = int(r[9])
        out.append(inst)
    return out
