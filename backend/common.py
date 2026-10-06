"""Helpers and constants shared by the route modules split out of main.py."""
import base64
import datetime
import json
import logging
import sqlite3
import time
from typing import Optional

from fastapi import HTTPException

from db import get_connection
import fx_service

logger = logging.getLogger(__name__)

ACTIONS = {"buy", "sell"}
DIRECTIONS = {"long", "short"}


def _normalize_trade_type(cur: sqlite3.Cursor, value: str) -> str:
    """Validate a trade_type against the trade_types table (case-insensitively)
    and return the canonical stored name. Raises 422 if it is not a known type.

    This replaces the old DB-level CHECK constraint: the constraint is enforced
    here, in the route layer, against the trade_types table.
    """
    cur.execute("SELECT name FROM trade_types")
    by_lower = {row[0].lower(): row[0] for row in cur.fetchall()}
    canonical = by_lower.get((value or "").strip().lower())
    if canonical is None:
        raise HTTPException(status_code=400, detail="Unknown trade type")
    return canonical


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    try:
        return get_connection()
    except sqlite3.OperationalError as exc:
        logger.error("DB open failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not open the database.")


def _validate_iso_date(value, field: str):
    """Return a normalized ISO date string, None for empty, or raise 400 if invalid."""
    if value is None or value == "":
        return None
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"{field} must be an ISO date (YYYY-MM-DD).")


def _dt_to_storage(dt: datetime.datetime) -> str:
    """Serialize a datetime to the DB's 'YYYY-MM-DD HH:MM:SS' text form — the same
    space-separated, second-precision shape as the created_at columns (which come
    from SQLite's datetime('now')). Date-only inputs arrive coerced to midnight."""
    return dt.isoformat(sep=" ", timespec="seconds")


# Reusable SELECT that joins broker name + color and the linked instrument; used
# by list/create/update trade routes.
# Columns: 0=id 1=user_id 2=ticker 3=trade_type 4=action 5=quantity
#          6=price_per_unit 7=total_value 8=trade_date 9=notes 10=created_at
#          11=status 12=remaining_quantity 13=broker_id 14=broker_name 15=broker_color
#          16=commission 17=net_total_value
#          18=instr_symbol 19=instr_name 20=instr_exchange 21=instr_asset_class 22=instr_currency
#          23=multiplier 24=strike_price 25=expiration_date 26=underlying 27=direction
#          28=trade_currency 29=fx_rate
#          30=face_value 31=coupon_rate 32=coupon_frequency 33=maturity_date 34=accrued_interest
_TRADE_SELECT = (
    "SELECT t.id, t.user_id, t.ticker, t.trade_type, t.action, t.quantity, "
    "t.price_per_unit, t.total_value, t.trade_date, t.notes, t.created_at, "
    "t.status, t.remaining_quantity, t.broker_id, b.name, b.color, "
    "t.commission, t.net_total_value, "
    "i.symbol, i.name, i.exchange, i.asset_class, i.currency, "
    "t.multiplier, t.strike_price, t.expiration_date, t.underlying, t.direction, "
    "t.trade_currency, t.fx_rate, "
    "t.face_value, t.coupon_rate, t.coupon_frequency, t.maturity_date, t.accrued_interest "
    "FROM trades t LEFT JOIN brokers b ON t.broker_id = b.id "
    "LEFT JOIN instruments i ON t.instrument_id = i.id"
)


# Sort fields the paginated trades endpoint accepts -> their SQL column.
_TRADE_SORT_COLUMNS = {
    "trade_date":     "t.trade_date",
    "ticker":         "t.ticker",
    "total_value":    "t.total_value",
    "price_per_unit": "t.price_per_unit",
    "quantity":       "t.quantity",
}

# In-memory cache of total_count per (user_id, filter) for 30s, so paging through
# results doesn't re-run COUNT(*) on every request.
_COUNT_CACHE: dict = {}
_COUNT_CACHE_TTL = 30.0


