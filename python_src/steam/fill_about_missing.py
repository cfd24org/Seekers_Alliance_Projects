#!/usr/bin/env python3
"""
fill_about_missing.py

Given a curator CSV produced by `bbbest.py`, visit curator profiles with missing or
error-marked `about_me` fields and attempt to extract the About text and any
mailto email. Writes an updated CSV with filled fields and snapshots for failures.

Usage example (zsh):
  python fill_about_missing.py --input curators.csv --output curators_filled.csv --concurrency 1 --no-headless

Requirements: playwright (and browsers installed via: python -m playwright install)
"""
import argparse
import asyncio
import builtins
import csv
import json
import os
import re
import sys
import time
import urllib.parse
from typing import List

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

try:
    from python_src.shared import csv_helpers
    from python_src.shared import paths as shared_paths
except Exception:
    import csv_helpers
    import paths as shared_paths

# Prevent BlockingIOError when many async tasks write to stdout: make stdout blocking
try:
    os.set_blocking(sys.stdout.fileno(), True)
except Exception:
    pass

_original_print = builtins.print

def _safe_print(*args, **kwargs):
    try:
        _original_print(*args, **kwargs)
    except BlockingIOError:
        try:
            with open('fill_about_stdout.log', 'a', encoding='utf-8') as f:
                end = kwargs.get('end', '\n')
                f.write(' '.join(str(a) for a in args) + end)
        except Exception:
            pass

builtins.print = _safe_print

# Tunables
NAV_TIMEOUT_MS = 30000
NAV_RETRIES = 2
NAV_RETRY_SLEEP = 2
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

ABOUT_ERROR_MARKER = "[ERROR: Unable to extract 'about me' section]"


async def extract_email_from_link(elem):
    if not elem:
        return "", ""
    href = await elem.get_attribute('href') or ''
    text = (await elem.inner_text()) or ''
    # visible text first
    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    if m:
        return href, m.group(0)
    decoded = urllib.parse.unquote(href or '')
    if decoded.lower().startswith('mailto:'):
        return href, decoded.split('mailto:')[-1]
    m2 = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", decoded)
    if m2:
        return href, m2.group(0)
    return href, ''


