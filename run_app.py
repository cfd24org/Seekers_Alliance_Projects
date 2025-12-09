# Lightweight root-level launcher so you can run:
#   python run_app.py
# from the repository root. This script launches Streamlit against
# python_src/steam/app.py and streams process output to the console.

import os
import sys
import subprocess
import time
import webbrowser
import urllib.request

PORT = os.environ.get("STEAM_UI_PORT", "8501")


def wait_for_server(port, timeout=30.0, interval=0.5):
    deadline = time.time() + float(timeout)
    url = f"http://127.0.0.1:{port}/"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return True
        except Exception:
            time.sleep(interval)
    return False


def stream_subprocess(cmd, env=None):
    print(f"Launching: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, bufsize=1)

    # Stream output in background thread-like loop
    try:
        while True:
            line = proc.stdout.readline()
            if line == '' and proc.poll() is not None:
                break
            if line:
                try:
                    sys.stdout.write(line)
                except Exception:
                    print(line)
        proc.wait()
    except KeyboardInterrupt:
        try:
            proc.terminate()
        except Exception:
            pass
    return proc.returncode


def main():
    repo_root = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(repo_root, 'python_src', 'steam', 'app.py')
    if not os.path.exists(app_path):
        print(f"App not found at expected path: {app_path}")
        sys.exit(2)

    cmd = [sys.executable, "-m", "streamlit", "run", app_path, f"--server.port={PORT}", "--server.headless=true"]
    env = os.environ.copy()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, bufsize=1)

    # Wait a short while for the server to start, while streaming output
    start = time.time()
    # Create a non-blocking streamer loop that also polls server status
    try:
        while True:
            # Read and print any available line
            line = proc.stdout.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
            # Check if server is up
            if wait_for_server(PORT, timeout=0.5):
                url = f"http://localhost:{PORT}"
                try:
                    webbrowser.open(url)
                except Exception:
                    print(f"Open your browser and visit {url}")
                # Now stream remaining output to console until process exits or user cancels
                for l in proc.stdout:
                    try:
                        sys.stdout.write(l)
                    except Exception:
                        print(l)
                break
            # If process exited unexpectedly, break and show exit code
            if proc.poll() is not None:
                break
            # Avoid tight loop
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Interrupted; terminating Streamlit process...")
        try:
            proc.terminate()
        except Exception:
            pass
        sys.exit(1)

    rc = proc.poll()
    if rc is None:
        try:
            rc = proc.wait()
        except Exception:
            rc = -1
    print(f"Streamlit exited with code: {rc}")
    sys.exit(rc or 0)


if __name__ == '__main__':
    main()