def _encode_cursor(last_val, last_id: int) -> str:
    """base64(JSON) of the last row's sort value + id — opaque keyset cursor."""
    raw = json.dumps({"last_val": last_val, "last_id": last_id}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str):
    """Return (last_val, last_id) from an opaque cursor, or 400 if it's malformed."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return data["last_val"], int(data["last_id"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid cursor.")


def _cached_total_count(conn, cache_key, where_sql: str, params: list) -> int:
    """COUNT(*) of matching trades, cached per cache_key for _COUNT_CACHE_TTL seconds."""
    now = time.monotonic()
    cached = _COUNT_CACHE.get(cache_key)
    if cached is not None and now - cached[0] < _COUNT_CACHE_TTL:
        return cached[1]
    count = conn.execute("SELECT COUNT(*) FROM trades t" + where_sql, params).fetchone()[0]
    _COUNT_CACHE[cache_key] = (now, count)
    return count


def _row_to_trade(r) -> dict:
    return {
        "id":                 r[0],
        "user_id":            r[1],
        "ticker":             r[2],
        "trade_type":         r[3],
        "action":             r[4],
        "quantity":           float(r[5]),
        "price_per_unit":     float(r[6]),
        "total_value":        float(r[7]),
        "trade_date":         r[8],
        "notes":              r[9],
        "created_at":         r[10],
        "status":             r[11],
        "remaining_quantity": float(r[12]) if r[12] is not None else None,
        "broker_id":          r[13],
        "broker_name":        r[14],
        "broker_color":       r[15],
        "commission":         float(r[16]) if r[16] is not None else 0.0,
        "net_total_value":    float(r[17]) if r[17] is not None else None,
        "symbol":             r[18],
        "name":               r[19],
        "exchange":           r[20],
        "asset_class":        r[21],
        "currency":           r[22],
        "multiplier":         float(r[23]) if r[23] is not None else 1.0,
        "strike_price":       float(r[24]) if r[24] is not None else None,
        "expiration_date":    r[25],
        "underlying":         r[26],
        "direction":          r[27] or "long",
        "trade_currency":     r[28] or "USD",
        "fx_rate":            float(r[29]) if r[29] is not None else 1.0,
        "face_value":         float(r[30]) if r[30] is not None else None,
        "coupon_rate":        float(r[31]) if r[31] is not None else None,
        "coupon_frequency":   int(r[32])   if r[32] is not None else None,
        "maturity_date":      r[33],
        "accrued_interest":   float(r[34]) if r[34] is not None else 0.0,
    }


def _compute_commission(cur: sqlite3.Cursor, broker_id, quantity: float, override) -> float:
    """Commission for a trade: the user override if given, else the broker's
    flat fee + per-unit fee * quantity. Returns 0 when neither applies."""
    if override is not None:
        return round(float(override), 10)
    if broker_id is None:
        return 0.0
    cur.execute(
        "SELECT commission_flat, commission_per_unit FROM brokers WHERE id = ?",
        (broker_id,),
    )
    row = cur.fetchone()
    if row is None:
        return 0.0
    flat, per_unit = float(row[0] or 0), float(row[1] or 0)
    return round(flat + per_unit * quantity, 10)


def _net_total(action: str, total_value: float, commission: float) -> float:
    """Buys cost more (add commission); sells net less (subtract commission)."""
    return round(total_value + commission if action == "buy" else total_value - commission, 10)


# Trade types whose price quotes are per-unit but whose economic exposure is
# scaled by a contract multiplier (an equity option quote of $2.50 controls
# 100 shares, i.e. $250 of notional). Anything else defaults to a 1x multiplier.
OPTION_TRADE_TYPES = {"Call", "Put"}
DEFAULT_OPTION_MULTIPLIER = 100.0
BOND_TRADE_TYPES = {"Bond"}
# Standard US corporate / treasury bond face: prices are quoted as % of par, so
# a multiplier of face_value/100 converts a "98.5" quote into $985 per bond.
DEFAULT_BOND_FACE_VALUE = 1000.0


def _base_currency(cur: sqlite3.Cursor) -> str:
    """The portfolio's reporting currency. Prefers base_currency, falls back to the
    legacy `currency` setting, then USD. All cash-pool amounts, realized P&L, and
    stats aggregates are stored/summed in this currency."""
    cur.execute("SELECT key, value FROM app_settings WHERE key IN ('base_currency', 'currency')")
    vals = {k: v for k, v in cur.fetchall()}
    return ((vals.get("base_currency") or vals.get("currency") or "USD").strip().upper()) or "USD"


def _resolve_fx(conn, cur: sqlite3.Cursor, trade_currency: str, override) -> float:
    """FX rate to convert `trade_currency` into the base currency at trade time.

    An explicit override wins (must be > 0); same-currency is 1.0; otherwise the
    live/cached rate is used. If a cross-currency rate can't be fetched (offline,
    unknown pair) we fall back to 1.0 and log it, so the trade still records — the
    user can correct the rate via the override later."""
    if override is not None:
        try:
            fx = float(override)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="fx_rate must be a number.")
        if fx <= 0:
            raise HTTPException(status_code=422, detail="fx_rate must be greater than 0.")
        return round(fx, 10)

    base = _base_currency(cur)
    if (trade_currency or "").upper() == base:
        return 1.0
    try:
        rate = fx_service.get_or_fetch_fx(conn, trade_currency, base)
    except Exception as exc:
        logger.warning("FX fetch %s->%s failed: %s", trade_currency, base, exc)
        rate = None
    if rate is None:
        logger.warning("No FX rate for %s->%s; defaulting to 1.0", trade_currency, base)
        return 1.0
    return round(rate, 10)


def _resolve_face_value(trade_type: str, override) -> Optional[float]:
    """Face/par value for a bond lot: explicit override if given (>0), else 1000
    for Bond and None for everything else. Used only by bonds; the multiplier
    derives from face_value/100 so a 98.5 quote prices a $1000 bond at $985."""
    if override is not None:
        try:
            fv = float(override)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="face_value must be a number.")
        if fv <= 0:
            raise HTTPException(status_code=422, detail="face_value must be greater than 0.")
        return round(fv, 10)
    return DEFAULT_BOND_FACE_VALUE if trade_type in BOND_TRADE_TYPES else None


def _resolve_multiplier(trade_type: str, override, face_value: Optional[float] = None) -> float:
    """The contract multiplier for a trade: an explicit override if given (must be
    > 0); else 100 for Call/Put; else face_value/100 for a Bond (so a per-par
    quote becomes a dollar amount); else 1. The canonical trade_type (from
    _normalize_trade_type) is expected so the Call/Put/Bond match is exact."""
    if override is not None:
        try:
            m = float(override)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="multiplier must be a number.")
        if m <= 0:
            raise HTTPException(status_code=422, detail="multiplier must be greater than 0.")
        return round(m, 10)
    if trade_type in OPTION_TRADE_TYPES:
        return DEFAULT_OPTION_MULTIPLIER
    if trade_type in BOND_TRADE_TYPES and face_value is not None:
        return round(face_value / 100.0, 10)
    return 1.0


def _row_to_sell_lot(r) -> dict:
    return {
        "id": r[0],
        "buy_trade_id": r[1],
        "sell_date": r[2],
        "quantity_sold": float(r[3]),
        "sell_price_per_unit": float(r[4]),
        "proceeds": float(r[5]),
        "realized_pnl": float(r[6]),
        "notes": r[7],
        "created_at": r[8],
    }


def _require_user(cur: sqlite3.Cursor, user_id: int):
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found.")


def _require_trade(cur: sqlite3.Cursor, trade_id: int) -> tuple:
    # Columns: 0=id 1=user_id 2=ticker 3=trade_type 4=action 5=quantity
    #          6=price_per_unit 7=total_value 8=trade_date 9=notes 10=created_at
    #          11=status 12=remaining_quantity 13=broker_id 14=commission 15=multiplier
    #          16=strike_price 17=expiration_date 18=underlying 19=direction
    #          20=trade_currency 21=fx_rate 22=accrued_interest
    cur.execute(
        "SELECT id, user_id, ticker, trade_type, action, quantity, price_per_unit, "
        "total_value, trade_date, notes, created_at, status, remaining_quantity, broker_id, "
        "commission, multiplier, strike_price, expiration_date, underlying, direction, "
        "trade_currency, fx_rate, accrued_interest "
        "FROM trades WHERE id = ?",
        (trade_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found.")
    return row


def _require_broker(cur: sqlite3.Cursor, broker_id: int):
    cur.execute("SELECT id FROM brokers WHERE id = ?", (broker_id,))
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Broker {broker_id} not found.")


def _require_instrument(cur: sqlite3.Cursor, instrument_id: int):
    cur.execute("SELECT id FROM instruments WHERE id = ?", (instrument_id,))
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found.")
