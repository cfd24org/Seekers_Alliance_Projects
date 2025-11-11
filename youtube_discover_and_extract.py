#!/usr/bin/env python3
"""
youtube_discover_and_extract.py

Discover YouTube channels for a search query (genre/topic), visit each
channel, open the most recent video, and extract public contact links (twitter,
instagram, discord, websites) and emails from the channel/about and the most
recent video's description.

Usage:
  python youtube_discover_and_extract.py --query "dice roguelike" --max-channels 20 --visit-videos --output youtube_contacts.csv

Requirements: playwright (and browsers installed via `python -m playwright install`)

Notes:
- This uses Playwright for reliable page rendering. Set --no-headless to watch.
- Results written as CSV with columns: channel_name, channel_url, video_url, found_contacts
"""
import argparse
import csv
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SOCIAL_DOMAINS = ['twitter.com', 'x.com', 'instagram.com', 'twitch.tv', 'discord.gg', 'discord.com', 'patreon.com', 'linkedin.com', 'facebook.com', 't.me']
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'


def extract_links_and_emails(text):
    if not text:
        return [], []
    txt = text.replace('%40', '@')
    urls = URL_RE.findall(txt)
    emails = EMAIL_RE.findall(txt)
    # filter youtube-like false positives in emails
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


def canonical_video_url(u: str):
    """Return canonical video URL (https://www.youtube.com/watch?v=ID) when possible."""
    try:
        p = urlparse(u)
        netloc = (p.netloc or '').lower()
        if 'youtu.be' in netloc:
            vid = p.path.lstrip('/')
            if vid:
                return f'https://www.youtube.com/watch?v={vid}'
        from urllib.parse import parse_qs
        qs = parse_qs(p.query)
        v = qs.get('v', [None])[0]
        if v:
            return f'https://www.youtube.com/watch?v={v}'
        scheme = p.scheme or 'https'
        return urljoin(f'{scheme}://{p.netloc}', p.path)
    except Exception:
        return u


