"""
Simple Streamlit frontend for your existing bbest.py scraper.
- Upload an existing CSV (optional) to run incremental updates
- Paste or upload a games file (one Steam appid per line)
- Toggle options and run the scraper

This app runs the existing `bbest.py` as a subprocess so your working script remains unchanged.
Run locally with:
    pip install streamlit
    streamlit run app.py

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
st.title("Steam Curator Scraper — GUI")

st.markdown("Upload an existing CSV (optional) to update, then supply one or more Steam app IDs (one per line) or upload a games file.")

# Left column: inputs
with st.form(key="scrape_form"):
    input_csv = st.file_uploader("Existing CSV to update (optional)", type=["csv"])
    games_text = st.text_area("App IDs (one per line)", height=120, placeholder="1948280\n3112170")
    games_file = st.file_uploader("Or upload a games file (one appid per line)", type=["txt", "csv"])    
    scroll_until_end = st.checkbox("Scroll until end (collect full listings)", value=False)
    concurrency = st.slider("Concurrency (profile page workers)", min_value=1, max_value=6, value=1)
    output_filename = st.text_input("Fixed output filename (optional, e.g. merged.csv)", value="")
    export_new_only = st.checkbox("Export only newly discovered curators (requires input CSV)", value=False)
    run_btn = st.form_submit_button("Run scraper")

# Area to show logs
log_area = st.empty()
progress_text = st.empty()

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
        cmd = ["python", "bbest.py", "--games-file", games_file_path, "--concurrency", str(concurrency)]
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
        else:
            st.warning("No output CSV found — check logs.")

        st.balloons()
    else:
        st.error("Could not prepare games file")
