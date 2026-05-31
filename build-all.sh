#!/usr/bin/env bash
#
# Build TradeNexus end-to-end:
#   1. PyInstaller  → dist/tradenexus (or tradenexus.exe on Windows)
#   2. electron-builder → platform-specific installer in electron-dist/
#
# Usage:
#   ./build-all.sh              # auto-detect platform
#   ./build-all.sh --linux
#   ./build-all.sh --mac
#   ./build-all.sh --win
#
# This builds ONLY for the OS it runs on. A single machine cannot build all three
# platforms (the backend is a host-native PyInstaller binary; macOS needs macOS).
# To build Linux + macOS + Windows together for a release, push a "v*" tag and let
# CI do it: .github/workflows/release.yml  (each OS builds on its own runner).
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── Platform detection ────────────────────────────────────────────────────────
TARGET_FLAG="${1:-}"

if [[ -z "$TARGET_FLAG" ]]; then
  case "$(uname -s)" in
    Linux)           TARGET_FLAG="--linux" ;;
    Darwin)          TARGET_FLAG="--mac"   ;;
    MINGW*|CYGWIN*|MSYS*) TARGET_FLAG="--win" ;;
    *)
      echo "Unsupported platform: $(uname -s)"
      echo "Pass --linux, --mac, or --win explicitly."
      exit 1
      ;;
  esac
fi

# ── Step 1: PyInstaller ───────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════╗"
echo "║  Step 1 — PyInstaller                        ║"
echo "╚══════════════════════════════════════════════╝"

PYTHON=".venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Error: virtualenv not found at .venv/"
  echo "Create it with: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"
  exit 1
fi

"$PYTHON" build.py --build

echo ""

# ── Step 2: electron-builder ──────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════╗"
echo "║  Step 2 — electron-builder ($TARGET_FLAG)    ║"
echo "╚══════════════════════════════════════════════╝"

if [[ ! -d node_modules ]]; then
  echo "node_modules not found — running npm install first"
  npm install
fi

npm run build -- "$TARGET_FLAG"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Done — output in electron-dist/             ║"
echo "╚══════════════════════════════════════════════╝"
ls -lh electron-dist/ 2>/dev/null || true
