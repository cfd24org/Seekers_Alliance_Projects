#!/usr/bin/env python3
"""
steam_search_scrape.py

Simple Playwright-based scraper to search the Steam store for one or more queries
and extract the result rows (name + id). Outputs CSV with columns:
  name, id, id_type, query

Usage examples:
  python steam_search_scrape.py --query "roguelike" --output steam_games.csv
  python steam_search_scrape.py --queries-file queries.txt --pages 2

Notes:
- Requires playwright and browsers (`python -m playwright install chromium`).
- By default only collects the first page of results; use --pages to collect more pages.
"""
import argparse
import csv
import re
import time
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'

SEARCH_URL = 'https://store.steampowered.com/search/?term={query}&page={page}'

ID_PATTERNS = [
    (r'/app/(\d+)', 'app'),
    (r'/sub/(\d+)', 'sub'),
    (r'/bundle/(\d+)', 'bundle'),
]


def extract_id_from_href(href: str):
    if not href:
        return None, 'unknown'
    for pat, t in ID_PATTERNS:
        m = re.search(pat, href)
        if m:
            return m.group(1), t
    return None, 'unknown'


def scrape_queries(queries, pages=1, headless=True, debug_dir=None, follow_details=True):
    results = []
    seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        for q in queries:
            for pg in range(1, pages + 1):
                url = SEARCH_URL.format(query=quote_plus(q), page=pg)
                print(f"Searching: '{q}' page {pg} -> {url}")
                try:
                    page.goto(url, timeout=30000)
                    # Wait for results container
                    try:
                        page.wait_for_selector('#search_resultsRows', timeout=5000)
                    except Exception:
                        # maybe no results
                        pass
                    time.sleep(0.5)
                    anchors = page.query_selector_all('#search_resultsRows a')
                    if not anchors:
                        # Save debug snapshot if requested
                        if debug_dir:
                            try:
                                html = page.content()
                                open(f"{debug_dir}/steam_search_{q.replace(' ', '_')}_p{pg}.html", 'w', encoding='utf-8').write(html)
                            except Exception:
                                pass
                    for a in anchors:
                        try:
                            href = a.get_attribute('href') or ''
                            title_el = a.query_selector('.title')
                            name = (title_el.inner_text().strip() if title_el else a.inner_text().strip())
                            appid, id_type = extract_id_from_href(href)
                            key = (appid, id_type) if appid else (href, 'href')
                            if key in seen:
                                continue
                            seen.add(key)
                            # default empty curator info; will be populated later if follow_details
                            results.append({'name': name, 'id': appid or '', 'id_type': id_type, 'query': q, 'href': href, 'curator_review_count': '', 'curator_list_url': ''})
                        except Exception:
                            continue
                except Exception as e:
                    print(f"Error loading search page for '{q}' page {pg}: {e}")
        # Optionally visit each game's page to extract curator counts
        if follow_details:
            print(f"Visiting {len(results)} game pages to collect curator counts...")
            for idx, row in enumerate(results):
                href = row.get('href')
                if not href:
                    continue
                try:
                    # reuse the page to avoid too many open tabs
                    page.goto(href, timeout=30000)
                    time.sleep(0.6)
                    # try known selectors first
                    curator_count = None
                    curator_url = None
                    try:
                        # block that often contains the curator info
                        block = page.query_selector('.steam_curators_block .no_curators_followed') or page.query_selector('.steam_curators_block')
                        text = block.inner_text() if block else ''
                    except Exception:
                        text = ''
                    if not text:
                        # fallback: look for any element containing 'Curators have reviewed'
                        try:
                            els = page.query_selector_all('div')
                            for el in els:
                                try:
                                    t = el.inner_text()
                                    if t and 'Curators have reviewed' in t:
                                        text = t
                                        break
                                except Exception:
                                    continue
                        except Exception:
                            text = ''
                    # regex to find number of curators
                    if text:
                        m = re.search(r"([0-9,]+)\s+Curators?\s+have\s+reviewed", text)
                        if m:
                            curator_count = int(m.group(1).replace(',', ''))
                        else:
                            # looser match: '91 Curators' or '91 Curators have'
                            m2 = re.search(r"([0-9,]+)\s+Curators?", text)
                            if m2:
                                curator_count = int(m2.group(1).replace(',', ''))
                    # also try to find direct curator list URL
                    try:
                        link_el = page.query_selector('a[href*="curators/curatorsreviewing"]')
                        if link_el:
                            curator_url = link_el.get_attribute('href')
                    except Exception:
                        curator_url = None
                    # final fallback: search raw html for curatorsreviewing link
                    if not curator_url:
                        html = page.content()
                        m3 = re.search(r'(https?://store\.steampowered\.com/curators/curatorsreviewing/\?appid=\d+[^"\s]*)', html)
                        if m3:
                            curator_url = m3.group(1)
                        # try to find count in raw html as well
                        if curator_count is None:
                            m4 = re.search(r'>([0-9,]+)\s+Curators?\s+have\s+reviewed<', html)
                            if m4:
                                curator_count = int(m4.group(1).replace(',', ''))
                    if curator_count is not None:
                        row['curator_review_count'] = str(curator_count)
                    if curator_url:
                        row['curator_list_url'] = curator_url
                except Exception as e:
                    print(f"Failed to fetch details for {href}: {e}")
                    if debug_dir:
                        try:
                            open(f"{debug_dir}/steam_detail_fail_{idx}.html", 'w', encoding='utf-8').write(page.content())
                        except Exception:
                            pass
        try:
            browser.close()
        except Exception:
            pass
    return results


def main():
    parser = argparse.ArgumentParser(description='Scrape Steam search results for queries')
    parser.add_argument('--query', action='append', help='Search query (can be used multiple times)')
    parser.add_argument('--queries-file', help='File with one query per line')
    parser.add_argument('--output', default='steam_games.csv', help='Output CSV file')
    parser.add_argument('--pages', type=int, default=1, help='Number of search pages to collect per query')
    parser.add_argument('--no-headless', action='store_true', help='Run browser with UI for debugging')
    parser.add_argument('--debug-dir', default=None, help='Directory to save HTML snapshots when results are empty')
    parser.add_argument('--no-details', action='store_true', help='Do not visit individual game pages to collect curator counts')
    args = parser.parse_args()

    queries = []
    if args.query:
        queries.extend(args.query)
    if args.queries_file:
        with open(args.queries_file, encoding='utf-8') as fh:
            for line in fh:
                t = line.strip()
                if t:
                    queries.append(t)
    if not queries:
        parser.error('Provide at least one --query or --queries-file')

    rows = scrape_queries(queries, pages=args.pages, headless=not args.no_headless, debug_dir=args.debug_dir, follow_details=not args.no_details)
    if not rows:
        print('No results found')
    fieldnames = ['name', 'id', 'id_type', 'query', 'href', 'curator_review_count', 'curator_list_url']
    with open(args.output, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f'Wrote {len(rows)} rows to {args.output}')


if __name__ == '__main__':
    main()
