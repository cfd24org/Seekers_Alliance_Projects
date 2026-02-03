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

st.markdown("---")

# --- Extract contacts (edition 2) form ---
with st.form(key="yt_extract_contacts_ed2_form"):
    ed2_input_upload = st.file_uploader("Channels CSV to extract descriptions from (columns: channel_url)", type=["csv"]) 
    ed2_input_path = st.text_input("Or existing CSV path (repo-relative)", value="")
    ed2_no_headless = st.checkbox("Show browser during run (no-headless)", value=False)
    ed2_debug_dir = st.text_input("Debug directory (optional, repo-relative)", value="")
    ed2_output = st.text_input("Output CSV path (repo-relative)", value=os.path.join(OUT_DIR, f"yt_descriptions_{int(time.time())}.csv"))
    run_ed2_extract = st.form_submit_button("Run contact extraction (edition 2)")

if run_ed2_extract:
    tmpdir = Path(tempfile.mkdtemp(prefix="yt_ed2_extract_"))
    candidate = None
    if ed2_input_upload is not None:
        candidate = tmpdir / f"uploaded_ed2_{int(time.time())}.csv"
        with open(candidate, 'wb') as f:
            f.write(ed2_input_upload.getbuffer())
    else:
        p = Path(ed2_input_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.exists():
            candidate = p
    if not candidate or not Path(candidate).exists():
        st.error("Input CSV not provided or not found")
    else:
        out_path = Path(ed2_output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cmd = ["python", "python_src/yt/extract_contacts.py", "--input", str(candidate), "--output", str(out_path)]
        if ed2_no_headless:
            cmd += ["--no-headless"]
        if ed2_debug_dir.strip():
            debug_p = Path(ed2_debug_dir)
            if not debug_p.is_absolute():
                debug_p = Path.cwd() / debug_p
            try:
                debug_p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            cmd += ["--debug-dir", str(debug_p)]

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
            st.error(f"Error while running edition 2 extraction: {e}")
            try:
                proc.terminate()
            except Exception:
                pass

        if out_path.exists():
            st.success(f"Edition 2 extraction finished — output: {out_path}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download descriptions CSV', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            st.warning("Edition 2 extraction did not produce an output CSV. Check logs above.")

st.markdown("---")

# --- Clean extracted contacts form ---
with st.form(key="yt_clean_form"):
    clean_input_upload = st.file_uploader("Extracted contacts CSV to clean", type=["csv"]) 
    clean_input_path = st.text_input("Or existing extracted CSV path (repo-relative)", value="")
    clean_output = st.text_input("Cleaned output CSV path (repo-relative)", value=os.path.join(OUT_DIR, f"yt_contacts_clean_{int(time.time())}.csv"))
    clean_dry = st.checkbox("Dry run (don't write output)", value=False)
    run_clean = st.form_submit_button("Run cleaner")

if run_clean:
    tmpdir = Path(tempfile.mkdtemp(prefix="yt_clean_"))
    candidate = None
    if clean_input_upload is not None:
        candidate = tmpdir / f"uploaded_clean_in_{int(time.time())}.csv"
        with open(candidate, 'wb') as f:
            f.write(clean_input_upload.getbuffer())
    else:
        p = Path(clean_input_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.exists():
            candidate = p
    if not candidate or not Path(candidate).exists():
        st.error("Input CSV not provided or not found")
    else:
        out_path = Path(clean_output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cmd = ["python", "-m", "python_src.yt.clean_yt_contacts", "--input", str(candidate), "--output", str(out_path)]
        if clean_dry:
            cmd += ["--dry-run"]

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
            st.error(f"Error while running cleaner: {e}")
            try:
                proc.terminate()
            except Exception:
                pass

        if out_path.exists():
            st.success(f"Cleaner finished — output: {out_path}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download cleaned CSV', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            if clean_dry:
                st.info("Dry-run completed. No output written.")
            else:
                st.warning("Cleaner did not produce an output CSV. Check logs above.")

st.markdown("---")

# --- Extract links (all) form ---
with st.form(key="yt_extract_links_all_form"):
    links_input_upload = st.file_uploader("CSV to scan for links (discover/contacts CSV)", type=["csv"]) 
    links_input_path = st.text_input("Or existing CSV path (repo-relative)", value="")
    links_output = st.text_input("Extracted links output CSV path (repo-relative)", value=os.path.join(OUT_DIR, f"extracted_links_{int(time.time())}.csv"))
    run_links_extract = st.form_submit_button("Run link extractor")

if run_links_extract:
    tmpdir = Path(tempfile.mkdtemp(prefix="yt_links_"))
    candidate = None
    if links_input_upload is not None:
        candidate = tmpdir / f"uploaded_links_in_{int(time.time())}.csv"
        with open(candidate, 'wb') as f:
            f.write(links_input_upload.getbuffer())
    else:
        p = Path(links_input_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.exists():
            candidate = p
    if not candidate or not Path(candidate).exists():
        st.error("Input CSV not provided or not found")
    else:
        out_path = Path(links_output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cmd = ["python", "-m", "python_src.yt.extract_links_all", "--input", str(candidate), "--output", str(out_path)]

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
            st.error(f"Error while running link extractor: {e}")
            try:
                proc.terminate()
            except Exception:
                pass

        if out_path.exists():
            st.success(f"Link extraction finished — output: {out_path}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download extracted links CSV', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            st.warning("Link extractor did not produce an output CSV. Check logs above.")

st.markdown("---")

# --- Uniformize links form ---
with st.form(key="yt_uniformize_links_form"):
    uniform_input_upload = st.file_uploader("Extracted links CSV to uniformize", type=["csv"]) 
    uniform_input_path = st.text_input("Or existing extracted links CSV path (repo-relative)", value="")
    uniform_output = st.text_input("Uniformized output CSV path (repo-relative)", value=os.path.join(OUT_DIR, f"uniform_links_{int(time.time())}.csv"))
    run_uniformize = st.form_submit_button("Run uniformizer")

if run_uniformize:
    tmpdir = Path(tempfile.mkdtemp(prefix="yt_uniform_"))
    candidate = None
    if uniform_input_upload is not None:
        candidate = tmpdir / f"uploaded_uniform_in_{int(time.time())}.csv"
        with open(candidate, 'wb') as f:
            f.write(uniform_input_upload.getbuffer())
    else:
        p = Path(uniform_input_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.exists():
            candidate = p
    if not candidate or not Path(candidate).exists():
        st.error("Input extracted links CSV not provided or not found")
    else:
        out_path = Path(uniform_output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cmd = ["python", "-m", "python_src.yt.uniformize_links", "--input", str(candidate), "--output", str(out_path)]

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
            st.error(f"Error while running uniformizer: {e}")
            try:
                proc.terminate()
            except Exception:
                pass

        if out_path.exists():
            st.success(f"Uniformizer finished — output: {out_path}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download uniform links CSV', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            st.warning("Uniformizer did not produce an output CSV. Check logs above.")

st.markdown("---")

# --- Pivot links to columns form ---
with st.form(key="yt_pivot_links_form"):
    pivot_rows_upload = st.file_uploader("Original rows CSV (discover/contacts CSV)", type=["csv"]) 
    pivot_rows_path = st.text_input("Or existing original CSV path (repo-relative)", value="")
    pivot_uniform_upload = st.file_uploader("Uniformized links CSV", type=["csv"]) 
    pivot_uniform_path = st.text_input("Or existing uniformized CSV path (repo-relative)", value="")
    pivot_output = st.text_input("Pivoted output CSV path (repo-relative)", value=os.path.join(OUT_DIR, f"yt_contacts_pivot_{int(time.time())}.csv"))
    run_pivot = st.form_submit_button("Run pivot")

if run_pivot:
    tmpdir = Path(tempfile.mkdtemp(prefix="yt_pivot_"))
    rows_candidate = None
    uniform_candidate = None
    if pivot_rows_upload is not None:
        rows_candidate = tmpdir / f"uploaded_rows_in_{int(time.time())}.csv"
        with open(rows_candidate, 'wb') as f:
            f.write(pivot_rows_upload.getbuffer())
    else:
        p = Path(pivot_rows_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.exists():
            rows_candidate = p
    if pivot_uniform_upload is not None:
        uniform_candidate = tmpdir / f"uploaded_uniform_in_{int(time.time())}.csv"
        with open(uniform_candidate, 'wb') as f:
            f.write(pivot_uniform_upload.getbuffer())
    else:
        q = Path(pivot_uniform_path)
        if not q.is_absolute():
            q = Path.cwd() / q
        if q.exists():
            uniform_candidate = q

    if not rows_candidate or not Path(rows_candidate).exists():
        st.error("Original rows CSV not provided or not found")
    elif not uniform_candidate or not Path(uniform_candidate).exists():
        st.error("Uniformized links CSV not provided or not found")
    else:
        out_path = Path(pivot_output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cmd = ["python", "-m", "python_src.yt.pivot_links_to_columns", "--rows", str(rows_candidate), "--uniform", str(uniform_candidate), "--output", str(out_path)]

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
            st.error(f"Error while running pivot: {e}")
            try:
                proc.terminate()
            except Exception:
                pass

        if out_path.exists():
            st.success(f"Pivot finished — output: {out_path}")
            with open(out_path, 'rb') as fh:
                st.download_button('Download pivoted contacts CSV', fh.read(), file_name=out_path.name, mime='text/csv')
        else:
            st.warning("Pivot did not produce an output CSV. Check logs above.")

st.markdown("\n---\nYou can run this UI directly with:\n\n    streamlit run python_src/yt/app.py\n\nOr from repository root with: python run_yt.py")
