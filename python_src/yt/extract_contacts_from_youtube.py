#!/usr/bin/env python3
"""
extract_contacts_from_youtube.py

Channel-focused contact extractor for YouTube.

Reads an input CSV (prefer a column named `channel_url`) and visits each provided
channel URL (opens the channel home), optionally clicks an on-page "About" tab
if found, extracts the header preview and the About renderer text and links,
parses URLs and emails, and writes results to an output CSV.

Usage:
  python extract_contacts_from_youtube.py --input discover.csv --output outputs/yt_contacts.csv [--no-headless] [--debug-dir debug]

"""
import argparse
import csv
import io
import re
import time
from urllib.parse import urlparse, urljoin, parse_qs, unquote
from datetime import datetime
from playwright.sync_api import sync_playwright

try:
    from python_src.shared import csv_helpers
except Exception:
    import csv_helpers

SOCIAL_DOMAINS = [
    'twitter.com', 'x.com', 'instagram.com', 'twitch.tv', 'discord.gg', 'discord.com',
    'patreon.com', 'linkedin.com', 'facebook.com', 't.me'
]
# map domains to clean column keys (avoid using split('.')[0] which is brittle)
DOMAIN_KEY_MAP = {
    'twitter.com': 'twitter',
    'x.com': 'x',
    'instagram.com': 'instagram',
    'twitch.tv': 'twitch',
    'discord.gg': 'discord',
    'discord.com': 'discord',
    'patreon.com': 'patreon',
    'linkedin.com': 'linkedin',
    'facebook.com': 'facebook',
    't.me': 't_me',
}

URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'


def unwrap_youtube_redirect(u: str) -> str:
    """If URL is a YouTube redirect, extract the actual target from the 'q' param."""
    try:
        if 'youtube.com/redirect' in u or 'youtube.com/redirect?' in u:
            q = parse_qs(urlparse(u).query).get('q')
            if q:
                return unquote(q[0])
    except Exception:
        pass
    return u


# Robust email/link extraction with liberal deobfuscation
COMMON_DOMAINS_NO_TLD = {'gmail', 'hotmail', 'yahoo', 'outlook', 'protonmail', 'icloud'}

# Removed _canonicalize_email and aggressive normalization here — keep extraction light-weight.

