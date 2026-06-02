import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db import get_connection
from price_service import get_or_fetch_price, get_cached_price, get_price_source
import fx_service

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
    symbols: list[str]
    source: str = "yahoo_finance"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/prices/{symbol}")
def get_price(
    symbol: str,
    source: str = Query(default="yahoo_finance"),
    cache_only: bool = Query(default=False),
):
    """Fetch a price by Yahoo Finance *symbol* (e.g. "VOD.L", "BTC-USD"), not by a
    raw display ticker. The Add-trade autofill passes the selected instrument's
    symbol; the cache is keyed by symbol too."""
    try:
        get_price_source(source)  # validate before touching the DB
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    conn = _db()
    try:
        # cache_only: return the cached value regardless of age and never fetch
        # live (used by the passive Add-trade autofill).
        if cache_only:
            result = get_cached_price(conn, symbol, source)
        else:
            result = get_or_fetch_price(conn, symbol, source)
    except sqlite3.Error as exc:
        logger.error("get_price DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch price.")
    finally:
        conn.close()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No price available for '{symbol.upper()}' from source '{source}'.",
        )
    return result


@router.post("/prices/refresh")
def refresh_prices(body: PriceRefreshBody):
    symbols = [s.strip() for s in body.symbols if s.strip()]
    if not symbols:
        raise HTTPException(status_code=422, detail="symbols list cannot be empty.")

    try:
        get_price_source(body.source)  # validate before opening DB
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    conn = _db()
    results = []
    try:
        for symbol in symbols:
            try:
                result = get_or_fetch_price(conn, symbol, body.source, max_age_minutes=0)
            except Exception as exc:
                logger.warning("refresh_prices: failed for %s: %s", symbol, exc)
                result = None

            if result is not None:
                results.append(result)
            else:
                results.append({
                    "symbol":      symbol.upper(),
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


@router.get("/fx/{from_currency}/{to_currency}")
def get_fx(
    from_currency: str,
    to_currency: str,
    cache_only: bool = Query(default=False),
):
    """FX rate from_currency -> to_currency (e.g. /fx/EUR/USD). 1.0 for same
    currency. cache_only never fetches live — used by the Add-trade form to
    pre-fill the fx_rate field without a blocking network call."""
    conn = _db()
    try:
        if cache_only:
            rate = fx_service.get_cached_fx(conn, from_currency, to_currency)
        else:
            rate = fx_service.get_or_fetch_fx(conn, from_currency, to_currency)
    except sqlite3.Error as exc:
        logger.error("get_fx DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch FX rate.")
    finally:
        conn.close()

    if rate is None:
        raise HTTPException(
            status_code=404,
            detail=f"No FX rate available for {from_currency.upper()}->{to_currency.upper()}.",
        )
    return {
        "from_currency": from_currency.upper(),
        "to_currency":   to_currency.upper(),
        "rate":          rate,
    }


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

        # Base currency for the optional base-currency unrealized view. Cached so
        # we do one FX fetch per native currency, not per position.
        base_ccy_row = conn.execute(
            "SELECT value FROM app_settings WHERE key IN ('base_currency', 'currency') "
            "ORDER BY CASE key WHEN 'base_currency' THEN 0 ELSE 1 END LIMIT 1"
        ).fetchone()
        base_currency = ((base_ccy_row[0] if base_ccy_row else "USD") or "USD").strip().upper()
        _live_fx_cache: dict = {}

        # JOIN instruments so each position carries its Yahoo symbol; prices are
        # fetched by symbol while the display ticker is shown to the user.
        # Open lots: long opens (buy/long) and short opens (sell/short). Synthetic
        # close rows are status='closed' and excluded.
        cur.execute(
            "SELECT t.id, t.ticker, t.trade_type, t.trade_date, t.remaining_quantity, "
            "t.price_per_unit, t.status, t.broker_id, b.color, t.quantity, t.commission, "
            "i.symbol, i.name, i.exchange, i.asset_class, i.id, t.multiplier, t.direction, "
            "t.trade_currency, t.fx_rate, t.strike_price, t.expiration_date "
            "FROM trades t LEFT JOIN brokers b ON t.broker_id = b.id "
            "LEFT JOIN instruments i ON t.instrument_id = i.id "
            "WHERE t.user_id = ? AND t.status IN ('open', 'partial') "
            "AND ((t.action = 'buy' AND t.direction = 'long') OR (t.action = 'sell' AND t.direction = 'short')) "
            "ORDER BY t.ticker, t.trade_type, t.direction, t.expiration_date, t.strike_price, t.trade_date, t.id",
            (user_id,),
        )
        rows = cur.fetchall()

        # Group lots by (ticker, trade_type, direction, strike, expiration) so
        # different option contracts on the same underlying stay separate. The
        # base-currency cost basis is summed per-lot at each lot's stored fx_rate.
        groups: dict[tuple, dict] = {}
        for (trade_id, ticker, trade_type, trade_date, remaining_qty, price_per_unit,
             status, broker_id, broker_color, orig_quantity, buy_commission,
             instr_symbol, instr_name, instr_exchange, instr_asset_class, instr_id,
             multiplier, direction, trade_currency, fx_rate,
             strike_price, expiration_date) in rows:
            remaining_qty  = float(remaining_qty)
            price_per_unit = float(price_per_unit)
            multiplier     = float(multiplier) if multiplier is not None else 1.0
            fx_rate        = float(fx_rate) if fx_rate is not None else 1.0
            direction      = direction or "long"
            key = (ticker, trade_type, direction, strike_price, expiration_date)
            if key not in groups:
                groups[key] = {
                    "ticker":                   ticker,
                    "symbol":                   instr_symbol,  # first non-null wins below
                    "instrument_id":            instr_id,
                    "name":                     instr_name,
                    "exchange":                 instr_exchange,
                    "asset_class":              instr_asset_class,
                    "trade_type":               trade_type,
                    "direction":                direction,
                    "multiplier":               multiplier,
                    "currency":                 trade_currency or "USD",
                    "fx_rate":                  fx_rate,
                    "strike_price":             float(strike_price) if strike_price is not None else None,
                    "expiration_date":          expiration_date,
                    "total_remaining_quantity": 0.0,
                    "total_raw_cost":           0.0,
                    "total_cost_basis":         0.0,
                    "total_cost_basis_base":    0.0,
                    "lots":                     [],
                    "broker_qty":               {},  # broker_id -> {broker_id, color, qty}
                }
            # Keep the first instrument fields seen for this ticker group.
            if groups[key]["symbol"] is None and instr_symbol is not None:
                groups[key]["symbol"]        = instr_symbol
                groups[key]["instrument_id"] = instr_id
                groups[key]["name"]          = instr_name
                groups[key]["exchange"]      = instr_exchange
                groups[key]["asset_class"]   = instr_asset_class
            g = groups[key]
            g["total_remaining_quantity"] += remaining_qty
            g["total_raw_cost"]           += remaining_qty * price_per_unit
            g["total_cost_basis"]         += remaining_qty * price_per_unit * multiplier
            g["total_cost_basis_base"]    += remaining_qty * price_per_unit * multiplier * fx_rate
            g["lots"].append({
                "trade_id":          trade_id,
                "trade_date":        trade_date,
                "remaining_quantity": remaining_qty,
                "price_per_unit":    price_per_unit,
                "multiplier":        multiplier,
                "status":            status,
                # Fields below let the sell modal estimate commissions client-side
                "broker_id":         broker_id,
                "quantity":          float(orig_quantity),
                "commission":        float(buy_commission or 0),
            })
            # Track quantity per broker for the dominant-broker pick below. Done for
            # any broker (color may be null); the color just rides along for styling.
            if broker_id:
                bq = g["broker_qty"]
                if broker_id not in bq:
                    bq[broker_id] = {"broker_id": broker_id, "color": broker_color, "qty": 0.0}
                bq[broker_id]["qty"] += remaining_qty

        positions = []
        for g in groups.values():
            total_qty   = round(g["total_remaining_quantity"], 10)
            cost_basis  = round(g["total_cost_basis"], 10)
            multiplier  = g["multiplier"]
            # avg_cost is the raw price-weighted average so it lines up with the
            # per-unit quote; cost basis and current value carry the multiplier.
            avg_cost    = round(g["total_raw_cost"] / total_qty, 10) if total_qty else 0.0

            # Dominant broker = the one with the most remaining quantity in this position
            dominant = max(g["broker_qty"].values(), key=lambda x: x["qty"]) if g["broker_qty"] else None
            broker_color = dominant["color"] if dominant else None
            broker_id    = dominant["broker_id"] if dominant else None

            # Fetch by Yahoo symbol; fall back to the display ticker for positions
            # whose trades aren't linked to an instrument yet.
            fetch_symbol = g["symbol"] or g["ticker"]
            try:
                price_data = get_or_fetch_price(conn, fetch_symbol, source)
            except Exception as exc:
                logger.warning("positions/prices: price fetch failed for %s: %s", fetch_symbol, exc)
                price_data = None

            current_price = price_data["price"] if price_data else None

            direction = g["direction"]
            position_currency = g["currency"]
            # Live FX from the position's currency to the base, for the optional
            # base-currency unrealized view. Cached per pair so a portfolio of
            # many EUR positions does one fetch, not N. None falls back to 1.0.
            if position_currency == base_currency:
                live_fx = 1.0
            elif position_currency in _live_fx_cache:
                live_fx = _live_fx_cache[position_currency]
            else:
                try:
                    live_fx = fx_service.get_or_fetch_fx(conn, position_currency, base_currency) or 1.0
                except Exception as exc:
                    logger.warning("positions/prices: FX %s->%s failed: %s",
                                   position_currency, base_currency, exc)
                    live_fx = 1.0
                _live_fx_cache[position_currency] = live_fx

            if current_price is not None:
                # current_value is the live market value of the units (the cost to
                # buy back, for a short). A long gains when value rises above its
                # cost basis; a short gains when the buy-back value falls below the
                # proceeds it received (cost_basis).
                current_value    = round(total_qty * current_price * multiplier, 10)
                unrealized_pnl   = round(
                    (cost_basis - current_value) if direction == "short"
                    else (current_value - cost_basis), 10
                )
                unrealized_pnl_pct = (
                    round(unrealized_pnl / cost_basis * 100, 4)
                    if cost_basis != 0 else None
                )
                # Base-currency view: market value at today's FX, vs cost basis
                # converted at each lot's stored FX (already in *_base). Captures
                # both the price move and the currency move since each lot opened.
                current_value_base = round(current_value * live_fx, 10)
                cost_basis_base    = round(g["total_cost_basis_base"], 10)
                unrealized_pnl_base = round(
                    (cost_basis_base - current_value_base) if direction == "short"
                    else (current_value_base - cost_basis_base), 10
                )
            else:
                current_value = unrealized_pnl = unrealized_pnl_pct = None
                current_value_base = unrealized_pnl_base = None

            positions.append({
                "ticker":                   g["ticker"],
                "symbol":                   g["symbol"] or g["ticker"],
                "instrument_id":            g["instrument_id"],
                "broker_id":                broker_id,
                "name":                     g["name"],
                "exchange":                 g["exchange"],
                "asset_class":              g["asset_class"],
                "trade_type":               g["trade_type"],
                "direction":                direction,
                "multiplier":               multiplier,
                "currency":                 position_currency,
                "strike_price":             g["strike_price"],
                "expiration_date":          g["expiration_date"],
                "total_remaining_quantity": total_qty,
                "avg_cost_per_unit":        avg_cost,
                "total_cost_basis":         cost_basis,
                "total_cost_basis_base":    round(g["total_cost_basis_base"], 10),
                "lots":                     g["lots"],
                "broker_color":             broker_color,
                "current_price":            current_price,
                "current_value":            current_value,
                "unrealized_pnl":           unrealized_pnl,
                "unrealized_pnl_pct":       unrealized_pnl_pct,
                "current_value_base":       current_value_base,
                "unrealized_pnl_base":      unrealized_pnl_base,
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
