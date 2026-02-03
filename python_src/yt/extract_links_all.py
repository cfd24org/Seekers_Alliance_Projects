#!/usr/bin/env python3
"""
extract_links_all.py

Scan a CSV (any tabular CSV) and extract every URL found anywhere in the row.
Writes a simple CSV with one extracted link per row along with the source row index
and some key input columns (if present).

Usage:
  python extract_links_all.py --input <input.csv> --output extracted_links.csv

"""
import argparse
import csv
import io
import re
import ast

URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+|[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s,]*)?")


def extract_from_value(v):
    links = []
    if not v:
        return links
    if isinstance(v, (list, tuple)):
        for it in v:
            links.extend(extract_from_value(it))
        return links
    if isinstance(v, dict):
        for it in v.values():
            links.extend(extract_from_value(it))
        return links
    s = str(v)
    # try to parse Python literal structures (some outputs contain repr(dict))
    if (s.startswith('{') or s.startswith('[')):
        try:
            lit = ast.literal_eval(s)
            return extract_from_value(lit)
        except Exception:
            pass
    # find obvious urls
    found = URL_RE.findall(s)
    # URL_RE returns tuples for the second alternative in some cases; normalize
    if found:
        for f in found:
            if isinstance(f, tuple):
                f = f[0]
            if f:
                links.append(f)
    return links


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()

    rows = []
    with open(args.input, 'r', encoding='utf-8', newline='') as fh:
        rdr = csv.DictReader(fh)
        rows = list(rdr)

    out_rows = []
    for idx, row in enumerate(rows):
        # prefer common columns for context
        video = (row.get('video_url') or row.get('video') or '')
        channel = (row.get('channel_url') or row.get('channel') or '')
        # scan all cells
        found = []
        for k, v in row.items():
            found.extend(extract_from_value(v))
        # also scan joined row text for anything missed
        joined = ' '.join([str(x) for x in row.values() if x])
        found.extend(URL_RE.findall(joined))
        # normalize tuples
        flat = []
        for f in found:
            if isinstance(f, tuple):
                f = f[0]
            if f and f not in flat:
                flat.append(f)
        for link in flat:
            out_rows.append({'row_index': idx, 'video_url': video, 'channel_url': channel, 'extracted_link': link})

    with open(args.output, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['row_index', 'video_url', 'channel_url', 'extracted_link'])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f'Wrote {args.output} ({len(out_rows)} links from {len(rows)} rows)')


if __name__ == '__main__':
    main()
