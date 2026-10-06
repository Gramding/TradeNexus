"""Open positions grouped by instrument, strike, expiration and direction."""
import logging
import sqlite3

from fastapi import APIRouter, HTTPException

from common import (
    _db,
    _require_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["positions"])


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/positions")
def get_positions(user_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)
        # Open lots are long opens (buy/long) and short opens (sell/short). The
        # synthetic close rows are status='closed' and never match.
        cur.execute(
            "SELECT id, ticker, trade_type, trade_date, remaining_quantity, price_per_unit, status, "
            "multiplier, direction, trade_currency, fx_rate, strike_price, expiration_date "
            "FROM trades "
            "WHERE user_id = ? AND status IN ('open', 'partial') "
            "AND ((action = 'buy' AND direction = 'long') OR (action = 'sell' AND direction = 'short')) "
            "ORDER BY ticker, trade_type, direction, expiration_date, strike_price, trade_date, id",
            (user_id,),
        )
        rows = cur.fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_positions DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch positions.")
    finally:
        conn.close()

    # Group by (ticker, trade_type, direction, strike, expiration) so a long and a
    # short on the same ticker stay separate, AND so two calls on the same name
    # with different strikes / expirations stay separate (they aren't fungible).
    # avg_cost_per_unit and total_cost_basis are in the position's native currency;
    # total_cost_basis_base converts via each lot's stored fx_rate.
    groups: dict[tuple, dict] = {}
    for (trade_id, ticker, trade_type, trade_date, remaining_qty, price_per_unit,
         status, multiplier, direction, trade_currency, fx_rate,
         strike_price, expiration_date) in rows:
        remaining_qty = float(remaining_qty)
        price_per_unit = float(price_per_unit)
        multiplier = float(multiplier) if multiplier is not None else 1.0
        fx_rate = float(fx_rate) if fx_rate is not None else 1.0
        direction = direction or "long"
        key = (ticker, trade_type, direction, strike_price, expiration_date)
        if key not in groups:
            groups[key] = {
                "ticker": ticker,
                "trade_type": trade_type,
                "direction": direction,
                "multiplier": multiplier,
                "currency": trade_currency or "USD",
                "strike_price": float(strike_price) if strike_price is not None else None,
                "expiration_date": expiration_date,
                "total_remaining_quantity": 0.0,
                "total_raw_cost": 0.0,
                "total_cost_basis": 0.0,
                "total_cost_basis_base": 0.0,
                "lots": [],
            }
        g = groups[key]
        lot_basis = remaining_qty * price_per_unit * multiplier
        g["total_remaining_quantity"] += remaining_qty
        g["total_raw_cost"] += remaining_qty * price_per_unit
        g["total_cost_basis"] += lot_basis
        g["total_cost_basis_base"] += lot_basis * fx_rate
        g["lots"].append({
            "trade_id": trade_id,
            "trade_date": trade_date,
            "remaining_quantity": remaining_qty,
            "price_per_unit": price_per_unit,
            "multiplier": multiplier,
            "status": status,
        })

    positions = []
    for g in groups.values():
        total_qty = g["total_remaining_quantity"]
        positions.append({
            "ticker": g["ticker"],
            "trade_type": g["trade_type"],
            "direction": g["direction"],
            "multiplier": g["multiplier"],
            "currency": g["currency"],
            "strike_price": g["strike_price"],
            "expiration_date": g["expiration_date"],
            "total_remaining_quantity": round(total_qty, 10),
            "avg_cost_per_unit": round(g["total_raw_cost"] / total_qty, 10) if total_qty else 0.0,
            # For a short, this is the proceeds received (the basis to compare a
            # buy-back against); for a long, the amount invested. Native currency.
            "total_cost_basis": round(g["total_cost_basis"], 10),
            "total_cost_basis_base": round(g["total_cost_basis_base"], 10),
            "lots": g["lots"],
        })

    return positions
