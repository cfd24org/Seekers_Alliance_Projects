#!/usr/bin/env python3
"""
youtube_discover_and_extract.py

Discover YouTube channels for a search query, visit each channel About page
and its most recent video (optional), and extract public contact links (social,
website) and emails. Outputs rows suitable for CSV export.
"""
import argparse
import csv
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
try:
    from python_src.shared import csv_helpers
    from python_src.shared import paths as shared_paths
except Exception:
    import sys, os
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from python_src.shared import csv_helpers
    from python_src.shared import paths as shared_paths

import os

URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SOCIAL_DOMAINS = [
    'twitter.com', 'x.com', 'instagram.com', 'twitch.tv', 'discord.gg', 'discord.com',
    'patreon.com', 'linkedin.com', 'facebook.com', 't.me'
]
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'


def extract_links_and_emails(text):
    if not text:
        return [], []
    txt = text.replace('%40', '@')
    urls = URL_RE.findall(txt)
    emails = EMAIL_RE.findall(txt)
    emails = [e for e in emails if 'youtube' not in e and 'youtu.be' not in e]
    # dedupe preserving order
    return list(dict.fromkeys(urls)), list(dict.fromkeys(emails))


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


def canonical_video_url(u: str):
    try:
        p = urlparse(u)
        netloc = (p.netloc or '').lower()
        if 'youtu.be' in netloc:
            vid = p.path.lstrip('/')
            if vid:
                return f'https://www.youtube.com/watch?v={vid}'
        qs = parse_qs(p.query)
        v = qs.get('v', [None])[0]
        if v:
            return f'https://www.youtube.com/watch?v={v}'
        scheme = p.scheme or 'https'
        return urljoin(f'{scheme}://{p.netloc}', p.path)
    except Exception:
        return u


