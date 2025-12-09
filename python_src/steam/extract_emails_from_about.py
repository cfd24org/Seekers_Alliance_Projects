#!/usr/bin/env python3
"""
extract_emails_from_about.py

Simple utility: given a CSV with an `about_me` column, scan the about_me text
for email addresses and populate the `email` column and set `has_email`=1 when
an email is found and the CSV `email` is empty or invalid.

Usage:
  python extract_emails_from_about.py --input curators.csv --output curators_with_emails.csv

Rules:
- Accepts typical emails (gmail, hotmail, icloud, custom domains, etc).
- Ignores matches that look like YouTube channel URLs (contains 'youtube' or 'youtu.be').
- Prefers existing CSV email when valid; only fills when missing or invalid.
"""
import argparse
import csv
import os
import re
import sys

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

def looks_like_youtube(s: str) -> bool:
    if not s:
        return False
    s = s.lower()
    return 'youtube' in s or 'youtu.be' in s


def find_email_in_text(text: str):
    if not text:
        return None
    # decode common URL encoding for mailto if present (basic)
    text = text.replace('%40', '@')
    # find all candidates
    for m in EMAIL_RE.findall(text):
        if looks_like_youtube(m):
            continue
        # avoid matches that include 'youtube' nearby
        context = text.lower()
        if 'youtube' in context:
            # if youtube mentioned, ensure the matched email isn't part of a youtube url
            # naive: skip if 'youtube' appears within 30 chars of the match
            idx = context.find(m.lower())
            if idx != -1:
                start = max(0, idx - 30)
                end = min(len(context), idx + len(m) + 30)
                if 'youtube' in context[start:end] or 'youtu.be' in context[start:end]:
                    continue
        return m
    return None


def is_valid_email(s: str) -> bool:
    if not s:
        return False
    return EMAIL_RE.fullmatch(s) is not None


def main():
    parser = argparse.ArgumentParser(description='Extract emails from about_me column and fill email field')
    parser.add_argument('--input', required=True, help='Input CSV file')
    parser.add_argument('--output', help='Output CSV path (defaults to input_filled.csv)')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print('Input not found:', args.input)
        sys.exit(1)

    out_path = args.output or (os.path.splitext(args.input)[0] + '_emails.csv')

    with open(args.input, newline='', encoding='utf-8') as f:
        reader = list(csv.DictReader(f))
        if not reader:
            print('No rows in CSV')
            sys.exit(1)
        fieldnames = list(reader[0].keys())
        # ensure email/has_email/about_me exist
        if 'about_me' not in fieldnames:
            print("Input CSV has no 'about_me' column")
        if 'email' not in fieldnames:
            fieldnames.append('email')
        if 'has_email' not in fieldnames:
            fieldnames.append('has_email')

    changed = 0
    for row in reader:
        about = (row.get('about_me') or '')
        existing = (row.get('email') or '').strip()
        if existing and is_valid_email(existing):
            row['has_email'] = 1
            continue
        found = find_email_in_text(about)
        if found and is_valid_email(found):
            row['email'] = found
            row['has_email'] = 1
            changed += 1
        else:
            # also try external_site or sample_review fields if present
            ext = (row.get('external_site') or '')
            samp = (row.get('sample_review') or '')
            for src in (ext, samp):
                if not found:
                    f2 = find_email_in_text(src)
                    if f2 and is_valid_email(f2):
                        row['email'] = f2
                        row['has_email'] = 1
                        changed += 1
                        break

    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reader)

    print(f'Wrote {out_path} (filled {changed} emails)')

if __name__ == '__main__':
    main()
