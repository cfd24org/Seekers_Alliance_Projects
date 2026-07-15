# Handoff Notes — Steam Curator Scraper

This document is for whoever is taking over this project. See [README.md](README.md) for full setup and usage instructions.

## What this is

A **locally-run** Steam curator scraper (Playwright browser automation) with a Streamlit GUI. It scrapes curator pages for follower counts, review info, and contact emails, and outputs CSV files. There is no cloud component, no database, and **no secrets/credentials required** — clone it, install dependencies per the README, and run.

## Getting started (new owner)

1. Clone this repo.
2. Follow the "Local Installation & Setup" section in the README (Python venv, `pip install -r requirements.txt`, `playwright install chromium`).
3. Launch the GUI with `python run_app.py` — everything can be driven from there, including downloading result CSVs.

Results are plain CSV files saved to `outputs/` (gitignored) or downloaded via the GUI. There is no shared/live spreadsheet for this project — each run produces its own CSV, and you can feed a previous CSV back in for incremental updates.

## ⚠️ Legacy YouTube files in this repo

This repo predates the dedicated YouTube project and still contains **early prototypes** of the YouTube tooling:

- `yt_descriptions_ui.py` (root)
- `youtube_api_discovery/discover_channels_api.py`
- `channels_to_description.py`
- `python_src/yt/` and `run_yt.py`

**Do not use these for YouTube work.** The maintained, far more evolved YouTube scraper (Google Sheets database, daily GitHub Actions cron, Discord notifications) lives in its own repo: [`yt_descriptions_app`](https://github.com/cfd24/yt_descriptions_app). The files here are kept only for history.

The Steam scraper code (`python_src/steam/`, `run_app.py`) is the active, canonical part of this repo.
