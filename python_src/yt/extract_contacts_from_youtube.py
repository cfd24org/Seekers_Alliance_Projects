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
    'patreon.com', 'linkedin.com', 'facebook.com', 't.me', 'youtube.com'
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
    'youtube.com': 'youtube',
}

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
            channel_name = channel_name

        # Extract the channel description
        description = ''
        try:
            # Check if "Read more" button exists and click it
            _expand_truncated_description(page)

            # Locate the description container using the full path
            desc_container = page.query_selector(
                'html > body > ytd-app > ytd-popup-container.style-scope.ytd-app > tp-yt-paper-dialog.style-scope.ytd-popup-container > ytd-engagement-panel-section-list-renderer.style-scope.ytd-popup-container > div#content > ytd-section-list-renderer.style-scope.ytd-engagement-panel-section-list-renderer > div#contents > ytd-item-section-renderer.style-scope.ytd-section-list-renderer > div#contents > ytd-about-channel-renderer.style-scope.ytd-item-section-renderer > div#about-container > yt-attributed-string#description-container > span.yt-core-attributed-string.yt-core-attributed-string--white-space-pre-wrap'
            )
            if desc_container:
                description = desc_container.inner_text() or ''
        except Exception:
            description = ''

        # Add the description to the found dictionary
        if description:
            found['description'] = description

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

        # NOTE: Skip parsing header preview text for links/emails. This often picks up unrelated
        # links (thumbnails, suggested channels, etc). We only want links from the About
        # renderer's explicit link list and emails in the channel description (about_text).
        # ...header preview parsing intentionally omitted...

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
                    if (dialog):
                        try:
                            inner = dialog.query_selector('#about-container')
                            if (inner):
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
                # If no About renderer is present, do not fall back to scanning the whole page
                # for anchors — that picks up unrelated links. Keep anchors empty.
                anchors = []

            # collect hrefs from anchors found
            hrefs = []
            def canonical_same(a,b):
                try:
                    if not a or not b:
                        return False
                    pa = urlparse(a)
                    pb = urlparse(b)
                    na = (pa.netloc or '') + (pa.path or '')
                    nb = (pb.netloc or '') + (pb.path or '')
                    # strip trailing slashes and common www prefixes
                    for s in ('www.', 'm.'):
                        na = na.replace(s, '')
                        nb = nb.replace(s, '')
                    na = na.rstrip('/')
                    nb = nb.rstrip('/')
                    return na.lower() == nb.lower()
                except Exception:
                    return False

            for a in anchors:
                try:
                    h = a.get_attribute('href') or ''
                    if not h:
                        continue
                    h = normalize_url('https://www.youtube.com', h)
                    # unwrap YouTube redirect if present
                    h = unwrap_youtube_redirect(h)

                    # Unwrap Google sign-in continuations that point to YouTube (common localized links)
                    try:
                        if 'accounts.google.com' in h:
                            parsed = urlparse(h)
                            q = parse_qs(parsed.query)
                            cont = q.get('continue') or q.get('next') or q.get('q')
                            if cont:
                                cand = unquote(cont[0])
                                if 'youtube.com' in cand:
                                    h = cand
                    except Exception:
                        pass

                    # normalize youtube handle links (e.g. youtube.com/@handle) to a consistent http(s) form
                    if h.startswith('youtube.com'):
                        h = 'https://' + h

                    # Skip if this is basically the same as the provided channel_url to avoid duplicates
                    try:
                        if channel_url and canonical_same(h, channel_url):
                            continue
                    except Exception:
                        pass

                    hrefs.append(h)
                except Exception:
                    continue

            # Collect explicit link-section anchors only. Do NOT classify into social/website/email here.
            # We skip mailto links entirely (email extraction is handled by a downstream script).
            try:
                uniq = list(dict.fromkeys(hrefs))
                for u in uniq:
                    if not u:
                        continue
                    if u.lower().startswith('mailto:'):
                        # skip mailto here
                        continue
                    found.setdefault('links', []).append(u)
            except Exception:
                pass
        except Exception:
            pass

        # NOTE: Removed last-resort raw HTML scanning. Scanning full page HTML or fallback
        # about-container content tends to collect many unrelated links. We only extract
        # from the explicit About link list (as 'links') and the channel description (about_text).

        # Attempt to extract specific fields from the About renderer: description span text, country, subscribers
        try:
            if about_node:
                # Prefer the inner span inside the description container which preserves whitespace/newlines
                try:
                    span = about_node.query_selector('yt-attributed-string#description-container span.yt-core-attributed-string, yt-attributed-string#description-container span')
                    desc_span = ''
                    if span:
                        desc_span = (span.inner_text() or '').strip()
                    else:
                        desc_span = about_text.strip() if about_text else ''
                    if desc_span:
                        found.setdefault('description', []).append(desc_span)
                except Exception:
                    pass

                # Country: look for the row that contains the privacy_public icon and take the second cell
                try:
                    country = about_node.evaluate("""(node)=> {
                        const rows = node.querySelectorAll('#additional-info-container tr');
                        for (const r of rows) {
                            try {
                                if ((r.innerHTML||'').includes('privacy_public')) {
                                    const tds = r.querySelectorAll('td');
                                    if (tds.length>1) return (tds[1].innerText||'').trim();
                                }
                            } catch(e) { continue; }
                        }
                        return null;
                    }""")
                    if country:
                        found.setdefault('country', []).append(country)
                except Exception:
                    pass

                # Subscribers: find any table cell mentioning "subscribers" and return the sibling cell (the count)
                try:
                    subs = about_node.evaluate("""(node)=> {
                        const rows = node.querySelectorAll('#additional-info-container tr');
                        for (const r of rows) {
                            try {
                                const tds = r.querySelectorAll('td');
                                for (const td of tds) {
                                    const txt = (td.innerText||'').toLowerCase();
                                    if (txt.includes('subscribers')) {
                                        if (tds.length>1) return (tds[1].innerText||'').trim();
                                        return txt;
                                    }
                                }
                            } catch(e) { continue; }
                        }
                        return null;
                    }""")
                    if subs:
                        m = re.search(r'([\d\.,]+\s*(?:[MKmk])?)', subs)
                        val = m.group(1).strip() if m else subs
                        if val:
                            found.setdefault('subscribers', []).append(val)
                except Exception:
                    pass
        except Exception:
            pass

        # Ensure we capture the raw description text so the downstream link/email normalizer
        # can parse it. Do not attempt to extract links/emails here.
        try:
            if not about_text:
                try:
                    meta_desc = page.query_selector('meta[name="description"]')
                    if meta_desc:
                        about_text = meta_desc.get_attribute('content') or ''
                except Exception:
                    about_text = about_text
            if about_text and not found.get('description'):
                try:
                    txt = about_text.strip()
                    if txt:
                        found.setdefault('description', []).append(txt)
                except Exception:
                    pass
        except Exception:
            pass

        # dedupe found lists before returning
        try:
            for k in list(found.keys()):
                try:
                    found[k] = list(dict.fromkeys(found.get(k) or []))
                except Exception:
                    continue
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
        try:
            dismiss_youtube_consent(page)
        except Exception:
            pass
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

    # Flatten results and build CSV fieldnames: preserve input columns, add channel_name_extracted,
    # and explicit columns we want from this extractor: description, links, country, subscribers.
    if raw_out_rows:
        input_cols = list(rows[0].keys())
        fieldnames = input_cols + ['channel_name_extracted', 'description', 'links', 'country', 'subscribers']

        final_rows = []
        for r in raw_out_rows:
            base = {k: r.get(k, '') for k in input_cols}
            base['channel_name_extracted'] = r.get('channel_name_extracted', '')
            f = r.get('found', {}) or {}
            # description: join multiple description entries with '\n\n'
            base['description'] = '\n\n'.join(f.get('description', [])) if f.get('description') else ''
            # links: pipe-joined explicit link-section anchors (downstream script will normalize)
            base['links'] = '|'.join(f.get('links', [])) if f.get('links') else ''
            base['country'] = '|'.join(f.get('country', [])) if f.get('country') else ''
            base['subscribers'] = '|'.join(f.get('subscribers', [])) if f.get('subscribers') else ''
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
