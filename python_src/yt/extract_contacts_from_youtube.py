#!/usr/bin/env python3
"""
extract_contacts_from_youtube.py

Given a CSV of YouTube videos (with columns: video_url, video_title, channel_url, channel_name),
visit each video's description and the channel's About page, and extract all public contact links:
- twitter, twitch, discord, instagram, facebook, patreon, linkedin, t.me, email, website

Usage:
  python extract_contacts_from_youtube.py --input yt_videos_broad_deduped.csv --output yt_contacts_extracted.csv [--no-headless] [--debug-dir debug_directory]

Requirements: playwright (and browsers installed via `python -m playwright install`)

Output: CSV with columns: video_url, video_title, channel_url, channel_name, found_contacts
(found_contacts is a semicolon-separated list of key=url, e.g. twitter=https://twitter.com/foo;email=foo@bar.com)
"""
import argparse
import csv
import re
import time
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime
try:
    from python_src.shared import csv_helpers
except Exception:
    import csv_helpers

SOCIAL_DOMAINS = ['twitter.com', 'x.com', 'instagram.com', 'twitch.tv', 'discord.gg', 'discord.com', 'patreon.com', 'linkedin.com', 'facebook.com', 't.me']
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'

def extract_links_and_emails(text):
    if not text:
        return [], []
    txt = text.replace('%40', '@')
    urls = URL_RE.findall(txt)
    emails = EMAIL_RE.findall(txt)
    emails = [e for e in emails if 'youtube' not in e and 'youtu.be' not in e]
    return list(dict.fromkeys(urls)), list(dict.fromkeys(emails))

def domain_of(u: str):
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ''

def normalize_url(base, href):
    if not href:
        return ''
    href = href.strip()
    if href.startswith('//'):
        return 'https:' + href
    if href.startswith('/'):
        return urljoin(base, href)
    if href.startswith('http'):
        return href
    return urljoin(base, href)

def extract_contacts(video_url, channel_url, page, debug_dir=None, idx=None):
    found = {}
    # Visit video and extract description links
    try:
        page.goto(video_url, timeout=30000)
        # Try multiple selectors for video description
        desc_html = ''
        try:
            desc_el = page.query_selector('#description')
            if desc_el:
                desc_html = desc_el.inner_text() or ''
            if not desc_html:
                desc_el2 = page.query_selector('yt-formatted-string.content')
                if desc_el2:
                    desc_html = desc_el2.inner_text() or ''
            if not desc_html:
                meta_desc = page.query_selector('meta[name="description"]')
                if meta_desc:
                    desc_html = meta_desc.get_attribute('content') or ''
            if not desc_html:
                desc_html = page.content()
        except Exception as e:
            desc_html = page.content()
            if debug_dir and idx is not None:
                with open(f"{debug_dir}/video_desc_fail_{idx}.html", "w", encoding="utf-8") as f:
                    f.write(desc_html)
        u2, e2 = extract_links_and_emails(desc_html)
        for uu in u2:
            dom = domain_of(uu)
            matched = False
            for sd in SOCIAL_DOMAINS:
                if sd in dom:
                    key = sd.split('.')[0]
                    found.setdefault(key, []).append(uu)
                    matched = True
                    break
            if not matched:
                found.setdefault('website', []).append(uu)
        for ee in e2:
            found.setdefault('email', []).append(ee)
    except Exception as e:
        if debug_dir and idx is not None:
            with open(f"{debug_dir}/video_page_fail_{idx}.txt", "w", encoding="utf-8") as f:
                f.write(f"Error: {e}\nURL: {video_url}\n")
    # Visit channel About page and extract main about text and links
    try:
        about_url = normalize_url(channel_url, '/about')
        page.goto(about_url, timeout=20000)
        time.sleep(1)
        about_text = ''
        try:
            about_el = page.query_selector('yt-formatted-string#description, .about-description, #description-container, #right-column yt-formatted-string, #content #description, #description-section')
            if about_el:
                about_text = about_el.inner_text() or ''
            if not about_text:
                meta_desc = page.query_selector('meta[name="description"]')
                if meta_desc:
                    about_text = meta_desc.get_attribute('content') or ''
            if not about_text:
                about_text = page.content()
        except Exception as e:
            about_text = page.content()
            if debug_dir and idx is not None:
                with open(f"{debug_dir}/about_fail_{idx}.html", "w", encoding="utf-8") as f:
                    f.write(about_text)
        urls, emails = extract_links_and_emails(about_text)
        for u in urls:
            dom = domain_of(u)
            matched = False
            for sd in SOCIAL_DOMAINS:
                if sd in dom:
                    key = sd.split('.')[0]
                    found.setdefault(key, []).append(u)
                    matched = True
                    break
            if not matched:
                found.setdefault('website', []).append(u)
        for e in emails:
            found.setdefault('email', []).append(e)
    except Exception as e:
        if debug_dir and idx is not None:
            with open(f"{debug_dir}/about_page_fail_{idx}.txt", "w", encoding="utf-8") as f:
                f.write(f"Error: {e}\nURL: {about_url}\n")
    # Dedupe
    for k, v in list(found.items()):
        if isinstance(v, list):
            found[k] = list(dict.fromkeys(v))
    return found

def main():
    parser = argparse.ArgumentParser(description='Extract contacts from YouTube video/channel descriptions')
    parser.add_argument('--input', required=True, help='Input CSV (from video search)')
    parser.add_argument('--output', required=True, help='Output CSV')
    parser.add_argument('--no-headless', action='store_true')
    parser.add_argument('--debug-dir', default=None, help='Directory to save debug HTML/text for failed cases')
    args = parser.parse_args()
    with open(args.input, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    out_rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.no_headless)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        for idx, row in enumerate(rows):
            video_url = row.get('video_url')
            channel_url = row.get('channel_url')
            print(f'[{idx+1}/{len(rows)}] Extracting from video: {video_url} | channel: {channel_url}')
            found = extract_contacts(video_url, channel_url, page, debug_dir=args.debug_dir, idx=idx)
            contact_parts = []
            for k, v in found.items():
                contact_parts.append(f"{k}={'|'.join(v)}")
            contact_str = ';'.join(contact_parts)
            out_row = dict(row)
            out_row['found_contacts'] = contact_str
            out_rows.append(out_row)
        try:
            browser.close()
        except Exception:
            pass
    with open(args.output, 'w', newline='', encoding='utf-8') as fh:
        try:
            fh.write(f"# created_by: extract_contacts_from_youtube.py | {datetime.utcnow().isoformat()}Z\n")
        except Exception:
            pass
        fieldnames = list(out_rows[0].keys())
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)
    # Ensure a consistent single-line author note is present at the top
    try:
        csv_helpers.prepend_author_note(args.output, created_by='extract_contacts_from_youtube.py')
    except Exception:
        pass
    print(f'Wrote {args.output} with {len(out_rows)} rows')

if __name__ == '__main__':
    main()
