"""
Lightweight Streamlit UI for the YouTube discovery + contact extraction scripts.
Run with:
    streamlit run python_src/yt/app.py
or via the root helper: python run_yt.py

This app runs the two modules as subprocesses and streams their logs. When the subprocess
produces an output CSV, the UI offers a download button.
"""
import streamlit as st
import subprocess
import tempfile
import time
import os
from pathlib import Path

st.set_page_config(page_title="YouTube Contact Scraper", layout="centered")
st.title("YouTube discovery & contact extraction — UI")

st.markdown("This UI runs the two working YouTube scripts as subprocesses and streams logs.\nUse the Discover form to find recent videos/channels, then use the Extract form against a videos CSV to pull contact links/emails.")

import os
try:
    from python_src.shared import paths as shared_paths
except Exception:
    import sys
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from python_src.shared import paths as shared_paths

# Ensure outputs dir exists
OUT_DIR = shared_paths.OUTPUT_DIR
try:
    os.makedirs(OUT_DIR, exist_ok=True)
except Exception:
    pass

# --- Discover form ---
with st.form(key="yt_discover_form"):
    query = st.text_input("Search query", value="dice roguelike")
    max_channels = st.number_input("Max channels/videos", min_value=1, max_value=500, value=20)
    collect_videos = st.checkbox("Collect videos (return video links instead of channels)", value=False)
    no_headless = st.checkbox("Show browser during run (no-headless)", value=False)
    discover_output = st.text_input("Output CSV path (repo-relative)", value=os.path.join(OUT_DIR, f"yt_discover_{int(time.time())}.csv"))
    run_discover = st.form_submit_button("Run discovery")

if run_discover:
    out_path = Path(discover_output)
    # ensure directory
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    cmd = ["python", "-m", "python_src.yt.youtube_discover_and_extract", "--query", query, "--max-channels", str(int(max_channels)), "--output", str(out_path)]
    if collect_videos:
        cmd += ["--collect-videos"]
    if no_headless:
        cmd += ["--no-headless"]

    st.info("Running: " + " ".join(cmd))
    log_box = st.empty()
    log_lines = []
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        while True:
            line = proc.stdout.readline()
            if line == '' and proc.poll() is not None:
                break
            if line:
                log_lines.append(line.rstrip())
                if len(log_lines) > 2000:
                    log_lines = log_lines[-2000:]
                log_box.text_area("logs", value="\n".join(log_lines), height=300)
        proc.wait()
    except Exception as e:
        st.error(f"Error while running discovery: {e}")
        try:
            proc.terminate()
        except Exception:
            pass

    if out_path.exists():
        st.success(f"Discovery finished — output: {out_path}")
        with open(out_path, 'rb') as fh:
            st.download_button('Download discovery CSV', fh.read(), file_name=out_path.name, mime='text/csv')
    else:
        st.warning("Discovery did not produce an output CSV. Check logs above.")

st.markdown("---")

# --- Extract contacts form ---
with st.form(key="yt_extract_form"):
    input_upload = st.file_uploader("Videos CSV to extract from (columns: video_url, channel_url)", type=["csv"]) 
    input_path = st.text_input("Or existing CSV path (repo-relative)", value="")
    extract_no_headless = st.checkbox("Show browser during run (no-headless)", value=False)
    extract_output = st.text_input("Output CSV path (repo-relative)", value=os.path.join(OUT_DIR, f"yt_contacts_{int(time.time())}.csv"))
    run_extract = st.form_submit_button("Run contact extraction")

if run_extract:
    tmpdir = Path(tempfile.mkdtemp(prefix="yt_extract_"))
    candidate = None
    if input_upload is not None:
        candidate = tmpdir / f"uploaded_{int(time.time())}.csv"
        with open(candidate, 'wb') as f:
            f.write(input_upload.getbuffer())
    else:
        p = Path(input_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.exists():
            candidate = p
    if not candidate or not Path(candidate).exists():
        st.error("Input CSV not provided or not found")
    else:
        out_path = Path(extract_output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cmd = ["python", "-m", "python_src.yt.extract_contacts_from_youtube", "--input", str(candidate), "--output", str(out_path)]
        if extract_no_headless:
            cmd += ["--no-headless"]

        st.info("Running: " + " ".join(cmd))
        log_box = st.empty()
        log_lines = []
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            while True:
                line = proc.stdout.readline()
                if line == '' and proc.poll() is not None:
                    break
                if line:
                    log_lines.append(line.rstrip())
                    if len(log_lines) > 2000:
                        log_lines = log_lines[-2000:]
                    log_box.text_area("logs", value="\n".join(log_lines), height=300)
            proc.wait()
        except Exception as e:
            st.error(f"Error while running extraction: {e}")
            try:
                proc.terminate()
            except Exception:
                pass

        if out_path.exists():
            st.success(f"Extraction finished — output: {out_path}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download contacts CSV', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            st.warning("Extraction did not produce an output CSV. Check logs above.")

st.markdown("\n---\nYou can run this UI directly with:\n\n    streamlit run python_src/yt/app.py\n\nOr from repository root with: python run_yt.py")
