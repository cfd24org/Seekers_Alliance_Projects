import os
import sys
from datetime import datetime


def prepend_author_note(csv_path: str, created_by: str = None):
    """Prepend a single-line author note to the top of an existing CSV file.

    The note uses the format:
    # created_by: <created_by> | <ISO8601 timestamp>

    If the file already starts with a '#' line, this function will not add a duplicate.
    """
    if not csv_path or not os.path.exists(csv_path):
        print(f"[csv_helpers] File not found, skipping: {csv_path}")
        return False

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"[csv_helpers] Failed to read {csv_path}: {e}")
        return False

    # If already annotated, do nothing
    first_line = content.splitlines()[0] if content.splitlines() else ''
    if first_line.startswith('#'):
        print(f"[csv_helpers] File already annotated, skipping: {csv_path}")
        return True

    ts = datetime.utcnow().isoformat() + 'Z'
    note = f"# created_by: {created_by or os.path.basename(sys.argv[0])} | {ts}\n"
    try:
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            f.write(note)
            f.write(content)
        print(f"[csv_helpers] Prepended author note to {csv_path}")
        return True
    except Exception as e:
        print(f"[csv_helpers] Failed to write annotated file {csv_path}: {e}")
        return False


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python csv_helpers.py <csv_path> [created_by]")
        sys.exit(2)
    path = sys.argv[1]
    created_by = sys.argv[2] if len(sys.argv) > 2 else None
    ok = prepend_author_note(path, created_by)
    sys.exit(0 if ok else 1)
