"""Foreign-exchange rates, cached like prices.

A rate is "how many units of `to_currency` equal one unit of `from_currency`",
e.g. get_or_fetch_fx(conn, "EUR", "USD") -> 1.08 means 1 EUR = 1.08 USD. Rates
are fetched from Yahoo Finance via the FX pair symbol "{FROM}{TO}=X" (reusing the
price source) and cached in the fx_rates table.

Same-currency conversions short-circuit to 1.0 and never hit the network, so a
single-currency (USD-only) user — and the offline test suite — never fetch.
"""
import datetime
import logging
import sqlite3
from typing import Optional

from price_service import get_price_source

logger = logging.getLogger(__name__)


def _fx_symbol(from_currency: str, to_currency: str) -> str:
    """Yahoo FX pair symbol, e.g. ("EUR", "USD") -> "EURUSD=X"."""
    return f"{from_currency.upper()}{to_currency.upper()}=X"


def get_or_fetch_fx(
    conn: sqlite3.Connection,
    from_currency: str,
    to_currency: str,
    source_name: str = "yahoo_finance",
    max_age_minutes: int = 720,
) -> Optional[float]:
    """Return the FX rate from_currency -> to_currency, using the fx_rates cache
    when fresh enough (default 12h — FX moves slowly for a trade tracker).

    Returns 1.0 when the currencies match. Returns None when no cached rate exists
    and the live fetch fails, so callers can decide how to fall back.
    """
    frm = (from_currency or "").strip().upper()
    to = (to_currency or "").strip().upper()
    if not frm or not to or frm == to:
        return 1.0

    cur = conn.cursor()
    if max_age_minutes > 0:
        cutoff = (
            datetime.datetime.utcnow() - datetime.timedelta(minutes=max_age_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT rate FROM fx_rates "
            "WHERE from_currency = ? AND to_currency = ? AND source = ? AND fetched_at >= ?",
            (frm, to, source_name, cutoff),
        )
        row = cur.fetchone()
        if row is not None:
            return float(row[0])

    source = get_price_source(source_name)
    result = source.fetch(_fx_symbol(frm, to))
    if result is None or not result.get("price"):
        return None
    rate = float(result["price"])

    fetched_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        """
        INSERT INTO fx_rates (from_currency, to_currency, rate, fetched_at, source)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(from_currency, to_currency, source) DO UPDATE SET
            rate       = excluded.rate,
            fetched_at = excluded.fetched_at
        """,
        (frm, to, rate, fetched_at, source_name),
    )
    conn.commit()
    return rate


def get_cached_fx(
    conn: sqlite3.Connection,
    from_currency: str,
    to_currency: str,
    source_name: str = "yahoo_finance",
) -> Optional[float]:
    """Return a cached FX rate regardless of age (1.0 for same currency), or None."""
    frm = (from_currency or "").strip().upper()
    to = (to_currency or "").strip().upper()
    if frm == to:
        return 1.0
    row = conn.execute(
        "SELECT rate FROM fx_rates WHERE from_currency = ? AND to_currency = ? AND source = ?",
        (frm, to, source_name),
    ).fetchone()
    return float(row[0]) if row is not None else None
