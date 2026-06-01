"""Resolve a clickable "view this instrument" URL for a trade or position.

The core is the pure build_quote_url() function, which walks a strict fallback
chain (broker deep link → Yahoo Finance → Yahoo search) and *never* returns a
non-https URL. The two routes simply load the trade/instrument/broker rows and
hand them to it.
"""
import logging
import re
import sqlite3
import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["quote-links"])

# quote_url_key -> the instrument dict field that fills the {value} placeholder.
_KEY_FIELDS = {"symbol": "symbol", "ticker": "ticker", "isin": "isin"}

# Named placeholders a template may use. {value} is the key-driven one; the rest
# pull a specific instrument field directly, so a template can target the right
# identifier per exchange, e.g. ".../{isin}" or ".../{ticker}.{exchange}".
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ---------------------------------------------------------------------------
# Core resolver (pure, no DB)
# ---------------------------------------------------------------------------

def _ensure_https(url: str) -> str:
    """Guard: every URL this module hands back must be an absolute https URL.
    Blocks http://, javascript:, file:, and anything else."""
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError(f"Refusing to return a non-https quote URL: {url!r}")
    return url


def build_quote_url(trade: dict, instrument: Optional[dict], broker: Optional[dict]) -> dict:
    """Resolve the best available quote URL via a strict fallback chain.

    Returns {url, source, label} where source is one of 'broker', 'yahoo', or
    'search_fallback'. url is always an https:// string (else ValueError).
    """
    # 1. Broker deep link -------------------------------------------------------
    if broker is not None and broker.get("quote_url_template") and instrument is not None:
        template = broker["quote_url_template"]
        key = broker.get("quote_url_key") or "symbol"
        # {value} follows the broker's chosen key; the named placeholders map to a
        # specific instrument field so a template can pick the right id per exchange.
        subs = {
            "value":    instrument.get(_KEY_FIELDS.get(key, "symbol")),
            "ticker":   instrument.get("ticker"),
            "symbol":   instrument.get("symbol"),
            "isin":     instrument.get("isin"),
            "exchange": instrument.get("exchange"),
        }
        used = set(_PLACEHOLDER_RE.findall(template))
        # Build only when every placeholder is known and resolves to a non-empty
        # value (e.g. a {isin} template on an instrument with no ISIN skips to Yahoo).
        if used and used <= set(subs) and all(subs[p] for p in used):
            url = _PLACEHOLDER_RE.sub(
                lambda m: urllib.parse.quote(str(subs[m.group(1)]), safe=""),
                template,
            )
            # A misconfigured template (non-https) skips to the Yahoo fallback
            # rather than erroring the whole request.
            if url.startswith("https://"):
                broker_name = broker.get("name") or "broker"
                return {
                    "url":    _ensure_https(url),
                    "source": "broker",
                    "label":  f"View on {broker_name}",
                }

    # 2. Yahoo Finance fallback -------------------------------------------------
    if instrument is not None and instrument.get("symbol"):
        url = f"https://finance.yahoo.com/quote/{urllib.parse.quote(str(instrument['symbol']), safe='')}"
        return {
            "url":    _ensure_https(url),
            "source": "yahoo",
            "label":  "View on Yahoo Finance",
        }

    # 3. Search fallback (always works) ----------------------------------------
    ticker = (instrument.get("ticker") if instrument else trade.get("ticker", "")) or ""
    url = f"https://finance.yahoo.com/search?q={urllib.parse.quote(str(ticker), safe='')}"
    return {
        "url":    _ensure_https(url),
        "source": "search_fallback",
        "label":  f"Search {ticker}",
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    try:
        return get_connection()
    except sqlite3.OperationalError as exc:
        logger.error("DB open failed: %s", exc)
        raise HTTPException(status_code=503, detail="Could not open the database.")


def _fetch_instrument(cur: sqlite3.Cursor, instrument_id) -> Optional[dict]:
    if instrument_id is None:
        return None
    cur.execute(
        "SELECT id, symbol, ticker, name, exchange, asset_class, currency, isin "
        "FROM instruments WHERE id = ?",
        (instrument_id,),
    )
    r = cur.fetchone()
    if r is None:
        return None
    return {
        "id": r[0], "symbol": r[1], "ticker": r[2], "name": r[3],
        "exchange": r[4], "asset_class": r[5], "currency": r[6], "isin": r[7],
    }


def _fetch_broker(cur: sqlite3.Cursor, broker_id) -> Optional[dict]:
    if broker_id is None:
        return None
    cur.execute(
        "SELECT id, name, quote_url_template, quote_url_key FROM brokers WHERE id = ?",
        (broker_id,),
    )
    r = cur.fetchone()
    if r is None:
        return None
    return {"id": r[0], "name": r[1], "quote_url_template": r[2], "quote_url_key": r[3] or "symbol"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/trades/{trade_id}/quote-url")
def get_trade_quote_url(trade_id: int):
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, broker_id, instrument_id, ticker FROM trades WHERE id = ?",
            (trade_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found.")
        trade = {"id": row[0], "broker_id": row[1], "instrument_id": row[2], "ticker": row[3]}
        instrument = _fetch_instrument(cur, row[2])
        broker = _fetch_broker(cur, row[1])
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_trade_quote_url DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve quote URL.")
    finally:
        conn.close()

    return build_quote_url(trade, instrument, broker)


@router.get("/instruments/{instrument_id}/quote-url")
def get_instrument_quote_url(instrument_id: int, broker_id: Optional[int] = Query(None)):
    """Resolve a quote URL for a position view, where there is no specific trade.
    broker_id is optional; omit it to skip the broker deep link and go to Yahoo."""
    conn = _db()
    try:
        cur = conn.cursor()
        instrument = _fetch_instrument(cur, instrument_id)
        if instrument is None:
            raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found.")
        broker = _fetch_broker(cur, broker_id)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_instrument_quote_url DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve quote URL.")
    finally:
        conn.close()

    # No trade to reference; the instrument's own ticker backs the search fallback.
    trade = {"ticker": instrument.get("ticker", "")}
    return build_quote_url(trade, instrument, broker)
