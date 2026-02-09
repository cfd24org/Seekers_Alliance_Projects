"""
Simple Streamlit frontend for your existing bbest.py scraper.
- Upload an existing CSV (optional) to run incremental updates
- Paste or upload a games file (one Steam appid per line)
- Toggle options and run the scraper

This app runs the existing `bbest.py` as a subprocess so your working script remains unchanged.
Run locally with:
    pip install streamlit
    streamlit run python_src/steam/run_steam.py

Notes:
- The container or machine running this must have Playwright and the browser binaries installed.
- The app will show live logs and provide a download link for the generated CSV when finished.
"""

import streamlit as st
import tempfile
import subprocess
import time
import os
from pathlib import Path
from collections import deque
import uuid

st.set_page_config(page_title="Steam Curator Scraper UI", layout="centered")

try:
    from python_src.shared import paths as shared_paths
except Exception:
    import sys, os
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from python_src.shared import paths as shared_paths

OUT_DIR = shared_paths.OUTPUT_DIR

# Global headless toggle
if 'headless' not in st.session_state:
    st.session_state.headless = True

col1, col2 = st.columns([1, 4])
with col1:
    if st.button("Toggle Headless Mode"):
        st.session_state.headless = not st.session_state.headless
with col2:
    st.write(f"Headless Mode: {'ON' if st.session_state.headless else 'OFF (visible browser)'}")

st.title("Steam Curator Scraper — GUI")

st.markdown("Upload an existing CSV (optional) to update, then supply one or more Steam app IDs (one per line) or upload a games file.")

# Left column: inputs
with st.form(key="scrape_form"):
    input_csv = st.file_uploader("Existing CSV to update (optional)", type=["csv"])
    games_text = st.text_area("App IDs (one per line)", height=120, placeholder="1948280\n3112170")
    games_file = st.file_uploader("Or upload a games file (one appid per line)", type=["txt", "csv"])    
    scroll_until_end = st.checkbox("Scroll until end (collect full listings)", value=False)
    concurrency = st.slider("Concurrency (profile page workers)", min_value=1, max_value=6, value=1)
    output_filename = st.text_input("Fixed output filename (optional, e.g. merged.csv)", value=os.path.join(OUT_DIR, "merged.csv"))
    export_new_only = st.checkbox("Export only newly discovered curators (requires input CSV)", value=False)
    run_btn = st.form_submit_button("Run scraper")

# Area to show logs
log_area = st.empty()
progress_text = st.empty()

# --- New standalone filler feature ---
st.markdown("---")
st.header("Fill missing About/Email — standalone")
with st.form(key="standalone_filler_form"):
    filler_upload = st.file_uploader("CSV to fill (optional)", type=["csv"], key="filler_upload")
    filler_existing_path = st.text_input("Or existing CSV path (repo-relative)", value="dice.csv")
    filler_concurrency = st.slider("Filler concurrency", min_value=1, max_value=6, value=1)
    filler_no_headless = st.checkbox("Show browser while filling (no-headless)", value=False)
    run_filler_now = st.form_submit_button("Run filler now")

