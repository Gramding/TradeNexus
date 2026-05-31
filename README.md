# TradeNexus

A desktop application for tracking stock and options trades, positions, realized/unrealized P&L, cash flow, and portfolio analytics. TradeNexus runs entirely on your machine — a local FastAPI backend with a SQLite database, a vanilla-JS frontend, and an Electron shell that bundles them into a single installable app.

> All data lives in a local SQLite file (`~/TradeTracker/trades.db`). There is no cloud account, no telemetry, and no external database. The only network calls are to Yahoo Finance for price quotes.

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation (development)](#installation-development)
- [Running in development](#running-in-development)
- [Seeding mock data](#seeding-mock-data)
- [Building a distributable app](#building-a-distributable-app)
- [Data, backups & configuration](#data-backups--configuration)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [API reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Trade tracking** — record buy/sell trades with ticker, type, quantity, price, broker, commission, and notes. Sortable, filterable, duplicable, and CSV-exportable.
- **Positions** — open/partial lots grouped by ticker with average cost, cost basis, live current price, and unrealized P&L (sortable).
- **Sell flow** — partial or full sells against specific buy lots, with commission-adjusted realized P&L recorded to a sell-lot ledger.
- **Cash pool** — per-user balance tracking with deposits, withdrawals, and automatic buy/sell cash movements. The Add Trade form warns when a buy exceeds your cash balance.
- **Analytics** — total/buy/sell volume, net position, commissions, realized P&L, monthly volume and trade-type breakdown charts, a cumulative growth chart with selectable ranges (3M / 6M / 1Y / **This fiscal year** / All), and a configurable fiscal-year window.
- **Brokers** — per-broker commission models (flat + per-unit), colors, and a configurable default broker.
- **Trade types** — built-in (Stock, Call, Put, Other) plus user-defined custom types, with rename-cascades-to-trades and safe deletion.
- **Global search** — a command-palette search bar (focus with `/`) across trades, positions, and cash transactions, with click-to-navigate and row highlighting.
- **Settings** — display name, currency, date format, decimal separator, price-refresh interval, fiscal-year start; broker management; trade-type management; database backup/restore; and price-cache clearing.
- **Convenience** — passive price autofill from cache on ticker blur, time-of-day greeting, light/dark theme, UI scaling, keyboard shortcuts, and a startup database backup (keeps the 7 most recent).

---

## Architecture

```
┌──────────────────────── Electron desktop shell ────────────────────────┐
│                                                                          │
│   electron/main.js                                                       │
│     • spawns the backend binary, polls /health, then opens the window    │
│     • loads frontend/index.html into a BrowserWindow                      │
│                                                                          │
│   ┌─────────────────────┐         HTTP (localhost:8765)                  │
│   │  Frontend (vanilla)  │  ───────────────────────────►  ┌───────────┐  │
│   │  index.html          │                                │  FastAPI   │  │
│   │  static/js/app.js     │  ◄───────────────────────────  │  backend   │  │
│   │  static/js/formatting │            JSON                 │  (uvicorn) │  │
│   │  Chart.js (CDN)       │                                └─────┬─────┘  │
│   └─────────────────────┘                                        │        │
│                                                            SQLite │        │
│                                                   ~/TradeTracker/ │        │
│                                                        trades.db ◄┘        │
└──────────────────────────────────────────────────────────────────────────┘
                                                          │
                                                   Yahoo Finance (yfinance)
```

| Layer    | Technology |
|----------|------------|
| Backend  | Python · FastAPI · Uvicorn · SQLite (stdlib `sqlite3`) · yfinance |
| Frontend | Plain HTML/CSS/JavaScript (no framework) · Chart.js (via CDN) |
| Desktop  | Electron · electron-builder · PyInstaller (backend → single binary) |

The backend listens on **`http://localhost:8765`** and exposes a health check at `/health`. The frontend's API base URL is hardcoded to that address in `frontend/static/js/app.js`.

---

## Project structure

```
TradeNexus/
├── backend/                 # FastAPI application
│   ├── entrypoint.py        # uvicorn launcher (serves on :8765)
│   ├── main.py              # app, users, trades, sell lots, positions, cash, stats, search
│   ├── brokers.py           # broker CRUD router
│   ├── prices.py            # price + cached-price routes
│   ├── price_service.py     # cache lookup + Yahoo Finance fetch
│   ├── settings.py          # app settings, backup/restore, price-cache
│   ├── trade_types.py       # trade-type CRUD router
│   ├── backup.py            # startup database backup
│   ├── db.py                # SQLite connection + DB path
│   ├── init_db.py           # schema creation, migrations, default seeds
│   ├── schema.sql           # table definitions
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   └── static/
│       ├── css/style.css
│       └── js/
│           ├── app.js        # all UI logic
│           └── formatting.js # currency/number/date formatting
├── electron/
│   ├── main.js              # spawns backend, opens window
│   └── preload.js
├── seed.py                  # wipe + repopulate with realistic mock data
├── build.py                 # PyInstaller build + smoke test
├── build-all.sh             # full build: PyInstaller → electron-builder
├── package.json             # Electron / electron-builder config
└── README.md
```

---

## Prerequisites

- **Python 3.10 or newer** (the project is developed against 3.14)
- **Node.js 18 or newer** and npm (required for the Electron shell / packaging)
- Internet access for live price quotes (cached prices work offline)
- OS: Linux, macOS, or Windows

---

## Installation (development)

From the project root:

### 1. Backend (Python virtual environment)

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt
```

> On Windows use `.venv\Scripts\python` and `.venv\Scripts\pip` in place of `.venv/bin/...`.

### 2. Initialize the database

The server does **not** create the schema automatically — run the initializer once. It creates `~/TradeTracker/trades.db`, applies migrations, and seeds default settings and trade types (it is safe to re-run; it never drops existing tables):

```bash
.venv/bin/python backend/init_db.py
```

*(Optional)* To start with realistic demo data instead, see [Seeding mock data](#seeding-mock-data). **`seed.py` wipes existing data**, so only use it on a fresh/throwaway database.

### 3. Frontend / Electron dependencies

```bash
npm install
```

---

## Running in development

There are two workflows depending on what you're iterating on.

### Option A — Backend + browser (fastest loop)

Run the API directly with uvicorn (auto-reload-friendly while editing Python):

```bash
.venv/bin/python backend/entrypoint.py
```

This serves the API on `http://localhost:8765`. Then open the frontend in a browser. Because the frontend fetches from `localhost:8765` (and the backend allows all CORS origins), the simplest approach is a static server:

```bash
cd frontend
python3 -m http.server 5173
# then visit http://localhost:5173
```

Edit `frontend/static/js/*.js` or `style.css` and refresh the page — no rebuild needed.

### Option B — Full Electron app

The Electron shell launches the **PyInstaller-built backend binary** (`dist/tradenexus`), not the Python source. Build the backend binary first, then start Electron:

```bash
.venv/bin/python build.py --build      # produces dist/tradenexus
npm start                              # electron . → spawns dist/tradenexus, opens the window
```

Electron polls `/health` for up to 30 seconds before showing the window. If the backend can't start, it shows an error dialog.

---

## Seeding mock data

`seed.py` resets the core tables and generates 12 demo users with realistic brokers, trades, sell lots, and cash transactions spanning ~3 years.

```bash
.venv/bin/python seed.py
```

> ⚠️ **This deletes existing users, brokers, trades, sell lots, and cash transactions** before repopulating. It preserves and re-seeds `trade_types` and `app_settings`. Do not run it against a database you care about.

---

## Building a distributable app

Building produces a self-contained installer/AppImage with the backend bundled inside — end users do **not** need Python or Node installed.

### One-shot (recommended)

```bash
./build-all.sh            # auto-detects your OS
./build-all.sh --linux    # or target explicitly
./build-all.sh --mac
./build-all.sh --win
```

This runs two stages:

1. **PyInstaller** (`build.py`) bundles the backend into a single executable at `dist/tradenexus` (or `tradenexus.exe` on Windows) and smoke-tests it.
2. **electron-builder** (`npm run build -- <target>`) packages Electron + frontend + the backend binary into `electron-dist/`.

Output (per platform):

| Platform | Artifact |
|----------|----------|
| Linux    | `electron-dist/*.AppImage` |
| Windows  | `electron-dist/*.exe` (NSIS installer) |
| macOS    | `electron-dist/*.dmg` (x64 + arm64) |

### Manual / partial builds

```bash
.venv/bin/python build.py            # build + smoke-test the backend binary
.venv/bin/python build.py --build    # build only
.venv/bin/python build.py --test     # test an already-built binary
npm run build:linux                  # electron-builder for one platform
```

> **Note:** the packaged app expects an initialized database at `~/TradeTracker/trades.db`. Run `init_db.py` (or ship an initialized DB) before first launch.

---

## Data, backups & configuration

- **Database:** `~/TradeTracker/trades.db` (SQLite). The parent folder is created automatically.
- **Backups:** on every startup the backend copies the DB to `~/TradeTracker/backups/trades_YYYY-MM-DD_HHMMSS.db`, keeping only the **7 most recent**. You can also download/restore a backup from **Settings → Data**.
- **Settings** are stored in the `app_settings` table and edited in **Settings → General** (display name, currency, date format, decimal separator, price-refresh interval, fiscal-year start). They auto-save on change.
- **Price cache:** Yahoo Finance quotes are cached in the `price_cache` table. Clear it from **Settings → Data** if prices look stale.
- **Port:** the backend always uses **8765**. Make sure it's free (see Troubleshooting).
- `.env` is intentionally empty — no connection string is needed.

---

## Keyboard shortcuts

Press `?` in the app to view the cheat sheet. Shortcuts are ignored while typing in a field.

| Key   | Action |
|-------|--------|
| `/`   | Focus the global search bar |
| `N`   | Open the Add Trade tab and focus the ticker field |
| `S`   | Switch to the Positions tab |
| `?`   | Toggle the shortcuts cheat sheet |
| `Esc` | Clear/blur search, or close the cheat sheet |

---

## API reference

All routes are served from `http://localhost:8765`. Selected endpoints:

**Health**
- `GET /health`

**Users**
- `GET /users` · `POST /users` · `DELETE /users/{user_id}`

**Trades**
- `GET /users/{user_id}/trades` (filters: `ticker`, `trade_type`, `action`)
- `POST /users/{user_id}/trades` · `PUT /trades/{trade_id}` · `DELETE /trades/{trade_id}`
- `POST /trades/{buy_trade_id}/sell`
- `GET /users/{user_id}/trades/export` (CSV)

**Positions & prices**
- `GET /users/{user_id}/positions` · `GET /users/{user_id}/positions/prices`
- `GET /prices/{ticker}` (`?cache_only=true` for a no-fetch cache read) · `POST /prices/refresh`

**Cash**
- `GET /users/{user_id}/cash` · `POST /users/{user_id}/cash/deposit` · `POST /users/{user_id}/cash/withdraw`

**Analytics**
- `GET /users/{user_id}/stats` (`?fiscal_year_start_month=`) · `GET /users/{user_id}/stats/growth`

**Search**
- `GET /search?user_id=&q=` — grouped trades / positions / cash transactions (min 2 chars)

**Brokers**
- `GET /brokers` · `POST /brokers` · `PUT /brokers/{broker_id}` · `DELETE /brokers/{broker_id}`

**Trade types**
- `GET /trade-types` · `POST /trade-types` · `PUT /trade-types/{id}` · `DELETE /trade-types/{id}`

**Settings & data**
- `GET /settings` · `PUT /settings`
- `GET /settings/backup` · `POST /settings/restore`
- `GET /settings/price-cache` · `DELETE /settings/price-cache`

Interactive API docs are available at `http://localhost:8765/docs` while the backend is running.

---

## Troubleshooting

**“Server did not respond within 30 s” / startup error dialog**
The backend binary failed to start. Confirm `dist/tradenexus` exists (run `build.py --build`) and that port 8765 is free.

**Port 8765 already in use**
Another process (or a previous run) is holding the port. Stop it:
```bash
# Linux/macOS
lsof -i :8765        # find the PID
kill <PID>
```

**`RuntimeError: Form data requires "python-multipart"`**
The backup/restore upload needs `python-multipart`. Reinstall dependencies (`pip install -r backend/requirements.txt`) and rebuild the binary so PyInstaller bundles it.

**Empty app / “no such table” errors**
The database schema hasn't been created. Run `.venv/bin/python backend/init_db.py`.

**Prices show “—” / look stale**
Live quotes require internet access. Use **Positions → Refresh prices**, or clear the cache from **Settings → Data**. Cached values are used when offline.

**Reset everything**
Delete `~/TradeTracker/trades.db` (and `~/TradeTracker/backups/`) and re-run `init_db.py`. A backup is taken automatically on each startup before any changes.

---

## License

Proprietary / unspecified. Add a license here if you intend to distribute.
```
