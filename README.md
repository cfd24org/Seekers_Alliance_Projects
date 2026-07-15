# Steam Curator Scraper & GUI Dashboard

This repository contains a set of Python scraping tools and a Streamlit web interface designed to collect, scrape, and manage information about Steam curators (curator name, Steam profile link, followers, reviews, external site, about me text, emails, etc.).

It is designed to be run **locally** on your computer.

> **Taking over this project?** See [HANDOFF.md](HANDOFF.md). Note: the YouTube-related files in this repo are legacy prototypes — the maintained YouTube scraper lives in the separate [`yt_descriptions_app`](https://github.com/cfd24/yt_descriptions_app) repo.

---

## 🚀 Features

1. **Steam Curator Scraper (`bbest.py`)**:
   - Scrapes curators that have reviewed specific Steam games (using Steam App IDs).
   - Supports incremental updates by importing a previously generated CSV to avoid duplicate pages.
   - Captures follower counts, review text/recommendation type, external site link, "about me" description, and emails.
   
2. **Steam Search Scraper (`steam_search_scrape.py`)**:
   - Searches the Steam Store for specific queries (e.g. "roguelike", "indie") and exports game names and App IDs.

3. **Steam Charts Scraper**:
   - Scrapes the most played games charts on Steam to collect game names and App IDs.

4. **Standalone Email Extractor & Profile Filler**:
   - Feeds a CSV back into the scraper to visit profiles with missing about text/emails or quickly parse raw texts using regex.

5. **Streamlit GUI Dashboard (`run_app.py`)**:
   - An easy-to-use local web interface to run all the scrapers, view progress logs, and download generated CSVs directly.

---

## ⚡ Quick Start (one click)

The easiest way to run the app — no terminal commands needed:

1. Make sure Python 3 is installed ([python.org/downloads](https://www.python.org/downloads/); on Windows tick "Add Python to PATH").
2. Download/clone this repository.
3. Double-click the launcher for your system:
   - **macOS**: `start_mac.command` (first time: right-click → Open, since it's from the internet)
   - **Windows**: `start_windows.bat`

The first run installs everything automatically (a few minutes); after that it starts in seconds and opens the app in your browser. Keep the launcher window open while using the app.

Prefer to set things up manually? Follow the steps below.

---

## 🛠️ Manual Installation & Setup

Ensure you have Python 3.8+ installed on your computer.

1. **Clone or Download the Repository**:
   Extract this folder to your local machine.

2. **Set up a Virtual Environment (Recommended)**:
   Open your terminal (macOS/Linux) or Command Prompt (Windows) inside this folder and run:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # macOS/Linux
   # or: .venv\Scripts\activate  # Windows
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright Browsers**:
   This scraper uses Playwright to automate page visits. Run this command to install the required browser binaries:
   ```bash
   playwright install chromium
   ```

---

## 🖥️ How to Run the App (GUI Dashboard)

To launch the Streamlit graphical interface:

```bash
python run_app.py
```

This will spin up a local server and automatically open a tab in your web browser (usually at `http://localhost:8501`).

### In the UI, you can:
- Upload an existing CSV of curators (optional) to run incremental updates.
- Paste Steam App IDs (one per line, e.g., `1948280` for a game) or upload a `.txt` file of App IDs.
- Run the scraper and watch logs stream live.
- Download the final CSV once complete.
- Use standalone tabs to run search queries or crawl Steam Charts.

---

## 💻 Running via Command Line (CLI)

If you prefer to run the scripts directly from the terminal:

### 1. Scrape Curators for specific App IDs
Create a text file named `games.txt` with one Steam App ID per line, then run:
```bash
python -m python_src.steam.bbest --games-file games.txt --output-file output.csv --concurrency 1
```

### 2. Search Steam for Game App IDs
```bash
python -m python_src.steam.steam_search_scrape --query "roguelike" --output steam_games.csv --pages 2
```

### 3. Fill Missing Info on an Existing CSV
```bash
python -m python_src.steam.fill_about_missing --input output.csv --output output_filled.csv --concurrency 1
```
