import os

# Absolute debug snapshot directory (non_py/debug_about_missing at repo root)
DEBUG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'non_py', 'debug_about_missing'))
# Ensure directory exists
try:
    os.makedirs(DEBUG_DIR, exist_ok=True)
except Exception:
    pass

# Central outputs directory for generated CSVs (repo-root/outputs)
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'outputs'))
# Ensure outputs directory exists
try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except Exception:
    pass