def extract_links_and_emails(text):
    """Return (urls, emails) found in text. Lightweight extraction only — no heavy canonicalization.
    Cleaning/normalization/deduplication is delegated to python_src.yt.clean_yt_contacts.
    """
    if not text:
        return [], []
    txt = text.replace('%40', '@')
    # First pass: straightforward URL and email matches
    urls = URL_RE.findall(txt)
    emails = EMAIL_RE.findall(txt)

    # Second pass: liberal deobfuscation for email-like text (but do not canonicalize)
    cleaned = txt
    subs = [
        (r'\(at\)', '@'), (r'\[at\]', '@'), (r'\s+at\s+', '@'),
        (r'\(dot\)', '.'), (r'\[dot\]', '.'), (r'\s+dot\s+', '.'),
        (r'\s+\(dot\)\s+', '.'),
    ]
    for pat, repl in subs:
        try:
            cleaned = re.sub(pat, repl, cleaned, flags=re.IGNORECASE)
        except Exception:
            continue
    cleaned = re.sub(r'\s*@\s*', '@', cleaned)
    cleaned = re.sub(r'\s*\.\s*', '.', cleaned)

    try:
        more_emails = EMAIL_RE.findall(cleaned)
        for me in more_emails:
            if me not in emails:
                emails.append(me)
    except Exception:
        pass

    # Keep lists deterministic but avoid heavy normalization — simple dedupe preserving order
    urls = list(dict.fromkeys(urls))
    emails = list(dict.fromkeys(emails))
    return urls, emails


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
                    try {
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


def extract_contacts_from_channel(channel_url, page, debug_dir=None, idx=None):
    """Open channel home URL, try to open About panel, extract header and about text and links.
    Returns (channel_name, found_dict).
    """
    found = {}
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
            channel_name = channel_name

        # Extract header preview text (quick win) before attempting About navigation
        header_text = ''
        try:
            # Try a few header-scoped selectors that often contain the short bio/preview
            hdr_selectors = [
                'ytd-description-preview-renderer',
                'yt-description-preview-view-model',
                'yt-page-header-renderer',
                '.ytDescriptionPreviewViewModelHost',
            ]
            for hs in hdr_selectors:
                try:
                    node = page.query_selector(hs)
                    if node:
                        header_text = node.inner_text() or ''
                        if header_text:
                            break
                except Exception:
                    continue
            # Also try the page-header truncated text nodes
            if not header_text:
                try:
                    parts = page.query_selector_all('truncated-text-content, .yt-truncated-text_truncated-text-content')
                    for p in parts:
                        try:
                            t = p.inner_text() or ''
                            if t:
                                header_text += (t + '\n')
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception:
            header_text = ''

        # Parse header text for links/emails
        # But first try clicking the header "more" button (the small blurb under the channel name)
        try:
            header_more = page.query_selector('button.yt-truncated-text__absolute-button, button.yt-truncated-text__more-button')
            if header_more:
                try:
                    header_more.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    header_more.click(force=True)
                    page.wait_for_timeout(700)
                    # wait briefly for the dialog/panel or about renderer to appear
                    try:
                        page.wait_for_selector('ytd-popup-container tp-yt-paper-dialog ytd-engagement-panel-section-list-renderer, ytd-about-channel-renderer #about-container', timeout=2000)
                    except Exception:
                        pass
                    # save snapshot for debugging if requested
                    if debug_dir and idx is not None:
                        try:
                            html = page.content()
                            with open(f"{debug_dir}/about_dialog_snapshot_{idx}.html", 'w', encoding='utf-8') as f:
                                f.write(html)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        if header_text:
            u_hdr, e_hdr = extract_links_and_emails(header_text)
            for uu in u_hdr:
                dom = domain_of(uu)
                matched = False
                for sd in SOCIAL_DOMAINS:
                    if sd in dom:
                        key = DOMAIN_KEY_MAP.get(sd, sd.split('.')[0])
                        found.setdefault(key, []).append(uu)
                        matched = True
                        break
                if not matched:
                    found.setdefault('website', []).append(uu)
            for ee in e_hdr:
                found.setdefault('email', []).append(ee)

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

        # After attempts, try to locate an About renderer on the page
        about_text = ''
        try:
            about_node = None
            # prefer the deep engagement-panel -> about renderer path that is commonly used
            deep_selectors = [
                'ytd-popup-container tp-yt-paper-dialog ytd-engagement-panel-section-list-renderer #content ytd-section-list-renderer #contents ytd-item-section-renderer #contents ytd-about-channel-renderer #about-container',
                'ytd-popup-container tp-yt-paper-dialog ytd-engagement-panel-section-list-renderer ytd-about-channel-renderer #about-container',
                'ytd-about-channel-renderer, ytd-channel-about-metadata-renderer, #about-container, ytd-item-section-renderer ytd-about-channel-renderer'
            ]
            for s in deep_selectors:
                try:
                    about_node = page.query_selector(s)
                    if about_node:
                        try:
                            about_node.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        break
                except Exception:
                    about_node = None

            # additional attempt: find tp-yt-paper-dialog and then query inside it for #about-container
            if not about_node:
                try:
                    dialog = page.query_selector('tp-yt-paper-dialog')
                    if dialog:
                        try:
                            inner = dialog.query_selector('#about-container')
                            if inner:
                                about_node = inner
                        except Exception:
                            pass
                except Exception:
                    pass

            if about_node:
                try:
                    # description container inside the about renderer
                    desc = about_node.query_selector('yt-attributed-string#description-container, yt-formatted-string#description, yt-attributed-string')
                    if desc:
                        about_text = desc.inner_text() or ''
                except Exception:
                    about_text = ''
                # collect explicit link anchors inside the about node
                anchors = []
                try:
                    anchors = about_node.query_selector_all('#link-list-container a, #links-section a, ytd-channel-external-link-renderer a, a[href^="http"]')
                except Exception:
                    anchors = []
            else:
                # fallback: search for link-list on whole page
                try:
                    anchors = page.query_selector_all('#link-list-container a, #links-section a, ytd-channel-external-link-renderer a, a[href^="http"]')
                except Exception:
                    anchors = []
        except Exception:
            about_text = ''
            anchors = []

        # If we didn't find anchors earlier, try to search page-wide anchors now
        try:
            # collect hrefs from anchors found
            hrefs = []
            for a in anchors:
                try:
                    h = a.get_attribute('href') or ''
                    if h:
                        h = normalize_url('https://www.youtube.com', h)
                        h = unwrap_youtube_redirect(h)
                        hrefs.append(h)
                except Exception:
                    continue
            # also mailto anchors
            try:
                mail_nodes = page.query_selector_all('a[href^="mailto:"]')
                for m in mail_nodes:
                    try:
                        h2 = m.get_attribute('href') or ''
                        if h2:
                            hrefs.append(h2)
                    except Exception:
                        continue
            except Exception:
                pass

            # add hrefs to found categorized by domain
            for u in list(dict.fromkeys(hrefs)):
                if not u:
                    continue
                if u.lower().startswith('mailto:'):
                    email = u.split('mailto:')[-1]
                    if email:
                        found.setdefault('email', []).append(email)
                    continue
                dom = domain_of(u)
                matched = False
                for sd in SOCIAL_DOMAINS:
                    if sd in dom:
                        key = DOMAIN_KEY_MAP.get(sd, sd.split('.')[0])
                        found.setdefault(key, []).append(u)
                        matched = True
                        break
                if not matched:
                    found.setdefault('website', []).append(u)
        except Exception:
            pass

        # parse about_text for inline links/emails
        try:
            if not about_text:
                # try to read some meta-desc fallback
                try:
                    meta_desc = page.query_selector('meta[name="description"]')
                    if meta_desc:
                        about_text = meta_desc.get_attribute('content') or ''
                except Exception:
                    about_text = about_text
            urls, emails = extract_links_and_emails(about_text)
            for u in urls:
                dom = domain_of(u)
                matched = False
                for sd in SOCIAL_DOMAINS:
                    if sd in dom:
                        key = DOMAIN_KEY_MAP.get(sd, sd.split('.')[0])
                        found.setdefault(key, []).append(u)
                        matched = True
                        break
                if not matched:
                    found.setdefault('website', []).append(u)
            for e in emails:
                found.setdefault('email', []).append(e)
        except Exception:
            pass

        # close any dialog/panel we opened to return DOM to stable state
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

    return channel_name, found


def extract_contacts(video_url, channel_url, page, debug_dir=None, idx=None):
    # Minimal fallback: open video and parse description/meta for links/emails
    found = {}
    try:
        page.goto(video_url, timeout=25000)
        page.wait_for_timeout(700)
        desc = ''
        try:
            el = page.query_selector('#description') or page.query_selector('yt-formatted-string.content')
            if el:
                desc = el.inner_text() or ''
        except Exception:
            try:
                meta = page.query_selector('meta[name="description"]')
                if meta:
                    desc = meta.get_attribute('content') or ''
            except Exception:
                desc = page.content()
        urls, emails = extract_links_and_emails(desc)
        for u in urls:
            dom = domain_of(u)
            matched = False
            for sd in SOCIAL_DOMAINS:
                if sd in dom:
                    key = DOMAIN_KEY_MAP.get(sd, sd.split('.')[0])
                    found.setdefault(key, []).append(u)
                    matched = True
                    break
            if not matched:
                found.setdefault('website', []).append(u)
        for e in emails:
            found.setdefault('email', []).append(e)
    except Exception:
        pass
    return found


def main():
    parser = argparse.ArgumentParser(description='Extract contacts from YouTube channel URLs')
    parser.add_argument('--input', required=True, help='Input CSV (discover output)')
    parser.add_argument('--output', required=True, help='Output CSV')
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
            video_url = (row.get('video_url') or '').strip()
            if channel_url:
                print(f'[{idx+1}/{len(rows)}] Channel: {channel_url}')
                cname, found = extract_contacts_from_channel(channel_url, page, debug_dir=args.debug_dir, idx=idx)
                out_row = dict(row)
                out_row['channel_name_extracted'] = cname
                out_row['found'] = found
                raw_out_rows.append(out_row)
            elif video_url:
                print(f'[{idx+1}/{len(rows)}] Video fallback: {video_url}')
                found = extract_contacts(video_url, row.get('channel_url'), page, debug_dir=args.debug_dir, idx=idx)
                out_row = dict(row)
                out_row['found'] = found
                raw_out_rows.append(out_row)
            else:
                print(f'[{idx+1}/{len(rows)}] Skipping malformed row: {row}')

        try:
            browser.close()
        except Exception:
            pass

    # Flatten results and build CSV fieldnames: preserve input columns, add channel_name_extracted, per-service columns, website_1..N and email_1..N
    if raw_out_rows:
        input_cols = list(rows[0].keys())
        service_keys = list(dict.fromkeys(DOMAIN_KEY_MAP.values()))  # preserve order
        # ensure 'discord' not duplicated and other services appear
        # collect max website/email counts
        max_web = 0
        max_em = 0
        for r in raw_out_rows:
            f = r.get('found', {}) or {}
            w = len(f.get('website', []))
            e = len(f.get('email', []))
            max_web = max(max_web, w)
            max_em = max(max_em, e)
            # also ensure services present in found are counted
            for k in f.keys():
                if k not in service_keys and k not in ('website', 'email'):
                    service_keys.append(k)
        # build final fieldnames
        fieldnames = input_cols + ['channel_name_extracted'] + service_keys
        for i in range(1, max_web + 1):
            fieldnames.append(f'website_{i}')
        for i in range(1, max_em + 1):
            fieldnames.append(f'email_{i}')

        final_rows = []
        for r in raw_out_rows:
            base = {k: r.get(k, '') for k in input_cols}
            base['channel_name_extracted'] = r.get('channel_name_extracted', '')
            f = r.get('found', {}) or {}
            # populate service columns with pipe-joined values
            for sk in service_keys:
                base[sk] = '|'.join(f.get(sk, [])) if f.get(sk) else ''
            # fill website_N and email_N
            websites = f.get('website', [])
            emails = f.get('email', [])
            for i in range(1, max_web + 1):
                base[f'website_{i}'] = websites[i-1] if i-1 < len(websites) else ''
            for i in range(1, max_em + 1):
                base[f'email_{i}'] = emails[i-1] if i-1 < len(emails) else ''
            final_rows.append(base)

        with open(args.output, 'w', newline='', encoding='utf-8') as fh:
            try:
                fh.write(f"# created_by: extract_contacts_from_youtube.py | {datetime.utcnow().isoformat()}Z\n")
            except Exception:
                pass
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(final_rows)
        try:
            csv_helpers.prepend_author_note(args.output, created_by='extract_contacts_from_youtube.py')
        except Exception:
            pass
        print(f'Wrote {args.output} ({len(final_rows)} rows)')
    else:
        print('No contacts extracted; no output written')


if __name__ == '__main__':
    main()
