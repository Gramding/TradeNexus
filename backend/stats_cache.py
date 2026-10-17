"""In-memory caches for the expensive stats and growth aggregations.

Both are keyed by user_id with no TTL — an entry only disappears when a trade or
sell_lot for that user is written (created / updated / deleted), the user is
deleted, or the whole database is replaced (restore). This makes repeated stats
and growth views load instantly without re-running the aggregations.

A lock guards every access because FastAPI runs sync routes in a threadpool, so
reads and writes can land concurrently.
"""
import threading

_lock = threading.Lock()
_stats: dict[int, dict] = {}
_growth: dict[int, list] = {}
# Trades-list total_count per filter tuple; element 0 of the key is the user id.
_counts: dict[tuple, int] = {}


def get_stats(user_id: int):
    with _lock:
        return _stats.get(user_id)


def set_stats(user_id: int, value: dict) -> None:
    with _lock:
        _stats[user_id] = value


def get_growth(user_id: int):
    with _lock:
        return _growth.get(user_id)


def set_growth(user_id: int, value: list) -> None:
    with _lock:
        _growth[user_id] = value


def get_count(key: tuple):
    with _lock:
        return _counts.get(key)


def set_count(key: tuple, value: int) -> None:
    with _lock:
        _counts[key] = value


def invalidate(user_id: int) -> None:
    """Drop cached stats, growth and trade counts for one user after a write."""
    with _lock:
        _stats.pop(user_id, None)
        _growth.pop(user_id, None)
        for key in [k for k in _counts if k[0] == user_id]:
            del _counts[key]


def invalidate_all() -> None:
    """Drop everything — used when the entire database is replaced (restore)."""
    with _lock:
        _stats.clear()
        _growth.clear()
        _counts.clear()
