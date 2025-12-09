Steam Curator Scraper — README

Quick summary
- `bbest.py` — main asyncio Playwright scraper. Supports incremental updates via `--input-csv`, multiple game sources (`--games-file`, `--appid`, or edit `RAW_GAME_IDS`), headless mode, retries, pooled pages, and new CLI flags `--output-file` and `--export-new-only`.
- `app.py` — Streamlit frontend that runs `bbest.py` as a subprocess, streams logs (bounded buffer), and offers the result CSV for download. Supports passing `--output-file` and `--export-new-only` options.
- `Dockerfile` — scaffold to run the Streamlit app with Playwright Chromium installed.

Project layout (after reorganization)

- `python_src/` - all Python source files organized as a package
  - `python_src/steam/` - Steam-related scripts and the Streamlit app (`app.py`, `bbest.py`, filler scripts, etc.)
  - `python_src/yt/` - YouTube discovery & extraction scripts
  - `python_src/shared/` - shared helpers (e.g. `csv_helpers.py`, `paths.py`)

- `non_py/` - non-Python assets (Dockerfile, packaging spec, build scripts, archived requirements)
- `archived_requirements/` - backups of previous full/pinned requirement lists
- `archived_unused/` - older scripts and miscellaneous files we aren't actively using

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

How to run (recommended)

1) Create and activate a virtualenv (zsh/macOS):

   python -m venv .venv
   source .venv/bin/activate

2) Install the curated project dependencies and Playwright browsers:

   pip install -r requirements.txt
   python -m playwright install chromium

3) Launch the Streamlit UI (recommended):

   From the repository root you can now run the convenient launcher:

     python run_app.py

   This calls the packaged launcher (`python_src.steam.run_app`) and opens the Streamlit UI in your browser.

   Alternatively you can run Streamlit directly against the moved app module:

     streamlit run python_src/steam/app.py

Docker (build image locally)
- Build:
    docker build -t steam-scraper .
- Run:
    docker run -p 8501:8501 steam-scraper

macOS native bundle (experimental)
- A small launcher `run_app.py` was added to help build a macOS native bundle using PyInstaller. It starts Streamlit and opens the browser.
- Packaging is non-trivial because Playwright browser binaries must be included.
- See `BUILD_DOCS.md` for step-by-step instructions to create a macOS binary with PyInstaller.

Running individual scripts (examples)

- Steam search scraper (collect game ids):

    python -m python_src.steam.steam_search_scrape --query "roguelike" --output steam_games.csv

- Run the curator scraper (`bbest.py`):

    python -m python_src.steam.bbest --games-file new_games.txt --concurrency 1 --output-file merged.csv

- Fill missing About fields (filler):

    python -m python_src.steam.fill_about_missing --input curators.csv --output curators_filled.csv --concurrency 1

- YouTube contact extraction (example):

    python -m python_src.yt.youtube_discover_and_extract --query "dice roguelike" --max-channels 20 --output youtube_contacts.csv

Notes / troubleshooting
- Playwright must be installed and the browser binaries present on the machine/container that runs the scraper.
- If Playwright import errors occur: ensure you installed the `playwright` package and ran `python -m playwright install chromium`.
- Use `--concurrency 1` for most reliable low-volume runs to reduce parallel profile visits.
- If Steam rate-limits you, consider adding proxies or increasing NAV_RETRY_SLEEP; do not scrape aggressively.

About the requirements files you found

There were several exported/old requirements files in the repository history. To keep the repo tidy and portable we now use a single curated `requirements.txt` at the repository root (the pip-friendly file you should install from).

The other full/pinned lists were moved to `archived_requirements/` for reproducibility and historical reference. Files in `archived_requirements/` include:

- `requirements_full_backup.txt` — the original large exported list (conda/pip-export style)
- `old-requirements.txt`, `reqs.txt`, `rq.txt` — older pinned lists or ad-hoc requirement snapshots

Root files such as `old-requirements.txt`, `reqs.txt`, and `rq.txt` were replaced with small pointer headers that reference the archived copies. The single active requirements file to install from is `requirements.txt` (root).

If you need to reproduce an exact historical environment, use the corresponding file from `archived_requirements/`.

Next recommended improvements (optional)
- Refactor `bbest.py` into an importable API so `app.py` can call it directly (avoids subprocess and simplifies log streaming).
- Build and publish a Docker image containing Playwright browsers for non-technical users.
- Add test(s) for dedupe key behavior (steam_profile vs curator_name).

Notes & next steps

- If you prefer to run scripts directly (e.g., `python bbest.py`) I can add small wrapper scripts at the repository root that call the appropriate `python -m ...` module, or adjust shebangs + PYTHONPATH behaviour.
- I can also update the top-level README.md (root) to mirror this file if you want the documentation at the repository root rather than in `non_py/`.
