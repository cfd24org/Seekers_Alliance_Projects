# Backup copy of working bbest.py
# This file is a snapshot of your current working script. Keep it safe.
# Do not run this file directly; it's only a saved copy.

# ...existing code...
# (This file intentionally left as a backup copy of bbest.py)

import asyncio
import csv
import re
import urllib.parse
import requests
import argparse
import os
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Support multiple games (list of Steam app ids)
# NOTE: user sometimes pastes a single string with commas. We accept both formats.
RAW_GAME_IDS = ["3314790, 646570, 2379780, 3405340, 2427700"]  # keep your original entry here
TEST_MODE = False
MAX_SCROLLS = 2 if TEST_MODE else 20
WAIT_BETWEEN_SCROLLS = 1.5
# If SCROLL_UNTIL_END is True the scraper will keep scrolling until the listing stops
# loading new curator entries (useful for games with many curators, e.g. ~1100)
SCROLL_UNTIL_END = False
# output filename is computed in main after normalization of GAME_IDS
MAX_CONCURRENT = 3  # number of parallel tabs/workers

# Navigation / retry tuning (adjust if Steam is slow or rate-limiting you)
NAV_TIMEOUT_MS = 30000     # 30s navigation timeout
NAV_RETRIES = 2            # number of retries for navigation on timeout
NAV_RETRY_SLEEP = 2       # seconds to wait before retry
# A common browser user-agent to reduce chance of bot-detection; change if desired
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


async def extract_email_from_text(text: str):
    """Extract the first email found in a text block.

    Return an empty string when no email is found (preferred for CSV sorting/filtering).
    """
    if not text:
        return ""
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return match.group(0) if match else ""


async def extract_email_from_link(elem):
    """Extract email from a <a class='curator_url'> element, only the address.

    Returns (href, email) where email is empty string if not found.
    """
    if not elem:
        return "", ""
    href = await elem.get_attribute("href") or ""
    text = await elem.inner_text() or ""
    email = ""

    # Try to extract email from the visible text
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    if match:
        email = match.group(0)
    else:
        # fallback: decode href
        decoded = urllib.parse.unquote(href)
        if "mailto:" in decoded:
            email = decoded.split("mailto:")[-1]
        elif "@" in decoded:
            email = decoded
    return href, email


