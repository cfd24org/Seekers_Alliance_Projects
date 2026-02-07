#!/usr/bin/env python3
"""
extract_contacts.py

Simple script to extract YouTube channel descriptions from a discover CSV.

Reads an input CSV (prefer a column named `channel_url`) and visits each provided
channel URL, opens the About panel, extracts the channel description, and writes
results to an output CSV.

Usage:
  python extract_contacts.py --input yt_discover.csv --output yt_descriptions.csv [--no-headless] [--debug-dir debug]

"""
import argparse
import csv
import io
import re
import time
from urllib.parse import urlparse, urljoin, parse_qs, unquote
from datetime import datetime
from playwright.sync_api import sync_playwright

import os
try:
    from python_src.shared import csv_helpers
except Exception:
    import sys
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from python_src.shared import csv_helpers
    except Exception:
        import csv_helpers

URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'


def dismiss_youtube_consent(page, timeout=2000):
    """Try to dismiss YouTube's cookie/consent dialog by clicking common localized buttons.
    Returns True if a button was clicked, False otherwise.
    """
    try:
        # small delay to let banner render
        page.wait_for_timeout(300)
    except Exception:
        pass

    candidates = [
        'button:has-text("Reject all")',
        'button:has-text("Reject")',
        'button:has-text("Reject all cookies")',
        'button:has-text("No, thanks")',
        'button:has-text("No, thanks.")',
        'button:has-text("Rechazar todo")',
        'button:has-text("No aceptar")',
        'tp-yt-paper-button:has-text("Reject all")',
        'tp-yt-paper-button:has-text("Reject")',
        'tp-yt-paper-button:has-text("Rechazar todo")',
        'ytd-button-renderer:has-text("Reject all")',
    ]

    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count():
                try:
                    loc.first.click(timeout=timeout)
                    page.wait_for_timeout(400)
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    # JS fallback: search buttons by common texts and click the first match
    try:
        clicked = page.evaluate(r"""
            () => {
                const texts = ["reject all","reject","rechazar todo","no aceptar","no, thanks","reject all cookies"];
                const nodes = Array.from(document.querySelectorAll('button, a, tp-yt-paper-button, ytd-button-renderer'));
                for (const n of nodes) {
                    try {
                        const t = (n.innerText || '').toLowerCase().trim();
                        for (const tt of texts) {
                            if (t === tt || t.includes(tt)) { n.click(); return true; }
                        }
                    } catch(e) { continue; }
                }
                return false;
            }
        """)
        if clicked:
            try:
                page.wait_for_timeout(400)
            except Exception:
                pass
            return True
    except Exception:
        pass

    return False


def normalize_url(base, href):
    if not href:
        return ''
    href = href.strip()
    if href.startswith('//'):
        return 'https:' + href
    if href.startswith('/'):
        return urljoin(base, href)
    # If it looks like a bare domain or domain/path (e.g. "twitch.tv/foo"), make it absolute
    if re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?$', href):
        return 'https://' + href
    if href.startswith('http'):
        return href
    return urljoin(base, href)


