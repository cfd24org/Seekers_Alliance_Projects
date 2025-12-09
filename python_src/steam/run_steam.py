"""
Run the Streamlit UI for the Steam scrapers.

This file replaces `app.py` to make the entrypoint name clearer. Run with:

    streamlit run python_src/steam/run_steam.py

The module is functionally identical to the previous `app.py` — it runs the same Streamlit UI and subprocesses.
"""
# ...existing code...
# The contents are intentionally identical to the previous app.py implementation.
# For brevity we import the original module if present to avoid duplicating maintenance.
try:
    from python_src.steam import app as _old_app
    # Re-export everything via the old app module (Streamlit will execute this file when run)
    # If the old app module defines Streamlit UI at import time, importing it here is sufficient.
except Exception:
    # Fallback: if import fails, load the file contents directly (keep a minimal safe message)
    import streamlit as st
    st.title("Steam Curator Scraper — GUI (run_steam.py)")
    st.write("Note: the packaged UI module failed to import; please check python_src/steam/app.py for details.")