async def process_curator(curator, page_pool):
    """Scrape info from a single curator block using a pooled page.

    Notes:
    - email fields default to empty string when not found
    - external_site defaults to empty string
    """
    name = "N/A"
    profile_link = ""
    followers = "N/A"
    recommendation = "N/A"
    try:
        # Basic info (from the listing block)
        name_elem = await curator.query_selector("div.name span")
        name = (await name_elem.inner_text()).strip() if name_elem else "N/A"

        profile_elem = await curator.query_selector("a.profile_avatar")
        profile_link = await profile_elem.get_attribute("href") if profile_elem else ""

        follower_elem = await curator.query_selector("div.followers span")
        followers = (await follower_elem.inner_text()).strip() if follower_elem else "N/A"

        rec_elem = await curator.query_selector("span.review_direction")
        recommendation = (await rec_elem.inner_text()).strip().upper() if rec_elem else "N/A"

        external_site = ""
        email_found = ""  # blank means no email found

        if profile_link:
            # acquire a page from the pool (this will block until available)
            page2 = await page_pool.get()
            try:
                try:
                    await page2.set_default_navigation_timeout(NAV_TIMEOUT_MS)
                except Exception:
                    pass
                try:
                    await page2.set_extra_http_headers({"User-Agent": DEFAULT_USER_AGENT})
                except Exception:
                    pass

                # Retry navigating to profile
                for attempt in range(NAV_RETRIES + 1):
                    try:
                        await page2.goto(profile_link, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                        break
                    except PlaywrightTimeoutError:
                        if attempt < NAV_RETRIES:
                            await asyncio.sleep(NAV_RETRY_SLEEP)
                        else:
                            print(f"[{name}] Timeout navigating to profile after {NAV_RETRIES+1} attempts")

                # External link under profile name
                site_link_el = await page2.query_selector("a.curator_url.ttip")
                if site_link_el:
                    external_site, email_from_link = await extract_email_from_link(site_link_el)
                    if email_from_link:
                        email_found = email_from_link

                # About page (may contain an email)
                about_link_el = await page2.query_selector("a.about")
                if about_link_el:
                    about_url = await about_link_el.get_attribute("href")
                    if about_url:
                        for attempt in range(NAV_RETRIES + 1):
                            try:
                                await page2.goto(about_url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                                break
                            except PlaywrightTimeoutError:
                                if attempt < NAV_RETRIES:
                                    await asyncio.sleep(NAV_RETRY_SLEEP)
                                else:
                                    print(f"[{name}] Timeout navigating to about page after {NAV_RETRIES+1} attempts")

                        desc_el = await page2.query_selector(
                            "div.about_container div.desc, div.about_container p.tagline"
                        )
                        if desc_el:
                            text = await desc_el.inner_text()
                            possible_email = await extract_email_from_text(text)
                            if possible_email:
                                email_found = possible_email
            except PlaywrightTimeoutError:
                print(f"[{name}] Timeout on profile page")
            except Exception as e:
                print(f"[{name}] Error when visiting profile: {e}")
            finally:
                try:
                    await page2.goto('about:blank', timeout=5000)
                except Exception:
                    pass
                await page_pool.put(page2)

        return {
            "curator_name": name,
            "steam_profile": profile_link,
            "followers": followers,
            "recommendation": recommendation,
            "external_site": external_site,
            "email": email_found,
        }

    except Exception as e:
        print(f"[{name if name else 'N/A'}] Error processing profile: {e}")
        return {
            "curator_name": name if name else "N/A",
            "steam_profile": profile_link if profile_link else "",
            "followers": followers if followers else "N/A",
            "recommendation": recommendation if recommendation else "N/A",
            "external_site": "",
            "email": "",
        }


async def main():
    # Command-line args: allow passing an existing CSV to incrementally update
    parser = argparse.ArgumentParser(description="Steam curator scraper (incremental mode supported)")
    parser.add_argument("--input-csv", dest="input_csv", help="Existing curator CSV to load and update (optional)")
    parser.add_argument("--games-file", dest="games_file", help="File with appids (one per line). Overrides RAW_GAME_IDS if provided.")
    parser.add_argument("--scroll-until-end", dest="scroll_until_end", action="store_true", help="Enable SCROLL_UNTIL_END mode for large listings")
    parser.add_argument("--concurrency", dest="concurrency", type=int, help="Override MAX_CONCURRENT")
    args = parser.parse_args()

    # Allow overriding flags via CLI
    global SCROLL_UNTIL_END, MAX_CONCURRENT
    if args.scroll_until_end:
        SCROLL_UNTIL_END = True
    if args.concurrency:
        MAX_CONCURRENT = max(1, args.concurrency)

    # If user passed a games file, load appids from it (one per line, ignore empty/comment lines)
    game_input = RAW_GAME_IDS
    if args.games_file:
        if os.path.exists(args.games_file):
            with open(args.games_file, 'r', encoding='utf-8') as gf:
                lines = [l.strip() for l in gf.readlines()]
                game_input = [l for l in lines if l and not l.startswith('#')]
        else:
            print(f"Games file not found: {args.games_file}")
            return

    # Normalize GAME_IDS: accept either a list of clean ids OR a single comma-separated string
    GAME_IDS = []
    if isinstance(game_input, (list, tuple)) and len(game_input) == 1 and "," in game_input[0]:
        GAME_IDS = [s.strip() for s in game_input[0].split(",") if s.strip()]
    else:
        GAME_IDS = [str(x).strip() for x in game_input]

    # recompute output filename now that GAME_IDS is normalized
    safe_ids = [g.replace('/', '_') for g in GAME_IDS]
    global OUTPUT_FILE
    OUTPUT_FILE = f"curators_{'_'.join(safe_ids)}_{'test' if TEST_MODE else 'full'}.csv"

    def load_existing_csv(path: str):
        """Load an existing CSV and return an aggregated dict keyed by steam_profile (fallback to name).

        The returned structure matches the aggregator used later: { key: { 'data': {...}, 'games': set(...) } }
        """
        agg = {}
        if not path or not os.path.exists(path):
            return agg
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for r in reader:
                profile = (r.get('steam_profile') or '').strip()
                name = (r.get('curator_name') or '').strip()
                key = profile if profile else name if name else None
                if not key:
                    continue
                games_field = (r.get('game') or '')
                games = set([g.strip() for g in games_field.split(';') if g.strip()]) if games_field else set()
                # normalize fields: ensure email empty string if missing
                rec = {
                    'curator_name': name or 'N/A',
                    'steam_profile': profile or '',
                    'followers': r.get('followers') or 'N/A',
                    'recommendation': r.get('recommendation') or 'N/A',
                    'external_site': r.get('external_site') or '',
                    'email': r.get('email') or '',
                }
                agg[key] = {'data': rec, 'games': games}
        return agg

    # Load existing CSV into aggregator if provided
    aggregated = {}
    if args.input_csv:
        aggregated = load_existing_csv(args.input_csv)
        print(f"Loaded {len(aggregated)} curators from {args.input_csv}")

    def get_game_name(appid: str) -> str:
        """Sync helper: ask Steam API for friendly name, fallback to id."""
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
            resp = requests.get(url, timeout=5).json()
            if resp and str(appid) in resp and resp[str(appid)].get("success"):
                return resp[str(appid)]["data"].get("name", f"Unknown ({appid})")
        except Exception:
            pass
        return f"Unknown ({appid})"

    async with async_playwright() as p:
        # Run headless so windows don't steal focus
        browser = await p.chromium.launch(headless=True)

        # Create a small pool of pages for profile visits (limits visible tabs)
        # We set the user-agent on each pooled page to reduce bot-detection.
        page_pool = asyncio.Queue()
        for _ in range(MAX_CONCURRENT):
            ppage = await browser.new_page()
            try:
                await ppage.set_extra_http_headers({"User-Agent": DEFAULT_USER_AGENT})
            except Exception:
                pass
            try:
                await ppage.set_default_navigation_timeout(NAV_TIMEOUT_MS)
            except Exception:
                pass
            await ppage.goto('about:blank')
            await page_pool.put(ppage)

        # semaphore used by all workers
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        async def sem_task(curator):
            async with semaphore:
                return await process_curator(curator, page_pool)

        # If aggregated was not loaded from CSV earlier, start empty
        # aggregated variable may already contain preloaded entries

        for appid in GAME_IDS:
            app_name = get_game_name(appid)
            curator_page_url = f"https://store.steampowered.com/curators/curatorsreviewing/?appid={appid}"

            # open listing page for this app id
            page = await browser.new_page()
            try:
                await page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
            except Exception:
                pass
            try:
                await page.goto(curator_page_url, timeout=NAV_TIMEOUT_MS, wait_until="networkidle")
            except PlaywrightTimeoutError:
                print(f"[{app_name}] Timeout loading curator listing for appid {appid}")
                await page.close()
                continue

            # Scroll the page according to mode
            if SCROLL_UNTIL_END:
                prev_count = 0
                stable_rounds = 0
                rounds = 0
                max_rounds = 500  # safety cap in case site never reports stability
                while rounds < max_rounds:
                    await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                    await asyncio.sleep(WAIT_BETWEEN_SCROLLS)
                    curator_divs = await page.query_selector_all("div.curator_page")
                    cur_count = len(curator_divs)
                    print(f"[{app_name}] Scrolled (auto) round {rounds+1}; curators: {cur_count}")
                    if cur_count == prev_count:
                        stable_rounds += 1
                        if stable_rounds >= 3:
                            break
                    else:
                        stable_rounds = 0
                        prev_count = cur_count
                    rounds += 1
            else:
                for i in range(MAX_SCROLLS):
                    await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                    print(f"[{app_name}] Scrolled {i + 1} times")
                    await asyncio.sleep(WAIT_BETWEEN_SCROLLS)

            # after scrolling get the final list of curator blocks
            curator_divs = await page.query_selector_all("div.curator_page")
            print(f"[{app_name}] Found {len(curator_divs)} curators on page")

            # build tasks only for curators not already seen (keyed by steam_profile when available)
            tasks = []
            keys = []
            for curator in curator_divs:
                name_elem = await curator.query_selector("div.name span")
                name = (await name_elem.inner_text()).strip() if name_elem else "N/A"
                profile_elem = await curator.query_selector("a.profile_avatar")
                profile_link = await profile_elem.get_attribute("href") if profile_elem else ""
                key = profile_link if profile_link else name
                if key in aggregated:
                    aggregated[key]["games"].add(app_name)
                    continue
                tasks.append(sem_task(curator))
                keys.append(key)

            results = []
            if tasks:
                results = await asyncio.gather(*tasks)

            # store results and attach game using the same key we checked earlier
            for res, key in zip(results, keys):
                if not res:
                    continue
                res_games = set([app_name])
                res_record = res.copy()
                aggregated[key] = {"data": res_record, "games": res_games}

            await page.close()

        # Close pooled pages
        while not page_pool.empty():
            ppage = await page_pool.get()
            await ppage.close()

        # Flatten aggregated results and write CSV with a 'game' column
        final_rows = []
        for key, entry in aggregated.items():
            row = entry["data"].copy()
            games_field = ";".join(sorted(entry["games"]))
            row["game"] = games_field
            # add helper column so you can sort by presence of email easily (1 has email, 0 missing)
            row["has_email"] = 1 if row.get("email") else 0
            final_rows.append(row)

        # Save CSV (include game and has_email columns)
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["curator_name", "steam_profile", "followers", "recommendation", "external_site", "email", "has_email", "game"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(final_rows)

        print(f"💾 Saved {len(final_rows)} unique curators to {OUTPUT_FILE}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
