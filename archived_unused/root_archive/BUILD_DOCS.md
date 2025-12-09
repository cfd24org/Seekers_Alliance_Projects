Mac native packaging guide (PyInstaller)

This document explains how to create a macOS native bundle (.app / single executable) for the project using PyInstaller.

Prerequisites (on macOS, zsh):
1) Python 3.11 (or same as project)
2) Xcode command line tools: xcode-select --install
3) pyenv or system Python

Recommended local dev steps

1. Create and activate a virtualenv
   python -m venv .venv
   source .venv/bin/activate

2. Install dependencies including Playwright and PyInstaller
   pip install -r requirements.txt pyinstaller
   python -m playwright install chromium

3. Locate Playwright browser cache (important)
   # default path on macOS
   ls ~/Library/Caches/ms-playwright

   We will bundle this `ms-playwright` folder with the executable so Playwright can find the browser binaries offline.

4. Build with PyInstaller (example commands)

   # One-file executable (may need extra hidden-imports later)
   pyinstaller --name SteamCuratorLauncher --onefile \
     --add-data "$HOME/Library/Caches/ms-playwright:ms-playwright" \
     --hidden-import=playwright._impl._api run_app.py

   # Alternatively create a macOS app bundle (onedir) then wrap into .app
   pyinstaller --name SteamCuratorLauncher --onedir \
     --add-data "$HOME/Library/Caches/ms-playwright:ms-playwright" \
     --hidden-import=playwright._impl._api run_app.py

5. Test the produced binary
   - If --onefile: ./dist/SteamCuratorLauncher
   - If --onedir: ./dist/SteamCuratorLauncher/SteamCuratorLauncher

   The first run may extract the binary; logs from Streamlit will appear and the browser will open.

6. Troubleshooting
   - If Playwright fails to import or browsers are missing, add additional --hidden-import flags reported in the error and ensure ms-playwright folder was bundled.
   - Dynamic import errors: inspect the PyInstaller build warnings and add missing modules.
   - Codesign & notarize: to distribute widely, sign the app with Apple Developer certificate and notarize via altool or notarytool.

Notes
- Bundling Playwright browsers will add hundreds of MB to your artifact.
- You must build on macOS for macOS app.
- Building for Windows or Linux requires their respective OS (CI runners recommended).

If you want, I can add a PyInstaller spec file and a basic GitHub Actions workflow to build the macOS artifact on push/tags (requires a macOS runner and secrets for code signing if you want signing step).

Appendix: example PyInstaller spec (optional)
If you want finer control over the bundle, create a `steam.spec` file and run `pyinstaller steam.spec`.

example steam.spec (adjust paths as needed):

# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis([
    'run_app.py'
],
    pathex=['.'],
    binaries=[],
    datas=[
        (os.path.expanduser('~/Library/Caches/ms-playwright'), 'ms-playwright')
    ],
    hiddenimports=['playwright._impl._api'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SteamCuratorLauncher')
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='SteamCuratorLauncher')


Appendix: example GitHub Actions (macOS runner)
Create `.github/workflows/build-macos.yml` to build artifacts on macOS. This example does not include code signing.

name: Build macOS

on:
  push:
    tags:
      - 'v*'

jobs:
  build-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install deps
        run: |
          python -m venv .venv
          source .venv/bin/activate
          pip install -r requirements.txt pyinstaller
      - name: Install Playwright browsers
        run: |
          source .venv/bin/activate
          python -m playwright install chromium
      - name: Build with PyInstaller
        run: |
          source .venv/bin/activate
          pyinstaller --name SteamCuratorLauncher --onefile --add-data "$HOME/Library/Caches/ms-playwright:ms-playwright" --hidden-import=playwright._impl._api run_app.py
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: macos-artifact
          path: dist/