def _parse_pub_date_from_page(page):
    """Attempt to parse a publish date from meta tags or <time> element on a YouTube video page."""
    try:
        # meta[itemprop=datePublished] or meta[itemprop=uploadDate]
        el = page.query_selector('meta[itemprop="datePublished"], meta[itemprop="uploadDate"]')
        pub_date = None
        if el:
            pub_date = el.get_attribute('content') or el.get_attribute('value') or None
        if not pub_date:
            t = page.query_selector('time')
            if t:
                pub_date = t.get_attribute('datetime') or None
        if pub_date:
            try:
                # normalize and parse
                dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
                return max(0, int(delta.total_seconds() // 86400))
            except Exception:
                return ''
    except Exception:
        pass
    return ''


def _populate_curator_placeholder():
    # placeholder if you want to unify with other scripts - not used here
    pass


def scrape(args):
    """Main scraping routine. Returns list of dict rows."""
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.no_headless)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        q = (args.query or '').strip()
        if not q:
            print('Empty query')
            return results

        # Build search URL: bias to channels unless collecting videos
        if getattr(args, 'collect_videos', False):
            search_url = f"https://www.youtube.com/results?search_query={q.replace(' ', '+')}"
        else:
            search_url = f"https://www.youtube.com/results?search_query={q.replace(' ', '+')}&sp=EgIQAg%3D%3D"

        try:
            page.goto(search_url, timeout=45000)
            try:
                page.wait_for_selector('ytd-channel-renderer,ytd-video-renderer,ytd-item-section-renderer', timeout=12000)
            except Exception:
                pass
        except Exception as e:
            print('Search page failed to load:', e)

        # Give page time and scroll so dynamic anchors appear
        time.sleep(2.0)
        for _ in range(6):
            try:
                page.evaluate('window.scrollBy(0, window.innerHeight)')
            except Exception:
                pass
            time.sleep(0.6)

        # If collecting videos only, short path: gather video links + channel info
        if getattr(args, 'collect_videos', False):
            anchors = page.query_selector_all('a')
            video_links = []
            seen = set()
            for a in anchors:
                try:
                    href = (a.get_attribute('href') or '').strip()
                except Exception:
                    href = ''
                if href and '/watch' in href:
                    v = normalize_url('https://www.youtube.com', href)
                    can = canonical_video_url(v)
                    if can and can not in seen:
                        seen.add(can)
                        video_links.append(can)
            video_links = list(dict.fromkeys(video_links))[: max(1, args.max_channels)]
            print(f'Collected {len(video_links)} video links')
            rows = []
            seen_ch = set()
            for idx, vurl in enumerate(video_links):
                print(f'[{idx+1}/{len(video_links)}] Visiting video: {vurl}')
                try:
                    page.goto(vurl, timeout=30000)
                    time.sleep(1.0)
                    title = ''
                    try:
                        t_meta = page.query_selector('meta[property="og:title"]')
                        if t_meta:
                            title = t_meta.get_attribute('content') or ''
                        if not title:
                            title = page.title() or ''
                    except Exception:
                        title = page.title() or ''
                    ch_url = ''
                    ch_name = ''
                    try:
                        ch_el = page.query_selector('ytd-channel-name a, a.yt-simple-endpoint[href*="/channel/"]')
                        if ch_el:
                            ch_url = normalize_url('https://www.youtube.com', ch_el.get_attribute('href') or '')
                            ch_name = ch_el.inner_text().strip() if hasattr(ch_el, 'inner_text') else ''
                    except Exception:
                        pass
                    if ch_url and ch_url in seen_ch:
                        continue
                    if ch_url:
                        seen_ch.add(ch_url)
                    rows.append({'video_url': vurl, 'video_title': title, 'channel_url': ch_url, 'channel_name': ch_name})
                except Exception as e:
                    print('Video visit failed:', e)
            try:
                browser.close()
            except Exception:
                pass
            return rows

        # collect channel links from search results
        channel_links = []

        def _save_debug_snapshot(page, name_prefix='yt_search'):
            try:
                dbg_dir = getattr(shared_paths, 'DEBUG_DIR', os.path.join(os.path.dirname(__file__), 'debug_about_missing'))
                os.makedirs(dbg_dir, exist_ok=True)
                fname = f"{name_prefix}_{int(time.time())}.html"
                path = os.path.join(dbg_dir, fname)
                open(path, 'w', encoding='utf-8').write(page.content())
                return path
            except Exception:
                return None

        # Try a few attempts with scrolling to let dynamic content load
        try:
            max_attempts = 3
            per_attempt_scrolls = 8
            seen = set()
            for attempt in range(max_attempts):
                try:
                    # wait for elements that usually indicate channels/videos are present
                    page.wait_for_selector('ytd-channel-renderer, ytd-item-section-renderer, ytd-rich-item-renderer, ytd-video-renderer', timeout=12000)
                except Exception:
                    # continue to scrolling/fallbacks even if selector wait fails
                    pass

                # perform incremental scrolling and collect anchors
                for s in range(per_attempt_scrolls):
                    try:
                        anchors = page.query_selector_all('a')
                    except Exception:
                        anchors = []
                    for a in anchors:
                        try:
                            href = (a.get_attribute('href') or '').strip()
                        except Exception:
                            href = ''
                        if not href:
                            continue
                        # normalize and filter channel-like hrefs
                        norm = normalize_url('https://www.youtube.com', href)
                        if any(tok in norm for tok in ('/channel/', '/user/', '/c/', '/@')):
                            if norm not in seen:
                                seen.add(norm)
                                channel_links.append(norm)
                    # break early if enough collected
                    if len(channel_links) >= args.max_channels:
                        break
                    # scroll a bit to trigger dynamic load
                    try:
                        page.evaluate('window.scrollBy(0, window.innerHeight)')
                    except Exception:
                        pass
                    time.sleep(1.0)

                if len(channel_links) >= args.max_channels:
                    break

            # If still empty, try a targeted selector pass and a JS evaluate extractor
            if not channel_links:
                try:
                    # broader selectors that sometimes surface channel anchors
                    elems = page.query_selector_all(
                        'ytd-channel-renderer a[href*="/@"], ytd-channel-renderer a[href*="/channel/"], ytd-rich-item-renderer a[href*="/channel/"], a[href*="/user/"], a[href*="/c/"]'
                    )
                    for e in elems:
                        try:
                            h = e.get_attribute('href') or ''
                        except Exception:
                            h = ''
                        h2 = normalize_url('https://www.youtube.com', h)
                        if h2 and any(x in h2 for x in ('/channel/', '/user/', '/c/', '/@')) and h2 not in channel_links:
                            channel_links.append(h2)
                except Exception:
                    pass

            if not channel_links:
                try:
                    js = '''() => {
                        const sel = ['a[href*="/@"]','a[href*="/channel/"]','a[href*="/user/"]','a[href*="/c/"]'];
                        const nodes = [];
                        for (const s of sel) {
                            document.querySelectorAll(s).forEach(a=>{ if(a.href) nodes.push(a.href); });
                        }
                        return Array.from(new Set(nodes)).slice(0, 500);
                    }'''
                    hrefs = page.evaluate(js)
                    for h in hrefs:
                        try:
                            h2 = normalize_url('https://www.youtube.com', h)
                        except Exception:
                            h2 = h
                        if h2 and h2 not in channel_links:
                            channel_links.append(h2)
                except Exception:
                    pass

            # As a last resort, try extracting any @ handles or /channel/ patterns from the page HTML
            if not channel_links:
                try:
                    html = page.content()
                    # find occurrences of /@handle or /channel/IDs
                    for match in re.finditer(r'(https?://[^"\'\s>]+/(?:@[-A-Za-z0-9_]+|channel/[-A-Za-z0-9_]+|user/[-A-Za-z0-9_]+|c/[-A-Za-z0-9_]+))', html):
                        h = match.group(1)
                        h2 = normalize_url('https://www.youtube.com', h)
                        if h2 not in channel_links:
                            channel_links.append(h2)
                except Exception:
                    pass

            # If still nothing, save debug snapshot for inspection
            if not channel_links:
                print('No channel links found on search page after retries — saving debug snapshot')
                _save_debug_snapshot(page, name_prefix='yt_search_no_channels')

        except Exception as e:
            print('Error collecting channel links:', e)

        print(f"Found {len(channel_links)} channel links on search page")
        channel_links = channel_links[: max(1, args.max_channels)]

        # Visit each channel and extract about + most recent video info
        for idx, ch_url in enumerate(channel_links):
            print(f'[{idx+1}/{len(channel_links)}] Visiting channel: {ch_url}')
            channel_name = ''
            found = {}
            video_url = ''
            video_title = ''
            video_days = ''
            bio_text = ''
            try:
                page.goto(ch_url, timeout=30000)
                time.sleep(1.0)
                # channel name
                try:
                    meta = page.query_selector('meta[property="og:title"]')
                    if meta:
                        channel_name = meta.get_attribute('content') or ''
                except Exception:
                    pass

                # visit about page
                about_href = None
                try:
                    about_el = page.query_selector('tp-yt-paper-tab[role="tab"] a[href*="/about"], a[href*="/about/"]')
                    if about_el:
                        about_href = about_el.get_attribute('href')
                except Exception:
                    pass
                if not about_href:
                    about_href = normalize_url(ch_url, '/about')

                try:
                    page.goto(about_href, timeout=20000)
                    time.sleep(1.0)
                    # try to get a bio/description
                    try:
                        bio_el = page.query_selector('#description')
                        if bio_el:
                            bio_text = bio_el.inner_text() or ''
                        else:
                            meta_desc = page.query_selector('meta[name="description"]')
                            bio_text = (meta_desc.get_attribute('content') if meta_desc else '') or ''
                    except Exception:
                        bio_text = ''
                    urls, emails = extract_links_and_emails(page.content())
                    for u in urls:
                        dom = urlparse(u).netloc.lower()
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
                except Exception:
                    pass

                # find most recent video: click Videos tab then pick first video
                try:
                    btn = None
                    tab_btns = page.query_selector_all('tp-yt-paper-tab')
                    for tb in tab_btns:
                        try:
                            txt = tb.inner_text().strip().lower()
                            if 'videos' in txt:
                                btn = tb
                                break
                        except Exception:
                            continue
                    if btn:
                        try:
                            btn.click()
                            page.wait_for_selector('ytd-grid-video-renderer,ytd-rich-grid-media', timeout=8000)
                            time.sleep(0.8)
                        except Exception:
                            pass
                    vlink = None
                    for sel in ('ytd-grid-video-renderer a#thumbnail', 'ytd-grid-video-renderer a.yt-simple-endpoint', 'ytd-rich-item-renderer a#video-title', 'a#video-title'):
                        try:
                            el = page.query_selector(sel)
                            if el:
                                vlink = el.get_attribute('href') or ''
                                break
                        except Exception:
                            continue
                    if vlink:
                        video_url = normalize_url('https://www.youtube.com', vlink)
                        try:
                            page.goto(video_url, timeout=30000)
                            time.sleep(1.0)
                            try:
                                tmeta = page.query_selector('meta[property="og:title"]')
                                if tmeta:
                                    video_title = tmeta.get_attribute('content') or ''
                                if not video_title:
                                    video_title = page.title() or ''
                            except Exception:
                                video_title = page.title() or ''
                            days = _parse_pub_date_from_page(page)
                            video_days = str(days) if days != '' else ''
                        except Exception:
                            pass
                except Exception:
                    pass

                # optionally visit video description for extra links/emails
                if args.visit_videos and video_url:
                    try:
                        page.goto(video_url, timeout=30000)
                        try:
                            page.wait_for_selector('#description', timeout=8000)
                        except Exception:
                            pass
                        desc_html = ''
                        try:
                            desc_el = page.query_selector('#description')
                            if desc_el:
                                desc_html = desc_el.inner_text() or ''
                        except Exception:
                            desc_html = page.content()
                        u2, e2 = extract_links_and_emails(desc_html)
                        for uu in u2:
                            dom = urlparse(uu).netloc.lower()
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
                            if ee not in found.get('email', []):
                                found.setdefault('email', []).append(ee)
                    except Exception:
                        pass

            except Exception as e:
                print('Error visiting channel:', e)

            # dedupe lists
            for k, v in list(found.items()):
                if isinstance(v, list):
                    found[k] = list(dict.fromkeys(v))

            contact_parts = []
            for k, v in found.items():
                contact_parts.append(f"{k}={'|'.join(v)}")
            contact_str = ';'.join(contact_parts)

            results.append({
                'channel_name': channel_name or '',
                'channel_url': ch_url,
                'bio': bio_text,
                'video_url': video_url,
                'video_title': video_title,
                'video_days_ago': video_days,
                'found_contacts': contact_str,
                'email': (found.get('email') or [''])[0] if found.get('email') else ''
            })

        try:
            browser.close()
        except Exception:
            pass

    return results


def write_csv(path, rows):
    if not rows:
        print('No rows to write')
        return
    fieldnames = list(rows[0].keys())
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        try:
            fh.write(f"# created_by: youtube_discover_and_extract.py | {datetime.utcnow().isoformat()}Z\n")
        except Exception:
            pass
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    try:
        csv_helpers.prepend_author_note(path, created_by='youtube_discover_and_extract.py')
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description='Discover YouTube channels and extract contacts from their most recent video/about')
    parser.add_argument('--query', required=True, help='Search query (genre/topic)')
    parser.add_argument('--max-channels', type=int, default=20)
    parser.add_argument('--visit-videos', action='store_true')
    parser.add_argument('--no-headless', action='store_true')
    parser.add_argument('--output', help='Output CSV path')
    parser.add_argument('--collect-videos', action='store_true', help='Collect video links, titles, and channel links from search results')
    args = parser.parse_args()

    out = args.output or (f"youtube_contacts_{int(time.time())}.csv")
    rows = scrape(args)
    write_csv(out, rows)
    print(f'Wrote {out} with {len(rows)} channel rows')


if __name__ == '__main__':
    main()