def scrape(args):
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.no_headless)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        search_q = args.query.strip()
        if not search_q:
            print('Empty query')
            return results
        # Use normal search for videos if collecting videos
        if getattr(args, 'collect_videos', False):
            search_url = f"https://www.youtube.com/results?search_query={search_q.replace(' ', '+')}"
        else:
            search_url = f"https://www.youtube.com/results?search_query={search_q.replace(' ', '+')}&sp=EgIQAg%3D%3D"

        try:
            page.goto(search_url, timeout=30000)
            page.wait_for_selector('ytd-video-renderer,a#video-title', timeout=8000)
        except PlaywrightTimeoutError:
            print('Search page load timeout')

        # If requested, collect video links, titles, and channel links from the search results and return early
        if getattr(args, 'collect_videos', False):
            video_links = []
            seen = set()
            max_scrolls = 15
            for i in range(max_scrolls):
                anchors = page.query_selector_all('a')
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
                if len(video_links) >= args.max_channels:
                    break
                try:
                    page.evaluate('window.scrollBy(0, window.innerHeight)')
                except Exception:
                    pass
                time.sleep(1.0)
            video_links = list(dict.fromkeys(video_links))[: max(1, args.max_channels)]
            print(f'Collected {len(video_links)} video links')
            # For each video, fetch title and channel link
            rows = []
            seen_channels = set()
            for idx, vurl in enumerate(video_links):
                print(f'[{idx+1}/{len(video_links)}] Visiting video: {vurl}')
                try:
                    page.goto(vurl, timeout=20000)
                    time.sleep(1.2)
                    # Title
                    title = ''
                    try:
                        title_el = page.query_selector('h1.title, h1.ytd-watch-metadata, meta[name="title"], meta[property="og:title"]')
                        if title_el:
                            title = title_el.inner_text() if hasattr(title_el, 'inner_text') else (title_el.get_attribute('content') or '')
                        if not title:
                            title = page.title()
                    except Exception:
                        pass
                    # Channel link and name
                    ch_url, ch_name = '', ''
                    try:
                        ch_el = page.query_selector('ytd-channel-name a, a.yt-simple-endpoint.yt-formatted-string[href*="/channel/"]')
                        if ch_el:
                            ch_url = ch_el.get_attribute('href') or ''
                            ch_url = normalize_url('https://www.youtube.com', ch_url)
                            ch_name = ch_el.inner_text().strip() if hasattr(ch_el, 'inner_text') else ''
                    except Exception:
                        pass
                    # Deduplicate by channel_url
                    if ch_url and ch_url in seen_channels:
                        continue
                    if ch_url:
                        seen_channels.add(ch_url)
                    rows.append({
                        'video_url': vurl,
                        'video_title': title,
                        'channel_url': ch_url,
                        'channel_name': ch_name
                    })
                except Exception as e:
                    print(f'Error visiting video: {e}')
            try:
                browser.close()
            except Exception:
                pass
            return rows

        # build YouTube search for channels
        search_q = args.query.strip()
        if not search_q:
            print('Empty query')
            return results
        search_url = f"https://www.youtube.com/results?search_query={search_q.replace(' ', '+')}&sp=EgIQAg%3D%3D"
        # the sp param above biases to channels; may not be necessary but helps

        try:
            page.goto(search_url, timeout=30000)
            page.wait_for_selector('ytd-channel-renderer,ytd-item-section-renderer', timeout=8000)
        except PlaywrightTimeoutError:
            print('Search page load timeout')

        # collect channel links from search results
        channel_links = []
        try:
            # channel renderers contain an 'a' linking to the channel
            elems = page.query_selector_all('ytd-channel-renderer a#main-link, ytd-channel-renderer a.ytd-channel-renderer')
            for e in elems:
                href = e.get_attribute('href') or ''
                href = normalize_url('https://www.youtube.com', href)
                if '/channel/' in href or '/user/' in href or '/c/' in href:
                    if href not in channel_links:
                        channel_links.append(href)
        except Exception:
            pass

        # fallback: look for links with /channel/ anywhere
        if not channel_links:
            try:
                anchors = page.query_selector_all('a')
                for a in anchors:
                    h = a.get_attribute('href') or ''
                    if '/channel/' in h or '/user/' in h or '/c/' in h:
                        h2 = normalize_url('https://www.youtube.com', h)
                        if h2 not in channel_links:
                            channel_links.append(h2)
            except Exception:
                pass

        channel_links = channel_links[: max(1, args.max_channels)]

        for idx, ch_url in enumerate(channel_links):
            print(f'[{idx+1}/{len(channel_links)}] Visiting channel: {ch_url}')
            channel_name = ''
            found = {}
            video_url = ''
            try:
                page.goto(ch_url, timeout=30000)
                # try to get channel name
                try:
                    title_el = page.query_selector('meta[property="og:title"]')
                    if title_el:
                        channel_name = title_el.get_attribute('content') or ''
                except Exception:
                    pass

                # Heuristic: prefer creator channels (handles or non-official names). Skip obvious platform/official channels.
                is_creator = False
                try:
                    # look for canonical URL or og:url which may contain the @handle
                    can_el = page.query_selector('link[rel="canonical"]')
                    og_el = page.query_selector('meta[property="og:url"]')
                    can_url = (can_el.get_attribute('href') if can_el else None) or (og_el.get_attribute('content') if og_el else '')
                    if can_url and '/@' in can_url:
                        is_creator = True
                except Exception:
                    pass

                # If no handle in canonical, use simple name heuristics to skip platform pages
                if not is_creator:
                    low = (channel_name or '').lower()
                    skip_tokens = ('youtube', 'official', 'help', 'support', 'kids', 'ads', 'studio', 'music', 'artists', 'tv')
                    if low and not any(tok in low for tok in skip_tokens):
                        is_creator = True

                # Also treat URLs containing an @ handle as creators
                if not is_creator and '/@' in ch_url:
                    is_creator = True

                if not is_creator:
                    print(f"Skipping non-creator channel: {ch_url} (name='{channel_name}')")
                    continue

                # visit About page for more links
                about_href = None
                try:
                    # look for the About tab link
                    about_el = page.query_selector('tp-yt-paper-tab[role="tab"] a[href*="/about"], a[href*="/about/"]')
                    if about_el:
                        about_href = about_el.get_attribute('href')
                except Exception:
                    pass

                if not about_href:
                    # try canonical about URL
                    about_href = normalize_url(ch_url, '/about')

                # fetch about page
                try:
                    page.goto(about_href, timeout=20000)
                    time.sleep(1)
                    html = page.content()
                    urls, emails = extract_links_and_emails(html)
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
                except Exception:
                    pass

                # find most recent video url: go to Videos tab and take first video
                try:
                    videos_tab = None
                    # click Videos tab
                    # selector for tab buttons
                    tab_btns = page.query_selector_all('tp-yt-paper-tab')
                    for tb in tab_btns:
                        try:
                            txt = tb.inner_text().strip().lower()
                            if 'videos' in txt:
                                btn = tb
                                break
                        except Exception:
                            continue
                    else:
                        btn = None
                    if btn:
                        try:
                            btn.click()
                            page.wait_for_selector('ytd-grid-video-renderer,ytd-rich-grid-media', timeout=8000)
                        except Exception:
                            pass
                    # now find first video link
                    # check common selectors
                    vlink = None
                    for sel in ('ytd-grid-video-renderer a#thumbnail', 'ytd-grid-video-renderer a.yt-simple-endpoint', 'ytd-rich-item-renderer a#video-title'):
                        try:
                            el = page.query_selector(sel)
                            if el:
                                vlink = el.get_attribute('href')
                                break
                        except Exception:
                            continue
                    if vlink:
                        video_url = normalize_url('https://www.youtube.com', vlink)
                    else:
                        # try to find first video on channel home
                        el2 = page.query_selector('a#video-title')
                        if el2:
                            vlink = el2.get_attribute('href')
                            video_url = normalize_url('https://www.youtube.com', vlink)
                except Exception:
                    pass

                # optionally visit video and extract description links
                if args.visit_videos and video_url:
                    try:
                        page.goto(video_url, timeout=30000)
                        page.wait_for_selector('#description', timeout=8000)
                        time.sleep(0.5)
                        desc_html = ''
                        try:
                            desc_el = page.query_selector('#description')
                            if desc_el:
                                desc_html = desc_el.inner_text() or ''
                        except Exception:
                            desc_html = page.content()
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
                'video_url': video_url,
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
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