async def extract_about_and_email_from_profile(page, name: str):
    """Return (about_text, email) extracted from the profile page or ("", "") on failure.
    Saves a snapshot to debug_about_missing/ when about extraction fails.
    """
    about_text = ""
    email_found = ""
    try:
        about_link_el = await page.query_selector('a.about')
        navigated = False
        if about_link_el:
            about_url = await about_link_el.get_attribute('href')
            if about_url and (about_url.startswith('http') or about_url.startswith('/')):
                for attempt in range(NAV_RETRIES + 2):
                    try:
                        await page.goto(about_url, timeout=NAV_TIMEOUT_MS, wait_until='networkidle')
                        navigated = True
                        break
                    except PlaywrightTimeoutError:
                        if attempt < NAV_RETRIES + 1:
                            await asyncio.sleep(NAV_RETRY_SLEEP)
                        else:
                            break
            else:
                try:
                    await about_link_el.click()
                    try:
                        await page.wait_for_load_state('networkidle', timeout=10000)
                    except Exception:
                        pass
                    navigated = True
                except Exception:
                    pass

        try:
            await page.wait_for_selector('div.about_container div.desc, div.desc, div.profile_about', timeout=8000)
        except Exception:
            pass

        for sel in (
            'div.about_container div.desc p.tagline',
            'div.about_container div.desc',
            'div.desc p',
            'div.desc',
            'div.profile_about',
            'div.curator_about',
        ):
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                try:
                    pchildren = await el.query_selector_all('p')
                    if pchildren:
                        parts = []
                        for p in pchildren:
                            try:
                                t = (await p.inner_text()) or ''
                                t = t.strip()
                                if t:
                                    parts.append(t)
                            except Exception:
                                continue
                        txt = ' '.join(parts).strip()
                    else:
                        txt = (await el.inner_text()) or ''
                except Exception:
                    txt = (await el.inner_text()) or ''

                txt = (txt or '').strip()
                if txt:
                    about_text = txt
                    break
            except Exception:
                continue

        if not about_text:
            try:
                meta = await page.query_selector('meta[name="description"], meta[property="og:description"]')
                if meta:
                    about_text = (await meta.get_attribute('content') or '').strip()
            except Exception:
                pass

        if not about_text:
            try:
                scripts = await page.query_selector_all('script[type="application/ld+json"]')
                for s in scripts:
                    try:
                        raw = (await s.inner_text()) or ''
                        obj = json.loads(raw)
                        desc = None
                        if isinstance(obj, dict):
                            desc = obj.get('description') or obj.get('about')
                        elif isinstance(obj, list):
                            for item in obj:
                                if isinstance(item, dict) and item.get('description'):
                                    desc = item.get('description')
                                    break
                        if desc:
                            about_text = str(desc).strip()
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if not about_text:
            try:
                body = (await page.inner_text('body') or '').strip()
                parts = re.split(r"\n?\s*[\d,]+\s*(?:CURATOR|CREATOR)?\s*FOLLOWERS\b", body, flags=re.I)
                candidate = parts[0] if parts else body
                if len(candidate) > 40:
                    about_text = candidate
                else:
                    for line in body.splitlines():
                        t = line.strip()
                        if len(t) > 40 and not re.search(r'FOLLOWERS|REVIEWS|POSTED', t, flags=re.I):
                            about_text = t
                            break
            except Exception:
                pass

        if not email_found:
            try:
                mail_el = await page.query_selector("a[href^='mailto:']")
                if mail_el:
                    href = await mail_el.get_attribute('href') or ''
                    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", href)
                    if m:
                        email_found = m.group(0)
            except Exception:
                pass

        if about_text:
            about_text = about_text.strip(' \t\n\r"\'“”')
            about_text = re.sub(r'\s{2,}', ' ', about_text)
            about_text = re.sub(r"\n?\s*[\d,]+\s*(?:CURATOR|CREATOR)?\s*FOLLOWERS\b.*", "", about_text, flags=re.I)
            about_text = re.sub(r"\n?\s*[\d,]+\s*(?:REVIEWS|REVIEWS POSTED|POSTED)\b.*", "", about_text, flags=re.I)
            about_text = re.sub(r"\bPOSTED\b", "", about_text, flags=re.I)
            about_text = re.sub(r"\s+", " ", about_text).strip()
            if len(about_text) > 800:
                about_text = about_text[:800]

        if not about_text:
            try:
                dbg_dir = getattr(shared_paths, 'DEBUG_DIR', os.path.join(os.path.dirname(__file__), '..', '..', 'non_py', 'debug_about_missing'))
                os.makedirs(dbg_dir, exist_ok=True)
                safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', name)[:50] or 'unknown'
                snap = f"{dbg_dir}/{safe_name}_{int(time.time())}.html"
                html = await page.content()
                with open(snap, 'w', encoding='utf-8') as fh:
                    fh.write(html[:200000])
                print(f"[DEBUG] About missing - saved snapshot: {snap}")
            except Exception:
                pass

    except Exception as e:
        print(f"[{name}] Error extracting about/email: {e}")

    return about_text or "", email_found or ""


async def process_profile(profile_link: str, name: str, page_pool: asyncio.Queue):
    page = await page_pool.get()
    try:
        try:
            await page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        except Exception:
            pass
        try:
            await page.set_extra_http_headers({"User-Agent": DEFAULT_USER_AGENT})
        except Exception:
            pass

        for attempt in range(NAV_RETRIES + 1):
            try:
                await page.goto(profile_link, timeout=NAV_TIMEOUT_MS, wait_until='domcontentloaded')
                break
            except PlaywrightTimeoutError:
                if attempt < NAV_RETRIES:
                    await asyncio.sleep(NAV_RETRY_SLEEP)
                else:
                    print(f"[{name}] Timeout navigating to profile after {NAV_RETRIES+1} attempts")

        about_text, email = await extract_about_and_email_from_profile(page, name)

        try:
            await page.goto('about:blank', timeout=5000)
        except Exception:
            pass

        return about_text, email
    except Exception as e:
        print(f"[{name}] Error when visiting profile: {e}")
        return "", ""
    finally:
        await page_pool.put(page)