def _expand_truncated_description(page):
    """Try to click common "more" buttons that reveal truncated text on YouTube.
    Returns True if something was clicked, False otherwise.
    """
    selectors = [
        'button.yt-truncated-text__absolute-button',
        'button.yt-truncated-text__more-button',
        'tp-yt-paper-button#more',
        'button[aria-label^="Description"]',
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn:
                try:
                    btn.click(force=True)
                    page.wait_for_timeout(500)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    # JS fallback
    try:
        clicked = page.evaluate(r"""
            () => {
                const matchers = ['show more','see more','read more','more','tap for more'];
                const nodes = Array.from(document.querySelectorAll('button, a, tp-yt-paper-button'));
                for (const n of nodes) {
                    try:
                        const t = (n.innerText || '').toLowerCase();
                        for (const m of matchers) {
                            if (t.includes(m)) { n.click(); return true; }
                        }
                    } catch(e) { continue; }
                }
                return false;
            }
        """)
        if clicked:
            page.wait_for_timeout(500)
            return True
    except Exception:
        pass
    return False


def extract_description_from_channel(channel_url, page, debug_dir=None, idx=None):
    """Open channel home URL, open About panel, extract description.
    Returns (channel_name, description).
    """
    description = ''
    channel_name = ''
    try:
        # Navigate to the provided channel home URL
        try:
            page.goto(channel_url, timeout=25000)
        except Exception:
            try:
                page.goto(normalize_url(channel_url, '/'), timeout=25000)
            except Exception:
                pass
        page.wait_for_timeout(700)
        try:
            # dismiss cookie/consent banner if present (regional/localized variants)
            dismiss_youtube_consent(page)
        except Exception:
            pass

        # Try to extract a sensible channel name (fall back to page.title())
        try:
            cname = ''
            try:
                # common channel-name selectors (dialog or page header)
                el = page.query_selector('ytd-channel-name yt-formatted-string, #channel-name yt-formatted-string, tp-yt-paper-dialog ytd-channel-name yt-formatted-string')
                if el:
                    cname = (el.inner_text() or '').strip()
            except Exception:
                cname = ''
            if not cname:
                try:
                    title = page.title() or ''
                    cname = title.replace(' - YouTube', '').strip()
                except Exception:
                    cname = ''
            channel_name = cname
        except Exception:
            channel_name = ''

        # Try to extract description from the channel header (expand truncated first)
        try:
            desc_preview = page.query_selector('yt-description-preview-view-model')
            if desc_preview:
                desc_preview.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
            _expand_truncated_description(page)
            page.wait_for_timeout(2000)
            desc_element = page.query_selector('yt-description-preview-view-model yt-attributed-string span.yt-core-attributed-string')
            if desc_element:
                description = desc_element.text_content() or ''
                if debug_dir:
                    try:
                        with open(f"{debug_dir}/desc_debug_{idx}.txt", 'w', encoding='utf-8') as f:
                            f.write(f"Description: {description}\n")
                            f.write(f"Element HTML: {desc_element.evaluate('el => el.outerHTML')}\n")
                            f.write(f"Text content: {desc_element.text_content()}\n")
                            f.write(f"Inner text: {desc_element.inner_text()}\n")
                    except Exception as e:
                        pass
        except Exception:
            description = ''

        # If no description from header, try to click About and extract from there
        if not description:
            # Try to click an in-page About tab safely (prefer tab selectors)
            clicked_about = False
            try:
                about_selectors = [
                    'tp-yt-paper-tab:has-text("About")',
                    'tp-yt-paper-tab:has-text("ABOUT")',
                    'ytd-c4-tabbed-header-renderer tp-yt-paper-tab:has-text("About")',
                    'a[href*="/about"]',
                ]
                for sel in about_selectors:
                    try:
                        el = page.query_selector(sel)
                        if not el:
                            continue
                        # Avoid clicking elements that are inside a featured-video/player container
                        try:
                            safe = page.evaluate(r"""(el) => {
                                try {
                                    const bad = el.closest('ytd-channel-video-player-renderer, ytd-channel-video-player, #player, .html5-video-player, ytd-channel-video-player-renderer');
                                    return !bad;
                                } catch(e) { return true; }
                            }""", el)
                        except Exception:
                            safe = True
                        if not safe:
                            continue

                        # ensure element visible and attempt click
                        try:
                            el.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        try:
                            el.click(force=True)
                            page.wait_for_timeout(800)
                            clicked_about = True
                            break
                        except Exception:
                            continue
                    except Exception:
                        continue
            except Exception:
                clicked_about = False

            # If About didn't appear by tabs, try to open the engagement panel About renderer (some channels pop a panel)
            if not clicked_about:
                try:
                    # there may be an engagement-panel or about button we can click without hitting video thumbnails
                    panel_btn = page.query_selector('a[href*="/channel/"][href*="/about"], a[href$="/about"]')
                    if panel_btn:
                        try:
                            # safety check for panel button as well
                            try:
                                safe_panel = page.evaluate(r"""(el) => {
                                    try {
                                        const bad = el.closest('ytd-channel-video-player-renderer, ytd-channel-video-player, #player, .html5-video-player');
                                        return !bad;
                                    } catch(e) { return true; }
                                }""", panel_btn)
                            except Exception:
                                safe_panel = True
                            if not safe_panel:
                                clicked_about = False
                            else:
                                try:
                                    panel_btn.scroll_into_view_if_needed()
                                except Exception:
                                    pass
                                try:
                                    panel_btn.click(force=True)
                                    page.wait_for_timeout(800)
                                    clicked_about = True
                                except Exception:
                                    clicked_about = False
                        except Exception:
                            clicked_about = False
                except Exception:
                    clicked_about = False

            # Extract the channel description from About panel
            if clicked_about:
                try:
                    page.wait_for_timeout(1000)
                    # Locate the about-container first
                    about_container = page.query_selector('tp-yt-paper-dialog ytd-about-channel-renderer #about-container')
                    if about_container:
                        # Then find the description container inside it
                        desc_element = about_container.query_selector('yt-attributed-string#description-container')
                        if desc_element:
                            # Check if "Read more" button exists and click it
                            _expand_truncated_description(page)
                            # Get the span inside it
                            span = desc_element.query_selector('span.yt-core-attributed-string')
                            if span:
                                description = span.inner_text() or ''
                            else:
                                # Fallback to the element's inner_text
                                description = desc_element.inner_text() or ''
                except Exception:
                    description = ''

        # Close any dialog/panel we opened to return DOM to stable state
        try:
            page.keyboard.press('Escape')
            page.wait_for_timeout(300)
        except Exception:
            pass

    except Exception as e:
        if debug_dir and idx is not None:
            try:
                with open(f"{debug_dir}/about_page_fail_{idx}.txt", 'w', encoding='utf-8') as f:
                    f.write(f"Error: {e}\nURL: {channel_url}\n")
            except Exception:
                pass

    return channel_name, description


def main():
    parser = argparse.ArgumentParser(description='Extract YouTube channel descriptions from discover CSV')
    parser.add_argument('--input', required=True, help='Input CSV from YouTube discover script')
    parser.add_argument('--output', required=True, help='Output CSV with descriptions')
    parser.add_argument('--no-headless', action='store_true', help='Run browsers in headful mode when set')
    parser.add_argument('--debug-dir', default=None, help='Directory to save debug HTML/text')
    args = parser.parse_args()

    # Read CSV skipping leading comment lines
    with open(args.input, 'r', encoding='utf-8', newline='') as fh:
        raw = fh.read().splitlines()
    # drop leading blank/comment lines
    start = 0
    for i, ln in enumerate(raw):
        if ln.strip() == '' or ln.lstrip().startswith('#'):
            continue
        start = i
        break
    cleaned = raw[start:]
    if not cleaned:
        print('No CSV content after skipping comments')
        return
    reader = csv.DictReader(io.StringIO('\n'.join(cleaned)))
    print(f"Detected CSV columns: {reader.fieldnames}")
    rows = list(reader)
    if not rows:
        print('No rows in CSV')
        return

    raw_out_rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.no_headless)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        for idx, row in enumerate(rows):
            channel_url = (row.get('channel_url') or row.get('channel') or '').strip()
            if channel_url:
                print(f'[{idx+1}/{len(rows)}] Channel: {channel_url}')
                cname, desc = extract_description_from_channel(channel_url, page, debug_dir=args.debug_dir, idx=idx)
                out_row = dict(row)
                out_row['channel_name_extracted'] = cname
                out_row['description'] = desc
                raw_out_rows.append(out_row)
            else:
                print(f'[{idx+1}/{len(rows)}] Skipping malformed row: {row}')

        try:
            browser.close()
        except Exception:
            pass

    # Build CSV fieldnames: preserve input columns, add channel_name_extracted and description
    if raw_out_rows:
        input_cols = list(rows[0].keys())
        fieldnames = input_cols + ['channel_name_extracted', 'description']

        final_rows = []
        for r in raw_out_rows:
            base = {k: r.get(k, '') for k in input_cols}
            base['channel_name_extracted'] = r.get('channel_name_extracted', '')
            base['description'] = r.get('description', '')
            final_rows.append(base)

        with open(args.output, 'w', newline='', encoding='utf-8') as fh:
            try:
                fh.write(f"# created_by: extract_contacts.py | {datetime.utcnow().isoformat()}Z\n")
            except Exception:
                pass
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(final_rows)
        try:
            csv_helpers.prepend_author_note(args.output, created_by='extract_contacts.py')
        except Exception:
            pass
        print(f'Wrote {args.output} ({len(final_rows)} rows)')
    else:
        print('No descriptions extracted; no output written')


if __name__ == '__main__':
    main()
