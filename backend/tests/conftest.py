"""Shared pytest fixtures.

Every test runs against a throwaway SQLite database in a temp directory — never
the real ~/TradeTracker/trades.db. We point db.DB_PATH at the temp file *before*
importing the application modules so that every `from db import DB_PATH` capture
(backup.py, settings.py, init_db.py) sees the temp path too.
"""
import pathlib
import sys
import tempfile

import pytest

# Make the backend package importable (this file lives in backend/tests/).
BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import db  # noqa: E402

# Redirect the database to a temp file for the whole test session.
_TMPDIR = pathlib.Path(tempfile.mkdtemp(prefix="tradenexus-tests-"))
db.DB_PATH = _TMPDIR / "test.db"

# Import application modules now that DB_PATH points at the temp DB. main.py runs
# run_startup_backup() at import; the temp DB does not exist yet, so it no-ops.
import init_db  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _fresh_db():
    """Drop the temp DB and recreate a clean, initialized schema."""
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(str(db.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    init_db.init()   # schema + migrations + default trade_types / settings / seed user


@pytest.fixture
def client():
    """A TestClient backed by a freshly initialized temp database."""
    _fresh_db()
    return TestClient(main.app)


@pytest.fixture
def user_id(client):
    """Create a user and return its id."""
    r = client.post("/users", json={"name": "Tester", "email": "tester@example.com"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_trade(client, uid, **overrides):
    """POST a trade with sensible defaults; return the response JSON."""
    body = {
        "ticker": "AAPL",
        "trade_type": "stock",
        "action": "buy",
        "quantity": 10,
        "price_per_unit": 100,
        "trade_date": "2026-05-01",
    }
    body.update(overrides)
    r = client.post(f"/users/{uid}/trades", json=body)
    assert r.status_code == 201, r.text
    return r.json()
