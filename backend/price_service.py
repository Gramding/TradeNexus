import abc
import datetime
import logging
import re
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class PriceSource(abc.ABC):
    @abc.abstractmethod
    def fetch(self, ticker: str) -> Optional[dict]:
        """Fetch a live price for *ticker*.

        Returns a dict with keys: price (float), currency (str), source (str).
        Returns None if the ticker is not found or the request fails.
        """


# ---------------------------------------------------------------------------
# Yahoo Finance implementation
# ---------------------------------------------------------------------------

class YahooFinanceSource(PriceSource):
    SOURCE_NAME = "yahoo_finance"

    def fetch(self, ticker: str) -> Optional[dict]:
        try:
            import yfinance as yf  # imported here so the module loads without yfinance present
            t = yf.Ticker(ticker)
            price = t.fast_info.last_price
            if price is None:
                logger.warning("yfinance returned None price for %s", ticker)
                return None
            currency = getattr(t.fast_info, "currency", None) or "USD"
            return {
                "price":    float(price),
                "currency": currency,
                "source":   self.SOURCE_NAME,
            }
        except Exception as exc:
            logger.warning("YahooFinanceSource.fetch(%s) failed: %s", ticker, exc)
            return None


# ---------------------------------------------------------------------------
# Instrument search (Yahoo Finance search API)
# ---------------------------------------------------------------------------

_YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
_SEARCH_RESULT_LIMIT = 8

# Map Yahoo's quoteType to our instruments.asset_class vocabulary. Anything not
# listed (INDEX, MUTUALFUND, OPTION, ...) falls back to 'other'.
_QUOTE_TYPE_TO_ASSET_CLASS = {
    "EQUITY":         "stock",
    "ETF":            "etf",
    "CRYPTOCURRENCY": "crypto",
    "CURRENCY":       "forex",
    "FUTURE":         "futures",
}


def _display_ticker(symbol: str) -> str:
    """Strip a Yahoo exchange/quote suffix to get a short display ticker:
    "VOD.L" -> "VOD", "BTC-USD" -> "BTC", "EURUSD=X" -> "EURUSD", "AAPL" -> "AAPL".
    """
    return re.split(r"[.\-=]", symbol, maxsplit=1)[0] or symbol


def search_instruments(query: str, limit: int = _SEARCH_RESULT_LIMIT) -> list[dict]:
    """Search Yahoo Finance for instruments matching *query*.

    Returns up to *limit* instrument dicts with keys: symbol, ticker, name,
    exchange, asset_class, currency. Raises on a network failure / timeout / bad
    HTTP status so the caller can fall back to local-only results.
    """
    import requests  # imported here so the module loads without requests present

    resp = requests.get(
        _YAHOO_SEARCH_URL,
        params={"q": query, "quotesCount": limit, "newsCount": 0},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=5,
    )
    resp.raise_for_status()
    quotes = resp.json().get("quotes", []) or []

    results: list[dict] = []
    for q in quotes:
        symbol = q.get("symbol")
        if not symbol:
            continue
        quote_type = (q.get("quoteType") or "").upper()
        results.append({
            "symbol":      symbol,
            "ticker":      _display_ticker(symbol),
            "name":        q.get("longname") or q.get("shortname"),
            "exchange":    q.get("exchange"),
            "asset_class": _QUOTE_TYPE_TO_ASSET_CLASS.get(quote_type, "other"),
            "currency":    q.get("currency") or "USD",
        })
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_SOURCES: dict[str, type[PriceSource]] = {
    "yahoo_finance": YahooFinanceSource,
}


def get_price_source(source_name: str) -> PriceSource:
    """Return an instantiated PriceSource for *source_name*.

    Raises ValueError for unknown sources so callers get a clear message and
    adding a new source only requires registering it in _SOURCES.
    """
    cls = _SOURCES.get(source_name)
    if cls is None:
        known = ", ".join(f"'{s}'" for s in sorted(_SOURCES))
        raise ValueError(
            f"Unknown price source '{source_name}'. "
            f"Supported sources: {known}."
        )
    return cls()


# ---------------------------------------------------------------------------
# Cache-aware fetch
# ---------------------------------------------------------------------------

def get_or_fetch_price(
    conn: sqlite3.Connection,
    symbol: str,
    source_name: str = "yahoo_finance",
    max_age_minutes: int = 15,
) -> Optional[dict]:
    """Return a price for the Yahoo Finance *symbol* (e.g. "VOD.L", "BTC-USD"),
    using price_cache when fresh enough.

    When *max_age_minutes* is 0 the cache is always bypassed (force-refresh).

    The returned dict contains:
        symbol, price, currency, source, fetched_at, from_cache (bool)

    Returns None if no cached value exists and the live fetch fails.
    """
    symbol = symbol.strip().upper()
    cur = conn.cursor()

    # ── Cache lookup (skipped when max_age_minutes == 0) ────────────────────
    if max_age_minutes > 0:
        cutoff = (
            datetime.datetime.utcnow() - datetime.timedelta(minutes=max_age_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT price, currency, fetched_at FROM price_cache "
            "WHERE symbol = ? AND source = ? AND fetched_at >= ?",
            (symbol, source_name, cutoff),
        )
        row = cur.fetchone()
        if row is not None:
            return {
                "symbol":      symbol,
                "price":       float(row[0]),
                "currency":    row[1],
                "source":      source_name,
                "fetched_at":  row[2],
                "from_cache":  True,
            }

    # ── Live fetch ───────────────────────────────────────────────────────────
    source = get_price_source(source_name)   # raises ValueError for unknown sources
    result = source.fetch(symbol)
    if result is None:
        return None

    fetched_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        """
        INSERT INTO price_cache (symbol, price, currency, fetched_at, source)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(symbol, source) DO UPDATE SET
            price      = excluded.price,
            currency   = excluded.currency,
            fetched_at = excluded.fetched_at
        """,
        (symbol, result["price"], result["currency"], fetched_at, source_name),
    )
    conn.commit()

    return {
        "symbol":     symbol,
        "price":      result["price"],
        "currency":   result["currency"],
        "source":     source_name,
        "fetched_at": fetched_at,
        "from_cache": False,
    }


def get_cached_price(
    conn: sqlite3.Connection,
    symbol: str,
    source_name: str = "yahoo_finance",
) -> Optional[dict]:
    """Return the cached price for the Yahoo *symbol* regardless of age, or None if
    there is no cache entry. Never performs a live fetch (used for passive autofill)."""
    symbol = symbol.strip().upper()
    cur = conn.execute(
        "SELECT price, currency, fetched_at FROM price_cache WHERE symbol = ? AND source = ?",
        (symbol, source_name),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "symbol":     symbol,
        "price":      float(row[0]),
        "currency":   row[1],
        "source":     source_name,
        "fetched_at": row[2],
        "from_cache": True,
    }
