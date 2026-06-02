import datetime
import logging
import os
import sqlite3
import tempfile

from fastapi import APIRouter, Body, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from db import DB_PATH, get_connection
from backup import run_startup_backup
import stats_cache

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])

SQLITE_MAGIC = b"SQLite format 3\x00"

# The settings that may be read/written, with per-key validation.
DATE_FORMATS = {"MM/DD/YYYY", "DD/MM/YYYY", "DD.MM.YYYY", "YYYY-MM-DD"}
REFRESH_INTERVALS = {5, 15, 30, 60}
# UI languages we ship locale files for (frontend/locales/*.json).
SUPPORTED_LANGUAGES = {"en", "de"}
ALLOWED_SETTINGS = {
    "display_name",
    "currency",
    "base_currency",
    "language",
    "date_format",
    "decimal_separator",
    "price_refresh_interval_minutes",
    "default_broker_id",
    "fiscal_year_start_month",
    "date_format_manual_override",
}


def _validate_setting(key: str, value) -> str:
    """Validate one setting and return its normalized string form for storage."""
    if key not in ALLOWED_SETTINGS:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")

    if key == "fiscal_year_start_month":
        try:
            month = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="fiscal_year_start_month must be an integer 1-12.")
        if not 1 <= month <= 12:
            raise HTTPException(status_code=400, detail="fiscal_year_start_month must be between 1 and 12.")
        return str(month)

    if key == "price_refresh_interval_minutes":
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="price_refresh_interval_minutes must be one of 5, 15, 30, 60.")
        if minutes not in REFRESH_INTERVALS:
            raise HTTPException(status_code=400, detail="price_refresh_interval_minutes must be one of 5, 15, 30, 60.")
        return str(minutes)

    if key == "decimal_separator":
        if value not in (".", ","):
            raise HTTPException(status_code=400, detail="decimal_separator must be '.' or ','.")
        return value

    if key == "date_format":
        if value not in DATE_FORMATS:
            raise HTTPException(status_code=400, detail=f"date_format must be one of {sorted(DATE_FORMATS)}.")
        return value

    if key == "language":
        if value not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=400, detail=f"language must be one of {sorted(SUPPORTED_LANGUAGES)}.")
        return value

    if key == "date_format_manual_override":
        if str(value) not in ("0", "1"):
            raise HTTPException(status_code=400, detail="date_format_manual_override must be '0' or '1'.")
        return str(value)

    if key == "base_currency":
        s = str(value or "").strip().upper()
        if len(s) != 3 or not s.isalpha():
            raise HTTPException(status_code=400, detail="base_currency must be a 3-letter ISO code (e.g. USD, EUR).")
        return s

    # display_name, currency, default_broker_id: free-form strings.
    return "" if value is None else str(value)


def _read_all_settings(conn) -> dict:
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {row[0]: row[1] for row in rows}


@router.get("/settings")
def get_settings():
    conn = get_connection()
    try:
        return _read_all_settings(conn)
    except sqlite3.Error as exc:
        logger.error("get_settings DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load settings.")
    finally:
        conn.close()


@router.put("/settings")
def update_settings(payload: dict = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    # Validate everything before writing anything.
    normalized = {key: _validate_setting(key, value) for key, value in payload.items()}

    # `currency` (display) and `base_currency` (reporting/FX base) are kept in sync
    # so the app has a single reporting currency. Setting either updates both,
    # unless the request explicitly sets both to different values.
    if "currency" in normalized and "base_currency" not in normalized:
        normalized["base_currency"] = _validate_setting("base_currency", normalized["currency"])
    elif "base_currency" in normalized and "currency" not in normalized:
        normalized["currency"] = normalized["base_currency"]

    conn = get_connection()
    try:
        for key, value in normalized.items():
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        conn.commit()
        # Cached stats are computed against the configured fiscal-year start, so a
        # change to it must drop the cache or the next read serves a stale window.
        if "fiscal_year_start_month" in normalized:
            stats_cache.invalidate_all()
        return _read_all_settings(conn)
    except sqlite3.Error as exc:
        logger.error("update_settings DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update settings.")
    finally:
        conn.close()


@router.get("/settings/price-cache")
def price_cache_count():
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
        return {"count": int(count)}
    except sqlite3.Error as exc:
        logger.error("price_cache_count DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read the price cache.")
    finally:
        conn.close()


@router.delete("/settings/price-cache")
def clear_price_cache():
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM price_cache")
        conn.commit()
        return {"deleted": cur.rowcount}
    except sqlite3.Error as exc:
        logger.error("clear_price_cache DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to clear the price cache.")
    finally:
        conn.close()


@router.get("/settings/db-stats")
def db_stats():
    """Report row counts, DB file size, and existing indexes so index creation
    can be verified."""
    conn = get_connection()
    try:
        trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        sell_lots = conn.execute("SELECT COUNT(*) FROM sell_lots").fetchone()[0]
        cash_pool = conn.execute("SELECT COUNT(*) FROM cash_pool").fetchone()[0]
        indexes = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
            ).fetchall()
        ]
    except sqlite3.Error as exc:
        logger.error("db_stats DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read database stats.")
    finally:
        conn.close()

    size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "trades": int(trades),
        "sell_lots": int(sell_lots),
        "cash_pool": int(cash_pool),
        "db_size_mb": round(size_bytes / (1024 * 1024), 2),
        "indexes": indexes,
    }


@router.get("/settings/backup")
def download_backup():
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="No database file exists yet.")

    filename = f"trades_backup_{datetime.date.today().isoformat()}.db"
    return FileResponse(
        path=DB_PATH,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/settings/restore")
async def restore_backup(file: UploadFile = File(...)):
    contents = await file.read()

    if contents[:16] != SQLITE_MAGIC:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid SQLite database.",
        )

    # Back up the current database before overwriting it.
    try:
        run_startup_backup()
    except Exception:
        logger.exception("Backup before restore failed")
        raise HTTPException(
            status_code=500,
            detail="Could not back up the current database; restore aborted.",
        )

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file in the same directory, then atomically replace.
    fd, tmp_path = tempfile.mkstemp(dir=DB_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(contents)
        os.replace(tmp_path, DB_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        logger.exception("Failed to write restored database")
        raise HTTPException(status_code=500, detail="Failed to write the restored database.")

    # Drop stale WAL sidecar files so the new database is read cleanly.
    for suffix in ("-wal", "-shm"):
        sidecar = DB_PATH.with_name(DB_PATH.name + suffix)
        if sidecar.exists():
            sidecar.unlink()

    # The whole database was replaced, so every cached stats/growth result is stale.
    stats_cache.invalidate_all()

    return {"message": "Database restored successfully. Previous database was backed up."}
