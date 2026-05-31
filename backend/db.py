import pathlib
import sqlite3

DB_PATH = pathlib.Path.home() / "TradeTracker" / "trades.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    # Performance pragmas, applied to every connection.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")  # 64MB page cache
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn
