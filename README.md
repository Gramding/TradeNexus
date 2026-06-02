# TradeNexus

A desktop application for tracking trades, positions, realized / unrealized P&L, cash flow, and portfolio analytics across **stocks, ETFs, options, bonds, crypto, forex, and futures** — long *and* short, in any currency. TradeNexus runs entirely on your machine: a local FastAPI backend with a SQLite database, a vanilla-JS frontend, and an Electron shell that bundles them into a single installable app.

> All data lives in a local SQLite file (`~/TradeTracker/trades.db`). There is no cloud account, no telemetry, and no external database. The only network calls are to Yahoo Finance — for price quotes, instrument search, and FX rates.

---

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation (development)](#installation-development)
- [Running in development](#running-in-development)
- [Seeding mock data](#seeding-mock-data)
- [Running tests](#running-tests)
- [Building a distributable app](#building-a-distributable-app)
- [Data, backups & configuration](#data-backups--configuration)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [API reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Trade tracking** — record buy / sell-short trades with ticker, type, quantity, price, broker, commission, and notes. Sortable, filterable, duplicable, and CSV-exportable.
- **Positions** — open / partial lots grouped by `(ticker, type, direction, strike, expiration)` so two calls at different strikes are distinct rows; shows average cost, cost basis, live current price, and unrealized P&L (sortable, both native and base currency).
- **Long & short** — open longs with **Buy (long)** and shorts with **Sell short**. Close a long via the Sell modal; close a short via the Cover modal. Realized P&L is direction-aware so a falling price on a short is a profit.
- **Options** — Call / Put with a contract **multiplier** (default 100), **strike**, **expiration**, and **underlying**. Total value, cost basis, cash flow, and P&L all carry the multiplier, so a $2.50 1-contract call is $250 of exposure, not $2.50.
- **Bonds** — face value (default $1000), coupon rate, coupon frequency, maturity, and accrued interest at purchase. Price quoted as % of par; multiplier derives from `face_value / 100`. Accrued interest bumps the cash debit but stays out of cost basis so realized P&L is principal-only. Coupons are recorded as Interest events.
- **Multi-currency** — every trade stores its native `trade_currency` and an `fx_rate` to the configured **base currency** (auto-fetched from Yahoo, overridable). The cash pool, realized P&L, and all stats aggregates are stored / summed in base currency; positions expose both native and base cost basis and unrealized P&L, so each leg captures both the price move *and* the FX move.
- **Cash pool** — per-user balance tracking with deposits, withdrawals, and automatic buy/sell cash movements. The Add Trade form warns when a buy exceeds your cash balance.
- **Events** — record **dividends** (per-share × shares held on the event date), **splits** (retroactively scale every open lot — `q × p × multiplier` stays invariant), **interest** (cash credit), and **fees** (cash debit). Each event can be deleted; splits with later trades are blocked from deletion to keep cost basis honest.
- **Sell flow** — partial or full sells against specific buy lots, with commission-adjusted realized P&L recorded to a sell-lot ledger. Cover flow mirrors this for shorts.
- **Analytics** — total / buy / sell volume, net position, commissions, **realized P&L**, **dividend income**, **interest income**, **fees paid**; monthly-volume and trade-type breakdown charts; cumulative growth chart with selectable ranges (3M / 6M / 1Y / **This fiscal year** / All); configurable fiscal-year window.
- **Brokers** — per-broker commission models (flat + per-unit), colors, and a configurable default broker.
- **Trade types** — nine built-ins (Stock, ETF, Crypto, Forex, Futures, Call, Put, Bond, Other) plus user-defined custom types, with rename-cascades-to-trades and safe deletion.
- **Global search** — a command-palette search bar (focus with `/`) across trades, positions (including shorts), and cash transactions, with click-to-navigate and row highlighting.
- **Settings** — display name, currency, **base currency**, date format, decimal separator, price-refresh interval, fiscal-year start; broker management; trade-type management; database backup / restore; and price-cache clearing.
- **Convenience** — passive price autofill from cache on ticker blur, time-of-day greeting, light / dark theme, UI scaling, keyboard shortcuts, and a startup database backup (keeps the 7 most recent).
- **Security** — CSP on the renderer, CORS restricted to `localhost`, vendored frontend libraries (no third-party CDN at runtime), and a global error handler that surfaces silent fetch failures as toasts.

---

## Architecture

```
┌──────────────────────── Electron desktop shell ────────────────────────┐
│                                                                          │
│   electron/main.js                                                       │
│     • spawns the backend binary, polls /health, then opens the window    │
│     • loads frontend/index.html into a BrowserWindow (CSP-enforced)      │
│                                                                          │
│   ┌─────────────────────┐         HTTP (localhost:8765)                  │
│   │  Frontend (vanilla)  │  ───────────────────────────►  ┌───────────┐  │
│   │  index.html          │                                │  FastAPI   │  │
│   │  static/js/app.js     │  ◄───────────────────────────  │  backend   │  │
│   │  static/js/formatting │            JSON                 │  (uvicorn) │  │
│   │  static/js/vendor/    │                                └─────┬─────┘  │
│   │    chart.umd.js       │                                      │        │
│   └─────────────────────┘                                  SQLite │        │
│                                                   ~/TradeTracker/ │        │
│                                                        trades.db ◄┘        │
└──────────────────────────────────────────────────────────────────────────┘
                                                          │
                                          Yahoo Finance (prices, search, FX)
```

| Layer    | Technology |
|----------|------------|
| Backend  | Python · FastAPI · Uvicorn · SQLite (stdlib `sqlite3`) · yfinance |
| Frontend | Plain HTML/CSS/JavaScript (no framework) · Chart.js (vendored locally) |
| Desktop  | Electron · electron-builder · PyInstaller (backend → single binary) |

The backend listens on **`http://localhost:8765`** and exposes a health check at `/health`. CORS is restricted to `null` (Electron's `file://` origin) and `http://localhost:8765`. The frontend's API base URL is hardcoded to that address in `frontend/static/js/app.js`.

### Data model

| Table | Purpose |
|-------|---------|
| `users` | Per-user identity (tracker is single-machine, multi-profile). |
| `instruments` | Yahoo symbol + ticker + name + asset class + currency for known securities. |
| `trades` | One row per trade. Carries `direction`, `multiplier`, option fields (`strike_price`, `expiration_date`, `underlying`), currency fields (`trade_currency`, `fx_rate`), and bond fields (`face_value`, `coupon_rate`, `coupon_frequency`, `maturity_date`, `accrued_interest`). |
| `sell_lots` | Shared realized-P&L ledger for sells (close a long) and covers (close a short). `realized_pnl` is stored in **base currency**. |
| `cash_pool` | One row per cash movement (`deposit`, `withdrawal`, `buy_deduction`, `sell_proceeds`, `dividend`, `interest`, `fee`). All amounts in **base currency**. |
| `events` | Dividends, splits, interest, fees — separate from trades since they don't open or close positions. |
| `price_cache` | Yahoo price quotes keyed by symbol + source. |
| `fx_rates` | FX-rate cache keyed by `(from_currency, to_currency, source)`. |
| `brokers`, `trade_types`, `app_settings` | Configuration. |

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

### 2. Initialize the database (optional)

The backend **auto-creates the database on first launch** — on startup it creates `~/TradeTracker/trades.db`, applies migrations, and seeds default settings and trade types. A fresh install therefore starts as an empty-but-working database with **no users**.

You only need the initializer if you want a convenience **demo user** in development (it is safe to re-run; it never drops existing tables):

```bash
.venv/bin/python backend/init_db.py     # creates schema + a demo user
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

This serves the API on `http://localhost:8765`. Then open the frontend in a browser. The backend's CORS is restricted to `null` (Electron's `file://` origin) and `http://localhost:8765`, so the simplest dev workflow is to serve the frontend from the same port the API runs on, or to open `frontend/index.html` directly:

```bash
# Option 1: open the HTML file directly (works with the 'null' origin).
xdg-open frontend/index.html        # Linux
open      frontend/index.html        # macOS

# Option 2: serve from a different port — in that case, temporarily add
# "http://localhost:5173" to allow_origins in backend/main.py, or use Option 1.
cd frontend
python3 -m http.server 5173
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

## Running tests

The backend has a pytest suite that runs against a **throwaway SQLite database** in a temp directory — your real `~/TradeTracker/trades.db` is never touched, and the tests make no network calls.

```bash
.venv/bin/pip install -r backend/requirements-dev.txt   # pytest + httpx (one-time)
.venv/bin/python -m pytest                               # run the suite
```

Coverage includes users, trades (creation / validation / filtering / update / delete), the sell flow (partial / full / oversell + cash effects), the **cover flow** for shorts, cash deposits / withdrawals, brokers & commissions, trade types (validation, rename-cascade, delete rules), settings validation, global search (incl. shorts), stats / fiscal-year windowing, the price + FX caches, the **options multiplier** end-to-end, **multi-currency** trades (foreign cash, FX-aware realized P&L, base-currency stats), **events** (dividends with date eligibility, splits with cost-basis invariant, interest / fees, delete reversals, stats fields), **bonds** (face value, accrued interest, principal-only realized P&L), and the schema migration from a pre-Phase-1 database. Tests live in `backend/tests/`.

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

> **Note:** the packaged app creates its database automatically on first launch — no manual initialization or shipped database is required. It starts empty (no users).

### Releasing all three platforms at once (CI)

`build-all.sh` only builds for the OS you run it on — **a single machine cannot produce working builds for all three platforms**, because the backend is a PyInstaller binary (host-native, not cross-compilable) and macOS builds require macOS.

To build Linux + macOS + Windows together for a release, use the GitHub Actions workflow at [`.github/workflows/release.yml`](.github/workflows/release.yml). It builds each platform on its own native runner:

- **Tagged release:** push a version tag and CI builds all three and attaches them to a GitHub Release.
  ```bash
  # bump "version" in package.json first, then:
  git tag v1.0.0
  git push origin v1.0.0
  ```
- **Ad-hoc:** trigger it manually from the repo's **Actions → Build release → Run workflow**, then download the installers from the run's **Artifacts**.

The installers are **unsigned** (no code-signing identity configured), so on first launch Windows SmartScreen and macOS Gatekeeper will warn the user. Proper signing/notarization removes those warnings but requires paid certificates.

---

## Data, backups & configuration

- **Database location:** `~/TradeTracker/trades.db` (SQLite) — in the user's **home directory**, not inside the app bundle. `Path.home()` resolves per-OS: `/home/<user>` on Linux (including the AppImage), `/Users/<user>` on macOS, `C:\Users\<user>` on Windows. It is created automatically on first launch and **persists across app updates** (replacing the AppImage/installer never touches it). The path is fixed and not currently configurable.
- **Backups:** on every startup the backend copies the DB to `~/TradeTracker/backups/trades_YYYY-MM-DD_HHMMSS.db`, keeping only the **7 most recent**. You can also download/restore a backup from **Settings → Data**.
- **Settings** are stored in the `app_settings` table and edited in **Settings → General** (display name, currency, base currency, date format, decimal separator, price-refresh interval, fiscal-year start). `currency` and `base_currency` are kept in sync so the app has one reporting currency. Settings auto-save on change.
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
- `POST /trades/{buy_trade_id}/sell` — close a long lot
- `POST /trades/{short_trade_id}/cover` — buy-to-close a short lot
- `GET /users/{user_id}/trades/export` (CSV)

**Positions & prices**
- `GET /users/{user_id}/positions` · `GET /users/{user_id}/positions/prices`
- `GET /prices/{symbol}` (`?cache_only=true` for a no-fetch cache read) · `POST /prices/refresh`
- `GET /fx/{from}/{to}` (`?cache_only=true`) — FX rate, used for multi-currency conversion

**Cash**
- `GET /users/{user_id}/cash` · `POST /users/{user_id}/cash/deposit` · `POST /users/{user_id}/cash/withdraw`

**Events (dividends, splits, interest, fees)**
- `GET /users/{user_id}/events` (`?event_type=`) · `POST /users/{user_id}/events` · `DELETE /events/{event_id}`

**Analytics**
- `GET /users/{user_id}/stats` (`?fiscal_year_start_month=`) · `GET /users/{user_id}/stats/growth`

**Search**
- `GET /search?user_id=&q=` — grouped trades / positions (longs and shorts) / cash transactions (min 2 chars)

**Brokers**
- `GET /brokers` · `POST /brokers` · `PUT /brokers/{broker_id}` · `DELETE /brokers/{broker_id}`

**Instruments**
- `GET /instruments` · `GET /instruments/search?q=` · `POST /instruments` · `PUT /instruments/{id}` · `DELETE /instruments/{id}`

**Trade types**
- `GET /trade-types` · `POST /trade-types` · `PUT /trade-types/{id}` · `DELETE /trade-types/{id}`

**Settings & data**
- `GET /settings` · `PUT /settings` (the `currency` and `base_currency` settings are kept in sync as the single reporting currency)
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

**“no such table” errors**
The schema normally auto-creates on startup. If you see this, initialization failed (check the server logs) — you can recreate it manually with `.venv/bin/python backend/init_db.py`.

**Prices show “—” / look stale**
Live quotes require internet access. Use **Positions → Refresh prices**, or clear the cache from **Settings → Data**. Cached values are used when offline.

**Reset everything**
Delete `~/TradeTracker/trades.db` (and `~/TradeTracker/backups/`). The app recreates an empty database on the next launch. A backup is taken automatically on each startup before any changes.

---

## License

Proprietary / unspecified. Add a license here if you intend to distribute.
```
