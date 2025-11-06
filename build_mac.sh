#!/usr/bin/env zsh
# filepath: /Users/crisostomo/Desktop/steam/build_mac.sh
# Simple macOS build script to create a PyInstaller bundle for the project.
# Usage: ./build_mac.sh [--bundle-playwright]
# By default this script will NOT bundle Playwright's browser cache into the app
# because bundling browsers often triggers macOS codesign / nested bundle issues.
# Pass --bundle-playwright to include the Playwright cache (you must have the
# browsers installed locally; this will attempt to install them into the venv).
set -euo pipefail

VENV_DIR=".venv"
PYINSTALLER_NAME="SteamCuratorLauncher"
PLAYWRIGHT_CACHE="$HOME/Library/Caches/ms-playwright"

# Opt-in: include Playwright browsers in the bundle (default: disabled)
BUNDLE_PLAYWRIGHT=0
if [ "${1:-}" = "--bundle-playwright" ] || [ "${BUNDLE_PLAYWRIGHT:-}" = "1" ]; then
  BUNDLE_PLAYWRIGHT=1
fi

echo "==> Using python3 to create venv (will reuse if $VENV_DIR exists)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 not found in PATH. Install python3 (Homebrew: brew install python)" >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating venv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
else
  echo "==> Reusing existing venv: $VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo "==> Upgrading pip, setuptools, wheel"
pip install --upgrade pip setuptools wheel

echo "==> Installing minimal runtime dependencies into the venv"
# Keep this minimal to avoid failures caused by a large repo-wide requirements.txt
pip install pyinstaller streamlit playwright requests

if [ "$BUNDLE_PLAYWRIGHT" -eq 1 ]; then
  echo "==> Installing Playwright browsers into the venv (chromium)"
  # This will populate $PLAYWRIGHT_CACHE which we can bundle into the app.
  python -m playwright install chromium
fi

if [ ! -d "$PLAYWRIGHT_CACHE" ]; then
  echo "Warning: Playwright cache not found at $PLAYWRIGHT_CACHE"
  echo "If you plan to bundle browsers, run this script with --bundle-playwright or run 'python -m playwright install chromium' locally."
  # Not fatal — we may prefer runtime browser install to avoid nested-app codesign issues.
fi

# Build with PyInstaller. When possible avoid bundling Playwright's browser files
# as they frequently trigger nested app codesign issues on macOS. Use --bundle-playwright
# to add the cache as data. Add a few common hidden-imports for Playwright and
# dynamic imports. If PyInstaller warns about additional hidden imports, re-run
# adding them as needed (see build/SteamCuratorLauncher/warn-*.txt for hints).
PYINSTALLER_CMD=(pyinstaller --name "$PYINSTALLER_NAME" --onefile --noconfirm --clean \
  --hidden-import=playwright._impl._api \
  --hidden-import=playwright.sync_api \
  --hidden-import=playwright._impl._connection \
  --hidden-import=packaging.version \
  run_app.py)

if [ "$BUNDLE_PLAYWRIGHT" -eq 1 ]; then
  PYINSTALLER_CMD+=(--add-data "$PLAYWRIGHT_CACHE:ms-playwright")
fi

echo "==> Running: ${PYINSTALLER_CMD[*]}"
"${PYINSTALLER_CMD[@]}"

echo "==> Build finished. Output in dist/"
ls -lah dist || true

if [ "$BUNDLE_PLAYWRIGHT" -eq 1 ]; then
  echo "Note: You bundled Playwright browsers into the app. That can increase size significantly and may" \
       "cause macOS codesign/notarization steps to fail because Playwright stores nested app bundles." \
       "If you hit signing errors, consider NOT bundling the browsers and letting the app install browsers at first run."
fi

echo "If the binary fails due to missing hidden imports, re-run with added --hidden-import flags as suggested by PyInstaller warnings (see build/SteamCuratorLauncher/warn-*.txt)."

echo "Done."
