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


def _populate_curator_details(page, results, debug_dir=None):
    """Given a Playwright `page` and a list of result rows (dicts with 'href'), visit each href
    and populate 'curator_review_count' and 'curator_list_url' in-place.
    """
    print(f"Visiting {len(results)} game pages to collect curator counts...")
    for idx, row in enumerate(results):
        href = row.get('href')
        if not href:
            continue
        try:
            page.goto(href, timeout=30000)
            time.sleep(0.6)
            curator_count = None
            curator_url = None
            try:
                block = page.query_selector('.steam_curators_block .no_curators_followed') or page.query_selector('.steam_curators_block')
                text = block.inner_text() if block else ''
            except Exception:
                text = ''
            if not text:
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
            if text:
                m = re.search(r"([0-9,]+)\s+Curators?\s+have\s+reviewed", text)
                if m:
                    curator_count = int(m.group(1).replace(',', ''))
                else:
                    m2 = re.search(r"([0-9,]+)\s+Curators?", text)
                    if m2:
                        curator_count = int(m2.group(1).replace(',', ''))
            try:
                link_el = page.query_selector('a[href*="curators/curatorsreviewing"]')
                if link_el:
                    curator_url = link_el.get_attribute('href')
            except Exception:
                curator_url = None
            if not curator_url:
                html = page.content()
                m3 = re.search(r'(https?://store\.steampowered\.com/curators/curatorsreviewing/\?appid=\d+[^"\s]*)', html)
                if m3:
                    curator_url = m3.group(1)
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
            _populate_curator_details(page, results, debug_dir)
        try:
            browser.close()
        except Exception:
            pass
    return results


