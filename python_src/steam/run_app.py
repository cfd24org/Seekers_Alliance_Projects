"""
Small launcher used for native packaging on macOS.
- Starts the Streamlit UI (using the same Python executable used to run this script)
- Opens the default browser pointing at the Streamlit UI
- Streams child process stdout/stderr to the console

Behavior is minimal so it can be bundled by PyInstaller.
"""
import os
import sys
import subprocess
import time
import webbrowser
import signal
import runpy
import threading
import urllib.request
import glob

PORT = os.environ.get("STEAM_UI_PORT", "8501")
STREAMLIT_CMD = [sys.executable, "-m", "streamlit", "run", "app.py", f"--server.port={PORT}", "--server.headless=true"]

def ensure_playwright_browsers():
    """Ensure Playwright browsers are installed. When packaging we prefer to install browsers at first run
    instead of bundling them with PyInstaller (which causes codesign and packaging issues).
    """
    try:
        # If PLAYWRIGHT_BROWSERS_PATH is set and exists, assume OK
        pw_path = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
        if pw_path and os.path.exists(pw_path):
            return True
        # Common cache location on macOS
        default_cache = os.path.expanduser('~/Library/Caches/ms-playwright')
        if os.path.exists(default_cache):
            return True
        # Otherwise, attempt to install browsers (non-interactive)
        print("Playwright browsers not found — installing Chromium (this may take a while)...")
        res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
        if res.returncode == 0:
            print("Playwright browsers installed")
            return True
        else:
            print("Failed to install Playwright browsers. Please run: python -m playwright install chromium")
            return False
    except Exception as e:
        print("Error while ensuring Playwright browsers:", e)
        return False

def wait_for_server(port, timeout=30.0, interval=0.5):
    """Poll localhost:port until we get an HTTP response or timeout.
    Returns True if server responds, False on timeout.
    """
    deadline = time.time() + float(timeout)
    url = f"http://127.0.0.1:{port}/"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                # any 2xx/3xx/4xx/5xx is OK — server responded
                return True
        except Exception:
            time.sleep(interval)
    return False

def _run_streamlit_in_process():
    """Run Streamlit in-process for bundled/frozen executables to avoid spawning a new process.
    We set sys.argv and run the streamlit CLI module via runpy. This keeps behavior similar to
    'python -m streamlit run app.py'.
    """
    argv = ["streamlit", "run", "app.py", f"--server.port={PORT}", "--server.headless=true"]
    sys.argv[:] = argv
    try:
        # Import and run streamlit's CLI as __main__
        runpy.run_module('streamlit.cli', run_name='__main__')
    except Exception as e:
        print('Failed to run Streamlit in-process:', e)

def main():
    env = os.environ.copy()

    # Clean up legacy CSV outputs in the repository root to avoid stale files with a 'reviews' column
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        removed = []
        for path in glob.glob(os.path.join(script_dir, 'curators_*.csv')):
            try:
                os.remove(path)
                removed.append(path)
            except Exception:
                pass
        if removed:
            print(f"Removed legacy CSV files to avoid stale columns: {removed}")
    except Exception:
        pass

    # When launched via this native launcher, prefer to enable "scroll until end"
    # which helps capture in-listing review snippets (carousel / store capsule text).
    # Don't override if the user already set this env var.
    if env.get('STEAM_SCRAPER_FORCE_SCROLL') is None:
        env['STEAM_SCRAPER_FORCE_SCROLL'] = '1'

    # If packaging didn't bundle browsers, attempt to install them at first run
    ensure_playwright_browsers()

    # Ensure Playwright has access to its cache relative to the executable if bundled
    possible_cache = os.path.join(os.path.dirname(sys.executable), 'ms-playwright')
    if os.path.exists(possible_cache):
        env.setdefault('PLAYWRIGHT_BROWSERS_PATH', possible_cache)

    # Always open the browser to show the Streamlit UI when the launcher runs.
    # Previously this respected STEAM_UI_OPENED to avoid repeated opens; we now
    # always attempt to open so the UI is visible to the user.
    already_opened = False

    # If this script is running from a PyInstaller bundle, running "sys.executable -m streamlit"
    # can attempt to execute the frozen binary again which may cause resource errors. In that case
    # run Streamlit in-process instead.
    if getattr(sys, 'frozen', False):
        # Run Streamlit in a background thread so we can poll the server without blocking.
        def run_streamlit_bg():
            try:
                _run_streamlit_in_process()
            except Exception as e:
                print('Streamlit in-process error:', e)

        t = threading.Thread(target=run_streamlit_bg, daemon=True)
        t.start()

        # Wait for server to be ready, then open browser once
        opened = False
        try:
            if not already_opened and wait_for_server(PORT, timeout=30):
                url = f"http://localhost:{PORT}"
                try:
                    webbrowser.open(url)
                    opened = True
                    env['STEAM_UI_OPENED'] = '1'
                except Exception:
                    print(f"Open your browser and visit {url}")
        except Exception as e:
            print('Error while waiting for Streamlit to start:', e)

        # Block until the background thread exits (Streamlit stops)
        try:
            t.join()
        except KeyboardInterrupt:
            pass

        return

    # Non-frozen: spawn Streamlit as a child process and forward its output
    proc = subprocess.Popen(STREAMLIT_CMD, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    # Wait for Streamlit to start before opening the browser; prevents repeated opens
    try:
        if not already_opened and wait_for_server(PORT, timeout=30):
            url = f"http://localhost:{PORT}"
            try:
                webbrowser.open(url)
                env['STEAM_UI_OPENED'] = '1'
            except Exception:
                print(f"Open your browser and visit {url}")
    except Exception as e:
        print('Error while waiting for Streamlit to start:', e)

    def handle_sigterm(signum, frame):
        try:
            proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    # Forward child output to our stdout
    try:
        for line in proc.stdout:
            if not line:
                break
            # bytes in pyinstaller bundled onefile may be bytes or str
            try:
                sys.stdout.write(line.decode() if isinstance(line, bytes) else line)
            except Exception:
                sys.stdout.write(str(line))
            sys.stdout.flush()
    except Exception as e:
        print("Launcher error:", e)
    finally:
        try:
            proc.terminate()
        except Exception:
            pass

if __name__ == '__main__':
    main()
