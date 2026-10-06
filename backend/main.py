import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backup import run_startup_backup
from init_db import ensure_initialized
import brokers as brokers_module
import cash as cash_module
import events as events_module
import instruments as instruments_module
import positions as positions_module
import prices as prices_module
import quote_links as quote_links_module
import search as search_module
import settings as settings_module
import stats as stats_module
import trade_types as trade_types_module
import trades as trades_module
import users as users_module

logger = logging.getLogger(__name__)

# Snapshot the existing database before any migration, then make sure the schema
# and default settings/trade-types exist. On a fresh install this creates an empty
# but fully working database (no users) — see ensure_initialized().
try:
    run_startup_backup()
except Exception:
    logger.exception("Startup backup failed; continuing without a backup")

try:
    ensure_initialized()
except Exception:
    logger.exception("Database initialization failed; the app may not work")

app = FastAPI(title="TradeNexus")
app.include_router(brokers_module.router)
app.include_router(instruments_module.router)
app.include_router(prices_module.router)
app.include_router(quote_links_module.router)
app.include_router(settings_module.router)
app.include_router(trade_types_module.router)
app.include_router(users_module.router)
app.include_router(trades_module.router)
app.include_router(positions_module.router)
app.include_router(cash_module.router)
app.include_router(events_module.router)
app.include_router(search_module.router)
app.include_router(stats_module.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost:8765", "http://127.0.0.1:8765"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global error handlers
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})