if run_filler_now:
    tmpdir_f = Path(tempfile.mkdtemp(prefix="steam_filler_"))
    input_csv_path = None
    # prefer uploaded file
    if filler_upload is not None:
        input_csv_path = tmpdir_f / f"uploaded_input_{int(time.time())}.csv"
        with open(input_csv_path, "wb") as f:
            f.write(filler_upload.getbuffer())
    else:
        candidate_path = Path(filler_existing_path)
        if not candidate_path.is_absolute():
            candidate_path = Path.cwd() / candidate_path
        if candidate_path.exists():
            input_csv_path = candidate_path
        else:
            st.error(f"CSV not found: {candidate_path}")

    if input_csv_path:
        out_path = Path(str(input_csv_path).rsplit('.', 1)[0] + '_filled.csv')
        cmd_fill = ["python", "-m", "python_src.steam.fill_about_missing", "--input", str(input_csv_path), "--output", str(out_path), "--concurrency", str(max(1, filler_concurrency))]
        if filler_no_headless or not st.session_state.headless:
            cmd_fill.append("--no-headless")

        st.info("Running filler: " + " ".join(cmd_fill))
        filler_log = st.empty()
        filler_progress = st.empty()
        log_lines = []
        proc = subprocess.Popen(cmd_fill, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            while True:
                line = proc.stdout.readline()
                if line == '' and proc.poll() is not None:
                    break
                if line:
                    for sub in line.splitlines():
                        log_lines.append(sub)
                        if len(log_lines) > 2000:
                            log_lines = log_lines[-2000:]
                    filler_log.markdown("```text\n" + "\n".join(log_lines) + "\n```")
                    filler_progress.text(log_lines[-1] if log_lines else "")
            proc.wait()
        except Exception as e:
            st.error(f"Error while running filler: {e}")
        finally:
            if proc.poll() is None:
                proc.terminate()

        if out_path.exists():
            st.success(f"Filler finished — output: {out_path}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download filled CSV', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            st.warning('Filler did not produce an output file. Check logs above for details.')

# --- New: Extract emails directly from about_me text ---
st.markdown("---")
st.header("Extract emails from about_me — quick scan")
with st.form(key="email_extractor_form"):
    email_input_upload = st.file_uploader("CSV to scan for emails (optional)", type=["csv"], key="email_input_upload")
    email_existing_path = st.text_input("Or existing CSV path (repo-relative)", value="dice_filled.csv")
    email_output_name = st.text_input("Output filename (optional)", value="")
    run_email_extractor = st.form_submit_button("Run email extractor")

if run_email_extractor:
    tmpdir_e = Path(tempfile.mkdtemp(prefix="steam_email_"))
    input_csv_path = None
    if email_input_upload is not None:
        input_csv_path = tmpdir_e / f"uploaded_input_{int(time.time())}.csv"
        with open(input_csv_path, "wb") as f:
            f.write(email_input_upload.getbuffer())
    else:
        candidate_path = Path(email_existing_path)
        if not candidate_path.is_absolute():
            candidate_path = Path.cwd() / candidate_path
        if candidate_path.exists():
            input_csv_path = candidate_path
        else:
            st.error(f"CSV not found: {candidate_path}")

    if input_csv_path:
        if email_output_name and email_output_name.strip():
            out_path = Path.cwd() / email_output_name.strip()
        else:
            out_path = Path(str(input_csv_path).rsplit('.', 1)[0] + '_emails.csv')

        cmd = ["python", "-m", "python_src.steam.extract_emails_from_about", "--input", str(input_csv_path), "--output", str(out_path)]
        st.info("Running extractor: " + " ".join(cmd))

        log_box = st.empty()
        log_lines = []
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            while True:
                line = proc.stdout.readline()
                if line == '' and proc.poll() is not None:
                    break
                if line:
                    for sub in line.splitlines():
                        log_lines.append(sub)
                        if len(log_lines) > 2000:
                            log_lines = log_lines[-2000:]
                    log_box.markdown("```text\n" + "\n".join(log_lines) + "\n```")
            proc.wait()
        except Exception as e:
            st.error(f"Error while running extractor: {e}")
        finally:
            if proc.poll() is None:
                proc.terminate()

        if out_path.exists():
            st.success(f"Extractor finished — output: {out_path.name}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download CSV with emails', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            st.warning('Extractor did not produce an output file. Check logs above for details.')

# --- New: Steam search scraper UI ---
st.markdown("---")
st.header("Steam Search Scraper — collect game names & ids")
with st.form(key="steam_search_form"):
    search_queries_text = st.text_area("Search queries (one per line)", height=120, placeholder="roguelike\naction")
    search_queries_file = st.file_uploader("Or upload a queries file (one query per line)", type=["txt", "csv"], key="search_queries_file")
    search_pages = st.number_input("Pages per query", min_value=1, max_value=10, value=1)
    search_output_name = st.text_input("Output filename (optional)", value="steam_games.csv")
    search_no_headless = st.checkbox("Show browser while scraping (no-headless)", value=False)
    search_debug_dir = st.text_input("Debug dir for HTML snapshots (optional)", value="")
    run_search = st.form_submit_button("Run Steam search scraper")

if run_search:
    tmpdir_s = Path(tempfile.mkdtemp(prefix="steam_search_"))
    st.info(f"Working directory: {tmpdir_s}")
    queries_path = None
    # prefer uploaded file
    if search_queries_file is not None:
        queries_path = tmpdir_s / f"uploaded_queries_{int(time.time())}.txt"
        with open(queries_path, "wb") as f:
            f.write(search_queries_file.getbuffer())
    else:
        # use text area
        lines = [l.strip() for l in search_queries_text.splitlines() if l.strip()]
        if lines:
            queries_path = tmpdir_s / f"queries_{int(time.time())}.txt"
            with open(queries_path, "w", encoding="utf-8") as f:
                for l in lines:
                    f.write(l + "\n")
    if not queries_path or not queries_path.exists():
        st.error("No queries provided. Paste queries or upload a queries file.")
    else:
        # prepare output path
        output_path = tmpdir_s / (search_output_name.strip() if search_output_name.strip() else "steam_games.csv")
        cmd = ["python", "-m", "python_src.steam.steam_search_scrape", "--queries-file", str(queries_path), "--output", str(output_path), "--pages", str(int(search_pages))]
        if search_no_headless or not st.session_state.headless:
            cmd.append("--no-headless")
        if search_debug_dir and search_debug_dir.strip():
            # ensure debug dir is an absolute path inside tmpdir if relative
            dbg = search_debug_dir.strip()
            dbg_path = Path(dbg)
            if not dbg_path.is_absolute():
                dbg_path = tmpdir_s / dbg_path
            dbg_path.mkdir(parents=True, exist_ok=True)
            cmd += ["--debug-dir", str(dbg_path)]

        st.write("Running:", " ".join(cmd))
        log_box = st.empty()
        log_lines = []
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            while True:
                line = proc.stdout.readline()
                if line == '' and proc.poll() is not None:
                    break
                if line:
                    for sub in line.splitlines():
                        log_lines.append(sub)
                        if len(log_lines) > 2000:
                            log_lines = log_lines[-2000:]
                    log_box.markdown("```text\n" + "\n".join(log_lines) + "\n```")
            proc.wait()
        except Exception as e:
            st.error(f"Error while running search scraper: {e}")
        finally:
            if proc.poll() is None:
                proc.terminate()

        if output_path.exists():
            st.success(f"Search finished — output: {output_path.name}")
            with open(output_path, 'rb') as fh:
                st.download_button('Download CSV', fh.read(), file_name=output_path.name, mime='text/csv')
        else:
            st.warning('Search did not produce an output file. Check logs above for details.')

# --- New: Steam Charts (Most Played) scraper UI ---
st.markdown("---")
st.header("Steam Charts — Top N Most Played")
with st.form(key="steam_charts_form"):
    charts_count = st.number_input("Number of top chart games to collect", min_value=1, max_value=2000, value=200)
    charts_output_name = st.text_input("Output filename (optional)", value="steam_charts.csv")
    charts_include_details = st.checkbox("Collect curator counts (slow; visits each game page)", value=False)
    charts_no_headless = st.checkbox("Show browser while scraping (no-headless)", value=False)
    charts_debug_dir = st.text_input("Debug dir for HTML snapshots (optional)", value="")
    run_charts = st.form_submit_button("Run charts scraper")

if run_charts:
    tmpdir_c = Path(tempfile.mkdtemp(prefix="steam_charts_"))
    st.info(f"Working directory: {tmpdir_c}")

    # build command
    output_path = tmpdir_c / (charts_output_name.strip() if charts_output_name.strip() else "steam_charts.csv")
    cmd = ["python", "-m", "python_src.steam.steam_search_scrape", "--charts", "--charts-count", str(int(charts_count)), "--output", str(output_path)]
    if charts_no_headless or not st.session_state.headless:
        cmd.append("--no-headless")
    # if user does not want slow detail visits, pass --no-details
    if not charts_include_details:
        cmd.append("--no-details")
    if charts_debug_dir and charts_debug_dir.strip():
        dbg = charts_debug_dir.strip()
        dbg_path = Path(dbg)
        if not dbg_path.is_absolute():
            dbg_path = tmpdir_c / dbg_path
        dbg_path.mkdir(parents=True, exist_ok=True)
        cmd += ["--debug-dir", str(dbg_path)]

    st.write("Running:", " ".join(cmd))
    log_box = st.empty()
    log_lines = []
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        while True:
            line = proc.stdout.readline()
            if line == '' and proc.poll() is not None:
                break
            if line:
                for sub in line.splitlines():
                    log_lines.append(sub)
                    if len(log_lines) > 2000:
                        log_lines = log_lines[-2000:]
                log_box.markdown("```text\n" + "\n".join(log_lines) + "\n```")
        proc.wait()
    except Exception as e:
        st.error(f"Error while running charts scraper: {e}")
    finally:
        if proc.poll() is None:
            proc.terminate()

    if output_path.exists():
        st.success(f"Charts scraping finished — output: {output_path.name}")
        with open(output_path, 'rb') as fh:
            st.download_button('Download CSV', fh.read(), file_name=output_path.name, mime='text/csv')
        st.balloons()
    else:
        st.warning('Charts scraper did not produce an output file. Check logs above for details.')

# Removed YouTube scrapers UI — using Steam-only UI per user request
st.markdown("---")
st.text("YouTube scrapers have been disabled in this UI. Run the YouTube scripts (yt.py, youtube_discover_and_extract.py, extract_contacts_from_youtube.py) directly from the command line if needed.")

if run_btn:
    # prepare temp directory for inputs and outputs
    tmpdir = Path(tempfile.mkdtemp(prefix="steam_scraper_"))
    st.info(f"Working directory: {tmpdir}")

    input_csv_path = ""
    if input_csv is not None:
        input_csv_path = tmpdir / f"uploaded_input_{int(time.time())}.csv"
        with open(input_csv_path, "wb") as f:
            f.write(input_csv.getbuffer())
        input_csv_path = str(input_csv_path)

    games_file_path = ""
    # prefer explicit upload, otherwise use text box
    if games_file is not None:
        games_file_path = tmpdir / f"uploaded_games_{int(time.time())}.txt"
        with open(games_file_path, "wb") as f:
            f.write(games_file.getbuffer())
        games_file_path = str(games_file_path)
    elif games_text.strip():
        games_file_path = tmpdir / f"games_{int(time.time())}.txt"
        with open(games_file_path, "w", encoding="utf-8") as f:
            for line in games_text.splitlines():
                s = line.strip()
                if s:
                    f.write(s + "\n")
        games_file_path = str(games_file_path)
    else:
        st.error("No app ids provided. Paste app ids or upload a games file.")

    if games_file_path:
        # build command
        cmd = ["python", "-m", "python_src.steam.bbest", "--games-file", games_file_path, "--concurrency", str(concurrency)]
        if input_csv_path:
            cmd += ["--input-csv", input_csv_path]

        # Allow the launcher to force full scrolling to capture in-listing review snippets
        force_scroll = os.environ.get('STEAM_SCRAPER_FORCE_SCROLL') == '1'
        if force_scroll and not scroll_until_end:
            st.info("Launcher requested full scrolling to capture in-listing reviews.")
        if force_scroll or scroll_until_end:
            cmd += ["--scroll-until-end"]

        # If user provided a fixed output filename, pass an absolute path in tmpdir so the app writes there
        output_path = None
        if output_filename and output_filename.strip():
            output_path = tmpdir / output_filename.strip()
            cmd += ["--output-file", str(output_path)]
        else:
            # Always direct scraper output into our tmpdir so we don't accidentally pick up
            # old CSVs from the repo root (which may still contain a 'reviews' column).
            output_path = tmpdir / f"curators_output_{int(time.time())}.csv"
            cmd += ["--output-file", str(output_path)]
            st.info(f"Scraper will write output to temporary file: {output_path.name}")
        if export_new_only:
            cmd += ["--export-new-only"]
        if not st.session_state.headless:
            cmd.append('--no-headless')

        st.write("Running:", " ".join(cmd))

        # run subprocess and stream logs
        max_lines = 2000  # bounded buffer of lines to keep in the UI
        log_lines = deque(maxlen=max_lines)
        # Use a placeholder and render logs via a fenced code block (markdown) to avoid Streamlit API differences
        log_area.markdown("```text\n\n```")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        try:
            # Read line-by-line and update the UI incrementally
            while True:
                line = process.stdout.readline()
                if line == '' and process.poll() is not None:
                    break
                if line:
                    # store and display a bounded amount of recent log lines
                    for subline in line.splitlines():
                        log_lines.append(subline)
                    # update the placeholder output using a fenced code block so long logs render nicely
                    log_area.markdown("```text\n" + "\n".join(log_lines) + "\n```")
                    progress_text.text(log_lines[-1] if log_lines else "")
            process.wait()
        except Exception as e:
            st.error(f"Error while running scraper: {e}")
        finally:
            if process.poll() is None:
                process.terminate()

        # Determine output CSV to offer for download
        candidate = None
        # If we passed an explicit output path, use that first
        if output_path:
            if output_path.exists():
                candidate = output_path
        # else look in the temp dir for curators_*.csv
        if not candidate:
            csv_candidates = list(tmpdir.glob("curators_*.csv"))
            if csv_candidates:
                candidate = max(csv_candidates, key=lambda p: p.stat().st_mtime)

        if candidate:
            st.success(f"Done — output: {candidate}")
            with open(candidate, "rb") as f:
                data = f.read()
            st.download_button("Download CSV", data, file_name=candidate.name, mime="text/csv")

            # New: Add a convenience button to run the filler on this CSV and produce a *_filled.csv
            st.markdown("---")
            st.write("Need to fill missing 'about_me' or missing emails? Use the filler tool:")
            show_browser_for_filler = st.checkbox("Show browser while filling (no-headless)", value=False)
            run_filler = st.button("Fill missing about/email for this CSV")

            if run_filler:
                filled_path = candidate.with_name(candidate.stem + '_filled.csv')
                cmd_fill = ["python", "-m", "python_src.steam.fill_about_missing", "--input", str(candidate), "--output", str(filled_path), "--concurrency", str(max(1, concurrency))]
                if show_browser_for_filler or not st.session_state.headless:
                    cmd_fill.append("--no-headless")

                st.info("Running filler: " + " ".join(cmd_fill))
                # small log area for the filler
                filler_log = st.empty()
                filler_progress = st.empty()
                log_lines = []
                proc = subprocess.Popen(cmd_fill, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                try:
                    while True:
                        line = proc.stdout.readline()
                        if line == '' and proc.poll() is not None:
                            break
                        if line:
                            for sub in line.splitlines():
                                log_lines.append(sub)
                                if len(log_lines) > 2000:
                                    log_lines = log_lines[-2000:]
                                filler_log.markdown("```text\n" + "\n".join(log_lines) + "\n```")
                                filler_progress.text(log_lines[-1] if log_lines else "")
                    proc.wait()
                except Exception as e:
                    st.error(f"Error while running filler: {e}")
                finally:
                    if proc.poll() is None:
                        proc.terminate()

                if filled_path.exists():
                    st.success(f"Filler finished — output: {filled_path.name}")
                    with open(filled_path, 'rb') as fh:
                        st.download_button('Download filled CSV', fh.read(), file_name=filled_path.name, mime='text/csv')
                else:
                    st.warning('Filler did not produce an output file. Check logs above for details.')
        else:
            st.warning("No output CSV found — check logs.")

        st.balloons()
    else:
        st.error("Could not prepare games file")
