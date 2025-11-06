Steam Curator Scraper — README

Quick summary
- `bbest.py` — main asyncio Playwright scraper. Supports incremental updates via `--input-csv`, multiple game sources (`--games-file`, `--appid`, or edit `RAW_GAME_IDS`), headless mode, retries, pooled pages, and new CLI flags `--output-file` and `--export-new-only`.
- `app.py` — Streamlit frontend that runs `bbest.py` as a subprocess, streams logs (bounded buffer), and offers the result CSV for download. Supports passing `--output-file` and `--export-new-only` options.
- `Dockerfile` — scaffold to run the Streamlit app with Playwright Chromium installed.

Quick local run
1) Create venv and install dependencies (macOS / zsh):
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m playwright install chromium

2) Run Streamlit UI locally:
   streamlit run app.py

3) Or run the scraper directly (example):
   python bbest.py --games-file new_games.txt --input-csv curators_prev.csv --concurrency 1 --scroll-until-end --output-file merged.csv

Docker (build image locally)
- Build:
    docker build -t steam-scraper .
- Run:
    docker run -p 8501:8501 steam-scraper

macOS native bundle (experimental)
- A small launcher `run_app.py` was added to help build a macOS native bundle using PyInstaller. It starts Streamlit and opens the browser.
- Packaging is non-trivial because Playwright browser binaries must be included.
- See `BUILD_DOCS.md` for step-by-step instructions to create a macOS binary with PyInstaller.

Notes / troubleshooting
- Playwright must be installed and the browser binaries present on the machine/container that runs the scraper.
- If Playwright import errors occur: ensure you installed the `playwright` package and ran `python -m playwright install chromium`.
- Use `--concurrency 1` for most reliable low-volume runs to reduce parallel profile visits.
- If Steam rate-limits you, consider adding proxies or increasing NAV_RETRY_SLEEP; do not scrape aggressively.

Next recommended improvements (optional)
- Refactor `bbest.py` into an importable API so `app.py` can call it directly (avoids subprocess and simplifies log streaming).
- Build and publish a Docker image containing Playwright browsers for non-technical users.
- Add test(s) for dedupe key behavior (steam_profile vs curator_name).
