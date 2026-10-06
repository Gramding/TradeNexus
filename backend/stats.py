"""Portfolio stats and the cumulative growth series."""
import datetime
import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

import stats_cache
from common import (
    _db,
    _require_user,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _fiscal_start_default(cur) -> int:
    """Read fiscal_year_start_month from app_settings, falling back to 1 (January)."""
    try:
        cur.execute("SELECT value FROM app_settings WHERE key = 'fiscal_year_start_month'")
        row = cur.fetchone()
        if row is not None:
            month = int(row[0])
            if 1 <= month <= 12:
                return month
    except (sqlite3.Error, ValueError, TypeError):
        pass
    return 1


@router.get("/users/{user_id}/stats")
def get_user_stats(
    user_id: int,
    fiscal_year_start_month: Optional[int] = Query(None, ge=1, le=12),
):
    # Only the default request (no explicit fiscal month) is cached; a cache hit
    # serves instantly without touching the database. An explicit override is
    # computed fresh and never read from or written to the cache.
    use_cache = fiscal_year_start_month is None
    if use_cache:
        cached = stats_cache.get_stats(user_id)
        if cached is not None:
            return cached

    conn = _db()
    try:
        cur = conn.cursor()
        _require_user(cur, user_id)

        # Default the fiscal-year start to the configured app setting.
        if fiscal_year_start_month is None:
            fiscal_year_start_month = _fiscal_start_default(cur)

        # Current fiscal-year window [start, next start): if today is before the
        # start month, the fiscal year began in the previous calendar year.
        today = datetime.date.today()
        fy_year = today.year if today.month >= fiscal_year_start_month else today.year - 1
        fy_start = datetime.date(fy_year, fiscal_year_start_month, 1)
        fy_end = datetime.date(fy_year + 1, fiscal_year_start_month, 1)

        # Each metric is its own focused query — SQLite plans small targeted
        # queries better than one big multi-aggregate scan. Value aggregations use
        # net_total_value (commission-adjusted), falling back to total_value for any
        # legacy row where it is NULL.
        cur.execute("SELECT COUNT(*) FROM trades WHERE user_id = ?", (user_id,))
        total_trades = cur.fetchone()[0]

        # Value aggregations are converted to the base currency with each row's
        # fx_rate (1.0 for same-currency / legacy rows) so a multi-currency
        # portfolio sums correctly instead of mixing units.
        cur.execute(
            "SELECT COALESCE(SUM(COALESCE(net_total_value, total_value) * COALESCE(fx_rate, 1)), 0) "
            "FROM trades WHERE user_id = ? AND action = 'buy'",
            (user_id,),
        )
        buy_volume = cur.fetchone()[0]

        cur.execute(
            "SELECT COALESCE(SUM(COALESCE(net_total_value, total_value) * COALESCE(fx_rate, 1)), 0) "
            "FROM trades WHERE user_id = ? AND action = 'sell'",
            (user_id,),
        )
        sell_volume = cur.fetchone()[0]

        cur.execute(
            "SELECT ticker FROM trades WHERE user_id = ? "
            "GROUP BY ticker ORDER BY COUNT(*) DESC LIMIT 1",
            (user_id,),
        )
        top_row = cur.fetchone()

        cur.execute(
            "SELECT trade_type, COUNT(*), SUM(COALESCE(net_total_value, total_value) * COALESCE(fx_rate, 1)) "
            "FROM trades WHERE user_id = ? "
            "GROUP BY trade_type ORDER BY trade_type",
            (user_id,),
        )
        by_type_rows = cur.fetchall()

        cur.execute(
            """
            SELECT strftime('%Y-%m', trade_date) AS month,
                   SUM(COALESCE(net_total_value, total_value) * COALESCE(fx_rate, 1)) AS volume
            FROM trades
            WHERE user_id = ?
              AND trade_date >= date('now', 'start of month', '-11 months')
            GROUP BY strftime('%Y-%m', trade_date)
            ORDER BY strftime('%Y-%m', trade_date)
            """,
            (user_id,),
        )
        monthly_rows = cur.fetchall()

        # Total commissions: every trade row carries its own commission (buy rows
        # hold the buy fee, synthetic sell rows hold the sell fee), converted to
        # base currency with the row's fx_rate.
        cur.execute(
            "SELECT COALESCE(SUM(commission * COALESCE(fx_rate, 1)), 0) FROM trades WHERE user_id = ?",
            (user_id,),
        )
        total_commissions = cur.fetchone()[0]

        # Event-driven income/expense in base currency (signed by event_type).
        cur.execute(
            "SELECT transaction_type, COALESCE(SUM(amount), 0) FROM cash_pool "
            "WHERE user_id = ? AND transaction_type IN ('dividend', 'interest', 'fee') "
            "GROUP BY transaction_type",
            (user_id,),
        )
        event_totals = {t: float(a) for t, a in cur.fetchall()}
        dividend_income = event_totals.get("dividend", 0.0)
        interest_income = event_totals.get("interest", 0.0)
        fees_paid       = -event_totals.get("fee", 0.0)  # stored negative; report as positive expense

        # Net realized P&L: sell_lots.realized_pnl is already net of both the sell
        # commission and the proportional buy commission.
        cur.execute(
            "SELECT COALESCE(SUM(sl.realized_pnl), 0) "
            "FROM sell_lots sl JOIN trades t ON sl.buy_trade_id = t.id "
            "WHERE t.user_id = ?",
            (user_id,),
        )
        net_realized_pnl = cur.fetchone()[0]

        # Total trade volume within the current fiscal-year window.
        cur.execute(
            "SELECT COALESCE(SUM(COALESCE(net_total_value, total_value) * COALESCE(fx_rate, 1)), 0) "
            "FROM trades WHERE user_id = ? AND trade_date >= ? AND trade_date < ?",
            (user_id, fy_start.isoformat(), fy_end.isoformat()),
        )
        this_fiscal_year_volume = cur.fetchone()[0]

    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.error("get_user_stats DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load stats.")
    finally:
        conn.close()

    result = {
        "total_trades":       int(total_trades),
        "buy_volume":         float(buy_volume),
        "sell_volume":        float(sell_volume),
        "net_position":       float(sell_volume) - float(buy_volume),
        "total_commissions":  float(total_commissions),
        "dividend_income":    float(dividend_income),
        "interest_income":    float(interest_income),
        "fees_paid":          float(fees_paid),
        "net_realized_pnl":   float(net_realized_pnl),
        "this_fiscal_year_volume": float(this_fiscal_year_volume),
        "fiscal_year_start":  fy_start.isoformat(),
        "most_traded_ticker": top_row[0] if top_row else None,
        "by_trade_type": [
            {"trade_type": r[0], "trade_count": int(r[1]), "volume": float(r[2])}
            for r in by_type_rows
        ],
        "monthly_volume": [
            {"month": r[0], "volume": float(r[1])}
            for r in monthly_rows
        ],
        "last_computed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }

    if use_cache:
        stats_cache.set_stats(user_id, result)
    return result


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/stats/growth")
def get_user_growth(
    user_id: int,
    date_from: Optional[str] = Query(
        None,
        description="ISO date; omit for the last year, pass '' for all history.",
    ),
):
    # Resolve the window:
    #   param omitted  -> default first-load view of the last year
    #   param == ''    -> everything (the "All" button)
    #   ISO date       -> only points on/after that date
    if date_from is None:
        cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    elif date_from == "":
        cutoff = None
    else:
        try:
            cutoff = datetime.date.fromisoformat(date_from).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from must be an ISO date (YYYY-MM-DD).")

    # The full (unfiltered) growth series is cached per user; date_from only slices
    # it in Python, so changing the window never re-runs the aggregation.
    full = stats_cache.get_growth(user_id)
    if full is None:
        conn = _db()
        try:
            cur = conn.cursor()
            _require_user(cur, user_id)

            # Both series are running totals over time, so instead of recomputing a
            # full SUM for every event date (O(dates × trades) — the old correlated
            # subqueries), collapse each side to a per-date delta in one pass and
            # accumulate in Python below. A buy contributes a fixed amount on its
            # trade_date (its current remaining value, for open/partial lots); a sell
            # contributes its realized P&L on its sell_date.
            cur.execute(
                """
                WITH user_buys AS (
                    SELECT trade_date, remaining_quantity, net_total_value,
                           total_value, commission, quantity, status,
                           COALESCE(fx_rate, 1) AS fx_rate
                    FROM   trades
                    WHERE  user_id = ? AND action = 'buy'
                ),
                user_sells AS (
                    SELECT sl.sell_date AS sell_date, sl.realized_pnl AS realized_pnl
                    FROM   sell_lots sl
                    JOIN   trades    t ON sl.buy_trade_id = t.id
                    WHERE  t.user_id = ?
                )
                SELECT date, SUM(cost_basis_delta) AS cost_basis_delta,
                             SUM(realized_pnl_delta) AS realized_pnl_delta
                FROM (
                    SELECT date(trade_date) AS date,
                           SUM(CASE WHEN status IN ('open', 'partial')
                                    THEN remaining_quantity
                                         * COALESCE(net_total_value, total_value + commission)
                                         / NULLIF(quantity, 0)
                                         * fx_rate
                                    ELSE 0 END) AS cost_basis_delta,
                           0.0 AS realized_pnl_delta
                    FROM   user_buys
                    GROUP  BY date(trade_date)
                    UNION ALL
                    SELECT date(sell_date) AS date,
                           0.0 AS cost_basis_delta,
                           SUM(realized_pnl) AS realized_pnl_delta
                    FROM   user_sells
                    GROUP  BY date(sell_date)
                )
                GROUP BY date
                ORDER BY date
                """,
                (user_id, user_id),
            )
            rows = cur.fetchall()
        except HTTPException:
            raise
        except sqlite3.Error as exc:
            logger.error("get_user_growth DB error: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to load growth data.")
        finally:
            conn.close()

        # Accumulate the per-date deltas into the running cost-basis / realized-P&L
        # series. Equivalent to the old cumulative SUMs, but single-pass.
        full = []
        cost_basis = 0.0
        realized_pnl = 0.0
        for date, cb_delta, pnl_delta in rows:
            cost_basis   += cb_delta or 0.0
            realized_pnl += pnl_delta or 0.0
            full.append({
                "date":         date,
                "cost_basis":   cost_basis,
                "realized_pnl": realized_pnl,
            })
        stats_cache.set_growth(user_id, full)

    if cutoff is None:
        return full
    # Rows are ordered by date; ISO date strings compare correctly lexicographically.
    return [pt for pt in full if pt["date"] >= cutoff]
