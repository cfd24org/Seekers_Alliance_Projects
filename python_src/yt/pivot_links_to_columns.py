#!/usr/bin/env python3
"""
pivot_links_to_columns.py

Take the canonicalized uniform_links.csv (output of uniformize_links.py) and the
original input CSV (the one you ran discovery on) and produce a per-row CSV with
columns for services and website_N/email_N. Uses the `sources` column in the
uniformized file (row indices) to map canonical links back to each source row.

Usage:
  python pivot_links_to_columns.py --rows <discover.csv> --uniform uniform_links.csv --output final_contacts.csv

"""
import argparse
import csv
from collections import defaultdict


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rows', required=True, help='Original input CSV used to extract links')
    p.add_argument('--uniform', required=True, help='Canonicalized links CSV (from uniformize_links.py)')
    p.add_argument('--output', required=True)
    args = p.parse_args()

    # read original rows
    with open(args.rows, 'r', encoding='utf-8', newline='') as fh:
        reader = csv.DictReader(fh)
        orig_rows = list(reader)

    # prepare per-row mapping: index -> service -> list
    per_row = [defaultdict(list) for _ in range(len(orig_rows))]

    # read uniformized canonical links
    with open(args.uniform, 'r', encoding='utf-8', newline='') as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            svc = (r.get('service') or '').strip()
            canon = (r.get('canonical') or '').strip()
            sources = (r.get('sources') or '')
            if not sources:
                continue
            for s in sources.split('|'):
                if s.strip() == '':
                    continue
                try:
                    idx = int(s)
                except Exception:
                    continue
                if 0 <= idx < len(per_row):
                    per_row[idx][svc].append(canon)

    # determine all service keys
    svc_keys = set()
    max_web = 0
    max_email = 0
    for d in per_row:
        for k, v in d.items():
            svc_keys.add(k)
            if k == 'website':
                max_web = max(max_web, len(v))
            if k == 'email':
                max_email = max(max_email, len(v))
    svc_keys = sorted(list(svc_keys))

    # build fieldnames: preserve some common input cols if present
    input_cols = []
    if orig_rows:
        input_cols = list(orig_rows[0].keys())
    fieldnames = input_cols + svc_keys
    for i in range(1, max_web+1):
        fieldnames.append(f'website_{i}')
    for i in range(1, max_email+1):
        fieldnames.append(f'email_{i}')

    out_rows = []
    for i, base_row in enumerate(orig_rows):
        out = {k: base_row.get(k, '') for k in input_cols}
        d = per_row[i]
        for sk in svc_keys:
            out[sk] = '|'.join(d.get(sk, [])) if d.get(sk) else ''
        websites = d.get('website', [])
        emails = d.get('email', [])
        for idx in range(1, max_web+1):
            out[f'website_{idx}'] = websites[idx-1] if idx-1 < len(websites) else ''
        for idx in range(1, max_email+1):
            out[f'email_{idx}'] = emails[idx-1] if idx-1 < len(emails) else ''
        out_rows.append(out)

    with open(args.output, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f'Wrote {args.output} ({len(out_rows)} rows)')

if __name__ == '__main__':
    main()