async def main_async(args):
    if not os.path.exists(args.input):
        print(f"Input CSV not found: {args.input}")
        return 1

    rows = []
    with open(args.input, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    to_fix = []
    for i, r in enumerate(rows):
        about = (r.get('about_me') or '').strip()
        if not about or about == ABOUT_ERROR_MARKER:
            profile = (r.get('steam_profile') or '').strip()
            name = (r.get('curator_name') or '').strip() or 'unknown'
            if profile:
                to_fix.append((i, profile, name))

    print(f"Found {len(to_fix)} profiles with missing about_me to attempt filling")
    if not to_fix:
        print("Nothing to do.")
        return 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.no_headless)
        page_pool = asyncio.Queue()
        for _ in range(max(1, args.concurrency)):
            pg = await browser.new_page()
            try:
                await pg.set_extra_http_headers({"User-Agent": DEFAULT_USER_AGENT})
            except Exception:
                pass
            try:
                await pg.set_default_navigation_timeout(NAV_TIMEOUT_MS)
            except Exception:
                pass
            await pg.goto('about:blank')
            await page_pool.put(pg)

        semaphore = asyncio.Semaphore(args.concurrency)

        async def worker(idx, profile_link, name):
            async with semaphore:
                about_text, email = await process_profile(profile_link, name, page_pool)
                # update about_me (always replace with extracted text, otherwise set error marker)
                if about_text:
                    rows[idx]['about_me'] = about_text
                else:
                    rows[idx]['about_me'] = ABOUT_ERROR_MARKER

                # existing email in CSV (may be empty)
                existing = (rows[idx].get('email') or '').strip()

                # if scraper found an email, write it only when CSV email is empty or invalid
                if email:
                    if not existing or not re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", existing):
                        rows[idx]['email'] = email
                    # mark that we have an email
                    rows[idx]['has_email'] = 1
                else:
                    # keep existing valid email if present, otherwise clear/mark missing
                    if existing and re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", existing):
                        rows[idx]['has_email'] = 1
                    else:
                        rows[idx]['email'] = ''
                        rows[idx]['has_email'] = 0

                print(f"Processed {name} -> about_len={len(rows[idx]['about_me'] or '')} email={rows[idx].get('email','')}")

        tasks = [worker(i, profile, name) for (i, profile, name) in to_fix]
        if tasks:
            await asyncio.gather(*tasks)

        while not page_pool.empty():
            pg = await page_pool.get()
            await pg.close()

        await browser.close()

    out_path = args.output or (os.path.splitext(args.input)[0] + '_filled.csv')
    fieldnames = rows[0].keys() if rows else [
        'curator_name', 'steam_profile', 'followers', 'reviews', 'external_site', 'about_me', 'sample_review', 'email', 'has_email', 'game'
    ]
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    try:
        csv_helpers.prepend_author_note(out_path, created_by='fill_about_missing.py')
    except Exception:
        pass

    print(f"Saved updated CSV to {out_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description='Fill missing about_me entries by visiting curator profiles')
    parser.add_argument('--input', required=True, help='Input curator CSV')
    parser.add_argument('--output', help='Output CSV path')
    parser.add_argument('--concurrency', type=int, default=1, help='Number of concurrent pages (default 1)')
    parser.add_argument('--no-headless', dest='no_headless', action='store_true', help='Run browser non-headless')
    args = parser.parse_args()

    args.concurrency = max(1, args.concurrency)

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print('Interrupted by user')
        return 1

if __name__ == '__main__':
    sys.exit(main())
