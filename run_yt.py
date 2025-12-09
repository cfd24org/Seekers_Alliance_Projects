# Convenience root-level launcher for the YouTube Streamlit UI.
# Run from repository root: python run_yt.py

import os
import sys

repo_root = os.path.dirname(os.path.abspath(__file__))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

try:
    from python_src.yt import app as yt_app
except Exception as e:
    print('Failed to import python_src.yt.app:', e)
    raise

if __name__ == '__main__':
    # Launch Streamlit against the moved app
    cmd = [sys.executable, '-m', 'streamlit', 'run', os.path.join(repo_root, 'python_src', 'yt', 'app.py')]
    os.execv(sys.executable, cmd)
