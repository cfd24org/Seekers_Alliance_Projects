#!/bin/bash
# One-click launcher for the Steam Curator Scraper (macOS/Linux).
# Double-click this file (macOS) or run ./start_mac.command from a terminal.
# First run sets everything up (a few minutes); later runs start in seconds.
set -e
cd "$(dirname "$0")"

echo "=============================================="
echo "  Steam Curator Scraper - Launcher"
echo "=============================================="

# 1. Find Python 3
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo ""
    echo "ERROR: Python 3 is not installed."
    echo "Install it from https://www.python.org/downloads/ then run this again."
    read -p "Press Enter to close..."
    exit 1
fi

# 2. Create virtual environment on first run
if [ ! -f ".venv/bin/python" ]; then
    echo "[1/3] First run: creating Python virtual environment..."
    "$PY" -m venv .venv
fi
PYV=".venv/bin/python"

# 3. Install/update dependencies (fast no-op after first run)
echo "[2/3] Checking dependencies..."
"$PYV" -m pip install --quiet --upgrade pip
"$PYV" -m pip install --quiet -r requirements.txt
"$PYV" -m playwright install chromium

# 4. Launch the app (opens in your browser)
echo "[3/3] Starting the app - your browser will open shortly."
echo "      Keep this window open while using the app. Press Ctrl+C to stop."
"$PYV" run_app.py
