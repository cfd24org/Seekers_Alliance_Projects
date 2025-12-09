# Lightweight root-level launcher so you can run:
#   python run_app.py
# from the repository root while keeping the real launcher in python_src/steam/run_app.py

import os
import sys

# Ensure repo root (this file's dir) is on sys.path so python_src package imports work
repo_root = os.path.dirname(os.path.abspath(__file__))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

try:
    # Import the packaged launcher and invoke main()
    from python_src.steam import run_app as _run_app
except Exception as e:
    print("Failed to import python_src.steam.run_app:", e)
    print("Make sure you're running from the repository root and that python_src/ is present.")
    raise

if __name__ == '__main__':
    _run_app.main()
