import abc
import datetime
import logging
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
    ticker: str,
    source_name: str = "yahoo_finance",
    max_age_minutes: int = 15,
) -> Optional[dict]:
    """Return a price for *ticker*, using price_cache when fresh enough.

    When *max_age_minutes* is 0 the cache is always bypassed (force-refresh).

    The returned dict contains:
        ticker, price, currency, source, fetched_at, from_cache (bool)

    Returns None if no cached value exists and the live fetch fails.
    """
    ticker = ticker.strip().upper()
    cur = conn.cursor()

    # ── Cache lookup (skipped when max_age_minutes == 0) ────────────────────
    if max_age_minutes > 0:
        cutoff = (
            datetime.datetime.utcnow() - datetime.timedelta(minutes=max_age_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT price, currency, fetched_at FROM price_cache "
            "WHERE ticker = ? AND source = ? AND fetched_at >= ?",
            (ticker, source_name, cutoff),
        )
        row = cur.fetchone()
        if row is not None:
            return {
                "ticker":      ticker,
                "price":       float(row[0]),
                "currency":    row[1],
                "source":      source_name,
                "fetched_at":  row[2],
                "from_cache":  True,
            }

    # ── Live fetch ───────────────────────────────────────────────────────────
    source = get_price_source(source_name)   # raises ValueError for unknown sources
    result = source.fetch(ticker)
    if result is None:
        return None

    fetched_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        """
        INSERT INTO price_cache (ticker, price, currency, fetched_at, source)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticker, source) DO UPDATE SET
            price      = excluded.price,
            currency   = excluded.currency,
            fetched_at = excluded.fetched_at
        """,
        (ticker, result["price"], result["currency"], fetched_at, source_name),
    )
    conn.commit()

    return {
        "ticker":     ticker,
        "price":      result["price"],
        "currency":   result["currency"],
        "source":     source_name,
        "fetched_at": fetched_at,
        "from_cache": False,
    }


def get_cached_price(
    conn: sqlite3.Connection,
    ticker: str,
    source_name: str = "yahoo_finance",
) -> Optional[dict]:
    """Return the cached price for *ticker* regardless of age, or None if there is
    no cache entry. Never performs a live fetch (used for passive autofill)."""
    ticker = ticker.strip().upper()
    cur = conn.execute(
        "SELECT price, currency, fetched_at FROM price_cache WHERE ticker = ? AND source = ?",
        (ticker, source_name),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "ticker":     ticker,
        "price":      float(row[0]),
        "currency":   row[1],
        "source":     source_name,
        "fetched_at": row[2],
        "from_cache": True,
    }
