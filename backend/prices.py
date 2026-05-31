import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db import get_connection
from price_service import get_or_fetch_price, get_cached_price, get_price_source

logger = logging.getLogger(__name__)
router = APIRouter(tags=["prices"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    try:
        return get_connection()
    except sqlite3.OperationalError as exc:
        logger.error("DB open failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not open the database.")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PriceRefreshBody(BaseModel):
    tickers: list[str]
    source: str = "yahoo_finance"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/prices/{ticker}")
def get_price(
    ticker: str,
    source: str = Query(default="yahoo_finance"),
    cache_only: bool = Query(default=False),
):
    try:
        get_price_source(source)  # validate before touching the DB
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    conn = _db()
    try:
        # cache_only: return the cached value regardless of age and never fetch
        # live (used by the passive Add-trade autofill).
        if cache_only:
            result = get_cached_price(conn, ticker, source)
        else:
            result = get_or_fetch_price(conn, ticker, source)
    except sqlite3.Error as exc:
        logger.error("get_price DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch price.")
    finally:
        conn.close()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No price available for '{ticker.upper()}' from source '{source}'.",
        )
    return result


@router.post("/prices/refresh")
def refresh_prices(body: PriceRefreshBody):
    tickers = [t.strip() for t in body.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=422, detail="tickers list cannot be empty.")

    try:
        get_price_source(body.source)  # validate before opening DB
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    conn = _db()
    results = []
    try:
        for ticker in tickers:
            try:
                result = get_or_fetch_price(conn, ticker, body.source, max_age_minutes=0)
            except Exception as exc:
                logger.warning("refresh_prices: failed for %s: %s", ticker, exc)
                result = None

            if result is not None:
                results.append(result)
            else:
                results.append({
                    "ticker":      ticker.upper(),
                    "price":       None,
                    "currency":    None,
                    "source":      body.source,
                    "fetched_at":  None,
                    "from_cache":  False,
                    "error":       "fetch failed",
                })
    finally:
        conn.close()

    return results


@router.get("/users/{user_id}/positions/prices")
def get_positions_with_prices(
    user_id: int,
    source: str = Query(default="yahoo_finance"),
):
    try:
        get_price_source(source)  # validate before touching the DB
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    conn = _db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found.")

        cur.execute(
            "SELECT t.id, t.ticker, t.trade_type, t.trade_date, t.remaining_quantity, "
            "t.price_per_unit, t.status, t.broker_id, b.color, t.quantity, t.commission "
            "FROM trades t LEFT JOIN brokers b ON t.broker_id = b.id "
            "WHERE t.user_id = ? AND t.action = 'buy' AND t.status IN ('open', 'partial') "
            "ORDER BY t.ticker, t.trade_type, t.trade_date, t.id",
            (user_id,),
        )
        rows = cur.fetchall()

        # Group lots into positions, same logic as GET /users/{id}/positions
        groups: dict[tuple, dict] = {}
        for (trade_id, ticker, trade_type, trade_date, remaining_qty, price_per_unit,
             status, broker_id, broker_color, orig_quantity, buy_commission) in rows:
            remaining_qty  = float(remaining_qty)
            price_per_unit = float(price_per_unit)
            key = (ticker, trade_type)
            if key not in groups:
                groups[key] = {
                    "ticker":                   ticker,
                    "trade_type":               trade_type,
                    "total_remaining_quantity": 0.0,
                    "total_cost_basis":         0.0,
                    "lots":                     [],
                    "broker_qty":               {},  # broker_id -> {color, qty}
                }
            g = groups[key]
            g["total_remaining_quantity"] += remaining_qty
            g["total_cost_basis"]         += remaining_qty * price_per_unit
            g["lots"].append({
                "trade_id":          trade_id,
                "trade_date":        trade_date,
                "remaining_quantity": remaining_qty,
                "price_per_unit":    price_per_unit,
                "status":            status,
                # Fields below let the sell modal estimate commissions client-side
                "broker_id":         broker_id,
                "quantity":          float(orig_quantity),
                "commission":        float(buy_commission or 0),
            })
            if broker_id and broker_color:
                bq = g["broker_qty"]
                if broker_id not in bq:
                    bq[broker_id] = {"color": broker_color, "qty": 0.0}
                bq[broker_id]["qty"] += remaining_qty

        positions = []
        for g in groups.values():
            total_qty  = round(g["total_remaining_quantity"], 10)
            cost_basis = round(g["total_cost_basis"], 10)
            avg_cost   = round(cost_basis / total_qty, 10) if total_qty else 0.0

            # Dominant broker = the one with the most remaining quantity in this position
            dominant = max(g["broker_qty"].values(), key=lambda x: x["qty"]) if g["broker_qty"] else None
            broker_color = dominant["color"] if dominant else None

            try:
                price_data = get_or_fetch_price(conn, g["ticker"], source)
            except Exception as exc:
                logger.warning("positions/prices: price fetch failed for %s: %s", g["ticker"], exc)
                price_data = None

            current_price = price_data["price"] if price_data else None

            if current_price is not None:
                current_value    = round(total_qty * current_price, 10)
                unrealized_pnl   = round(current_value - cost_basis, 10)
                unrealized_pnl_pct = (
                    round(unrealized_pnl / cost_basis * 100, 4)
                    if cost_basis != 0 else None
                )
            else:
                current_value = unrealized_pnl = unrealized_pnl_pct = None

            positions.append({
                "ticker":                   g["ticker"],
                "trade_type":               g["trade_type"],
                "total_remaining_quantity": total_qty,
                "avg_cost_per_unit":        avg_cost,
                "total_cost_basis":         cost_basis,
                "lots":                     g["lots"],
                "broker_color":             broker_color,
                "current_price":            current_price,
                "current_value":            current_value,
                "unrealized_pnl":           unrealized_pnl,
                "unrealized_pnl_pct":       unrealized_pnl_pct,
                "price_source":             price_data["source"]      if price_data else None,
                "price_fetched_at":         price_data["fetched_at"]  if price_data else None,
                "price_from_cache":         price_data["from_cache"]  if price_data else None,
            })

    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_positions_with_prices DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch positions with prices.")
    finally:
        conn.close()

    return positions