def scrape_top_charts(count=200, headless=True, debug_dir=None, follow_details=False):
    """Scrape the Steam "Most Played" charts page and return up to `count` rows.
    Returns the same row dicts as scrape_queries so output writing is shared.

    This function tries multiple strategies to collect the top chart links:
    - Prefer explicit `.chart_row` entries and the anchor inside each row
    - Fallback to selecting any anchor that looks like a store item
    - If selectors fail (dynamic content), run a page.evaluate JS snippet that returns up to `count` {href,name} objects

    After collecting links we build canonical store page URLs (e.g. /app/<id>/) and
    optionally visit each game's page (via the shared helper) to extract curator info.
    """
    results = []
    seen = set()
    charts_url = 'https://store.steampowered.com/charts/mostplayed'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        print(f"Loading Steam charts page: {charts_url}")
        try:
            page.goto(charts_url, timeout=45000)
            # wait a bit more for dynamic content on the charts page
            try:
                page.wait_for_selector('.chart_row, a[href*="/app/"]', timeout=10000)
            except Exception:
                pass
            time.sleep(0.8)

            # Prefer selecting explicit chart rows if present
            rows = page.query_selector_all('.chart_row')
            anchors = []
            if rows:
                for r in rows:
                    try:
                        a = r.query_selector('a[href*="/app/"], a[href*="/sub/"], a[href*="/bundle/"]')
                        if a:
                            anchors.append(a)
                    except Exception:
                        continue
            else:
                # fallback: grab any anchor that looks like a store item
                anchors = page.query_selector_all('a[href*="/app/"], a[href*="/sub/"], a[href*="/bundle/"]')

            # If no anchors found via selector (dynamic content), try a JS evaluation fallback
            if not anchors:
                try:
                    js_func = ("(count) => {"
                        "  const out = [];"
                        "  const rows = document.querySelectorAll('.chart_row');"
                        "  let nodes = [];"
                        "  if (rows && rows.length) { rows.forEach(r => { const a = r.querySelector('a[href*=\"/app/\"],a[href*=\"/sub/\"],a[href*=\"/bundle/\"]'); if (a) nodes.push(a); }); }"
                        "  if (nodes.length === 0) nodes = Array.from(document.querySelectorAll('a[href*=\"/app/\"],a[href*=\"/sub/\"],a[href*=\"/bundle/\"]'));"
                        "  for (const a of nodes.slice(0, count)) {"
                        "    try {"
                        "      const href = a.href || '';"
                        "      let name = '';"
                        "      const selectors = ['.chart_row_name .title', '.chart_row_name', '.chart_name .title', '.chart_name', '.title', 'span.title'];"
                        "      const row = a.closest('.chart_row');"
                        "      for (const sel of selectors) { let f = row ? row.querySelector(sel) : null; if (!f) f = a.querySelector(sel); if (f && (f.innerText || f.alt) && (f.innerText || f.alt).trim()) { name = (f.innerText || f.alt).trim(); break; } }"
                        "      if (!name) { const img = a.querySelector('img'); if (img && img.alt && img.alt.trim()) name = img.alt.trim(); }"
                        "      if (!name) { const txt = a.innerText || ''; for (const line of txt.split('\n')) { const s = line.trim(); if (s) { name = s; break; } } }"
                        "      out.push({href, name});"
                        "    } catch (e) { continue; }"
                        "  }"
                        "  return out;"
                        "}")
                    items = page.evaluate(js_func, count)
                    if items:
                        anchors = []
                        for it in items:
                            anchors.append({'href': it.get('href', ''), 'name': it.get('name', '')})
                except Exception:
                    anchors = []

            if not anchors and debug_dir:
                try:
                    open(f"{debug_dir}/steam_charts.html", 'w', encoding='utf-8').write(page.content())
                except Exception:
                    pass

            print(f"Found {len(anchors)} raw anchors/items on charts page (will dedupe and limit to {count})")

            for a in anchors:
                if len(results) >= count:
                    break
                try:
                    # 'a' might be an ElementHandle or a dict produced by JS fallback
                    if isinstance(a, dict):
                        href = a.get('href', '')
                        name = a.get('name', '')
                    else:
                        href = a.get_attribute('href') or ''
                        name = ''
                        try:
                            val = a.evaluate('''(el) => {
                                const row = el.closest('.chart_row');
                                const selectors = ['.chart_row_name .title', '.chart_row_name', '.chart_name .title', '.chart_name', '.title', 'span.title'];
                                for (const sel of selectors) {
                                    let f = row ? row.querySelector(sel) : null;
                                    if (!f) f = el.querySelector(sel);
                                    if (f && (f.innerText || f.alt) && (f.innerText || f.alt).trim()) return (f.innerText || f.alt).trim();
                                }
                                const img = el.querySelector('img');
                                if (img && img.alt && img.alt.trim()) return img.alt.trim();
                                const txt = el.innerText || '';
                                for (const line of txt.split('\n')) { const s = line.trim(); if (s) return s; }
                                return null;
                            }''')
                            if val:
                                name = val.strip()
                        except Exception:
                            try:
                                name = a.inner_text().strip()
                            except Exception:
                                name = ''

                    appid, id_type = extract_id_from_href(href)
                    if not appid:
                        continue
                    key = (appid, id_type)
                    if key in seen:
                        continue
                    seen.add(key)

                    # build canonical store page href
                    canonical_href = href or f"https://store.steampowered.com/{id_type}/{appid}/"

                    results.append({'name': name, 'id': appid, 'id_type': id_type, 'query': 'charts', 'href': canonical_href, 'curator_review_count': '', 'curator_list_url': ''})
                except Exception:
                    continue

            print(f"Collected {len(results)} unique chart entries")

            # Optionally visit each game's page to extract curator counts (can be slow)
            if follow_details and results:
                _populate_curator_details(page, results, debug_dir)
        except Exception as e:
            print(f"Failed to load charts page: {e}")
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
    parser.add_argument('--charts', action='store_true', help='Scrape the Steam "Most Played" charts page')
    parser.add_argument('--charts-count', type=int, default=200, help='Number of top chart games to collect')
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
    if not queries and not args.charts:
        parser.error('Provide at least one --query, --queries-file, or --charts')

    rows = []
    if queries:
        rows.extend(scrape_queries(queries, pages=args.pages, headless=not args.no_headless, debug_dir=args.debug_dir, follow_details=not args.no_details))
    if args.charts:
        rows.extend(scrape_top_charts(count=args.charts_count, headless=not args.no_headless, debug_dir=args.debug_dir, follow_details=not args.no_details))
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
