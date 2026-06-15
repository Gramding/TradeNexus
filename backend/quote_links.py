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

# An ISIN: 2-letter country code, 9 alphanumerics, 1 check digit. Used to recover
# the ISIN for an {isin}/isin-keyed template when the dedicated isin column is
# blank but the value lives in symbol/ticker (e.g. ISIN-keyed instruments store
# the ISIN as symbol, or a free-text trade is logged under its ISIN).
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _isin_like(value) -> Optional[str]:
    """Return the normalized ISIN if *value* is ISIN-shaped, else None."""
    if value:
        v = str(value).strip().upper()
        if _ISIN_RE.match(v):
            return v
    return None

# onvista's search redirects to the canonical instrument page for any type (stock,
# ETF, fund, bond), so an ISIN — or a ticker — is enough to deep-link.
_ONVISTA_SEARCH = "https://www.onvista.de/suche/?searchValue={}"


# ---------------------------------------------------------------------------
# Core resolver (pure, no DB)
# ---------------------------------------------------------------------------

def _ensure_https(url: str) -> str:
    """Guard: every URL this module hands back must be an absolute https URL.
    Blocks http://, javascript:, file:, and anything else."""
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError(f"Refusing to return a non-https quote URL: {url!r}")
    return url


def build_quote_url(
    trade: dict,
    instrument: Optional[dict],
    broker: Optional[dict],
    source: str = "yahoo_finance",
) -> dict:
    """Resolve the best available quote URL via a strict fallback chain.

    The broker deep link always wins when configured. Otherwise the link targets
    the *selected price source* rather than always Yahoo — so an Onvista portfolio's
    tickers open onvista.de, matching where the prices come from.

    The fallback follows the broker's own `price_source` when set, otherwise the
    global `source`. Onvista is "sticky": if *either* the broker or the global setting
    selects Onvista the link targets onvista.de (by ISIN) — so we never silently
    default to Yahoo when the user has chosen Onvista anywhere, even if the broker's
    own price_source is still at its Yahoo default. Yahoo is reached only when neither
    source is Onvista.

    Returns {url, source, label} where source is one of 'broker', 'yahoo',
    'onvista', 'search_fallback', or 'onvista_search'. url is always an https://
    string (else ValueError).
    """
    # Resolve the effective fallback source. The broker's own price source takes
    # precedence, but Onvista chosen *anywhere* in the chain wins — a broker left at
    # the default Yahoo must not clobber a global Onvista setting, and vice-versa.
    broker_source = broker.get("price_source") if broker else None
    if broker_source == "onvista" or source == "onvista":
        source = "onvista"
    elif broker_source:
        source = broker_source

    # 1. Broker deep link -------------------------------------------------------
    if broker is not None and broker.get("quote_url_template"):
        template = broker["quote_url_template"]
        key = broker.get("quote_url_key") or "symbol"
        # Identifier fields come from the linked instrument when present. For a
        # free-text trade (no instrument link) we fall back to the trade's ticker so
        # {ticker}/{symbol}/{value} templates still resolve — most logged trades
        # have no instrument, and going to the broker beats falling back to Yahoo.
        # isin/exchange can't be inferred without an instrument, so they stay None
        # and templates needing them fall through to the source link.
        tkr = (instrument.get("ticker") if instrument else None) or trade.get("ticker")
        sym = (instrument.get("symbol") if instrument else None) or tkr
        # The dedicated isin column is sometimes blank while the ISIN lives in
        # symbol/ticker (ISIN-keyed instruments store the ISIN as symbol, and
        # free-text trades are often logged under their ISIN). Recover it so an
        # {isin}/isin-keyed broker template still resolves instead of falling
        # through to the search fallback.
        isin = (instrument.get("isin") if instrument else None) or None
        if not _isin_like(isin):
            isin = _isin_like(sym) or _isin_like(tkr) or _isin_like(trade.get("ticker")) or isin
        subs = {
            "ticker":   tkr,
            "symbol":   sym,
            "isin":     isin,
            "exchange": instrument.get("exchange") if instrument else None,
        }
        # {value} follows the broker's chosen key.
        subs["value"] = subs.get(_KEY_FIELDS.get(key, "symbol"))
        used = set(_PLACEHOLDER_RE.findall(template))
        # Build only when every placeholder is known and resolves to a non-empty
        # value (e.g. a {isin} template on an instrument with no ISIN skips on).
        if used and used <= set(subs) and all(subs[p] for p in used):
            url = _PLACEHOLDER_RE.sub(
                lambda m: urllib.parse.quote(str(subs[m.group(1)]), safe=""),
                template,
            )
            # A misconfigured template (non-https) skips to the source fallback
            # rather than erroring the whole request.
            if url.startswith("https://"):
                broker_name = broker.get("name") or "broker"
                return {
                    "url":    _ensure_https(url),
                    "source": "broker",
                    "label":  f"View on {broker_name}",
                }

    # 2. Selected price source's instrument page --------------------------------
    if source == "onvista":
        # onvista deep-links by ISIN (preferred) or ticker via its search redirect.
        key = (instrument.get("isin") or instrument.get("ticker")) if instrument else None
        key = key or trade.get("ticker")
        if key:
            url = _ONVISTA_SEARCH.format(urllib.parse.quote(str(key), safe=""))
            return {
                "url":    _ensure_https(url),
                "source": "onvista",
                "label":  "View on Onvista",
            }
    elif instrument is not None and instrument.get("symbol"):
        url = f"https://finance.yahoo.com/quote/{urllib.parse.quote(str(instrument['symbol']), safe='')}"
        return {
            "url":    _ensure_https(url),
            "source": "yahoo",
            "label":  "View on Yahoo Finance",
        }

    # 3. Search fallback (always works), still on the selected source -----------
    ticker = (instrument.get("ticker") if instrument else trade.get("ticker", "")) or ""
    if source == "onvista":
        url = _ONVISTA_SEARCH.format(urllib.parse.quote(str(ticker), safe=""))
        return {
            "url":    _ensure_https(url),
            "source": "onvista_search",
            "label":  f"Search {ticker} on Onvista",
        }
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


def _active_price_source(cur: sqlite3.Cursor) -> str:
    """The globally selected price source (Settings); drives the non-broker link
    fallback so it matches where prices are fetched. Defaults to Yahoo."""
    row = cur.execute("SELECT value FROM app_settings WHERE key = 'price_source'").fetchone()
    return (row[0] if row and row[0] else "yahoo_finance")


def _fetch_broker(cur: sqlite3.Cursor, broker_id) -> Optional[dict]:
    if broker_id is None:
        return None
    cur.execute(
        "SELECT id, name, quote_url_template, quote_url_key, price_source FROM brokers WHERE id = ?",
        (broker_id,),
    )
    r = cur.fetchone()
    if r is None:
        return None
    return {
        "id": r[0], "name": r[1], "quote_url_template": r[2],
        "quote_url_key": r[3] or "symbol", "price_source": r[4],
    }


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
        source = _active_price_source(cur)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_trade_quote_url DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve quote URL.")
    finally:
        conn.close()

    return build_quote_url(trade, instrument, broker, source)


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
        source = _active_price_source(cur)
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_instrument_quote_url DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve quote URL.")
    finally:
        conn.close()

    # No trade to reference; the instrument's own ticker backs the search fallback.
    trade = {"ticker": instrument.get("ticker", "")}
    return build_quote_url(trade, instrument, broker, source)
