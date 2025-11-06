"""
bbest.py - Steam curator scraper

Usage highlights:
  - Incremental updates supported via --input-csv
  - Provide games via --games-file or --appid (single) or edit RAW_GAME_IDS
  - New flags: --output-file to force the output filename, --export-new-only to write only newly discovered curators

Example:
  python bbest.py --input-csv curators_prev.csv --games-file new_games.txt --scroll-until-end --concurrency 1 --output-file merged.csv --export-new-only

Requirements: playwright, requests
"""

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
RAW_GAME_IDS = ["2746910", "1990110"]  # keep your original entry here
TEST_MODE = False
MAX_SCROLLS = 2 if TEST_MODE else 20
WAIT_BETWEEN_SCROLLS = 1.5
# If SCROLL_UNTIL_END is True the scraper will keep scrolling until the listing stops
# loading new curator entries (useful for games with many curators, e.g. ~1100)
SCROLL_UNTIL_END = False
# output filename is computed in main after normalization of GAME_IDS
# Reduce the default MAX_CONCURRENT value to limit the number of pages opened simultaneously
MAX_CONCURRENT = 1  # Adjusted to open only one page at a time

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
        # Explicit mailto: should always be treated as an email
        if decoded.lower().startswith("mailto:"):
            email = decoded.split("mailto:")[-1]
        else:
            # If the href looks like a URL (http(s)://...), only treat it as an email
            # if an email-like pattern appears in the URL (e.g., mailto or query params).
            # This prevents YouTube style handles like 'https://www.youtube.com/@TrendAddictGames'
            # from being mistaken for an email address.
            url_like = decoded.lower().startswith("http://") or decoded.lower().startswith("https://")
            # Search for a proper email pattern anywhere in the decoded href/text
            match2 = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", decoded)
            if match2:
                email = match2.group(0)
            else:
                # As a last resort (non-URL raw strings), if there's an '@' but no email pattern,
                # don't treat it as an email — keep it as external_site only.
                email = ""
    return href, email


async def process_curator(curator, page_pool, appid=None, app_name=None, listing_review=None):
    """Scrape info from a single curator block using a pooled page.

    Notes:
    - email fields default to empty string when not found
    - external_site defaults to empty string
    """
    name = "N/A"
    profile_link = ""
    followers = "N/A"
    about_me = ""
    sample_review = ""
    reviews_count = 0
    try:
        # Basic info (from the listing block)
        name_elem = await curator.query_selector("div.name span")
        name = (await name_elem.inner_text()).strip() if name_elem else "N/A"

        profile_elem = await curator.query_selector("a.profile_avatar")
        profile_link = await profile_elem.get_attribute("href") if profile_elem else ""

        follower_elem = await curator.query_selector("div.followers span")
        followers = (await follower_elem.inner_text()).strip() if follower_elem else "N/A"

        # NOTE: we intentionally drop the per-listing 'recommendation' value (not useful)

        external_site = ""
        email_found = ""  # blank means no email found

        # If the listing already contains a review snippet (recommended), prefer it
        if listing_review and not sample_review:
            try:
                sample_review = (listing_review or "").strip()[:800]
            except Exception:
                pass

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

                # Try to capture a short sample review from the profile that matches the current appid.
                # First, look for a direct link on the profile that points to a review/store page for this appid;
                # if found, navigate to that URL and extract the review text there (preferred). Otherwise
                # fall back to scanning review blocks on the profile page.
                try:
                    review_page_selectors = [
                        "div.apphub_UserReviewCardContent", "div.review_box", "div.user_review",
                        "div.review_body", "div.review_text", "div.reviews p", "div.text"
                    ]

                    # Look for anchors on the profile page linking to the store/review for this appid
                    candidate_review_href = None
                    try:
                        anchors = await page2.query_selector_all('a')
                        for a in anchors:
                            ahref = await a.get_attribute('href') or ''
                            if not ahref:
                                continue
                            # Normalize and detect appid mentions in href (common patterns)
                            if appid and (f"/app/{appid}" in ahref or f"app={appid}" in ahref or re.search(rf"{re.escape(str(appid))}", ahref)):
                                candidate_review_href = urllib.parse.urljoin(page2.url, ahref)
                                break
                    except Exception:
                        candidate_review_href = None

                    # If we found a candidate review link, try to open and extract its review text
                    if candidate_review_href:
                        try:
                            await page2.goto(candidate_review_href, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                            # try multiple selectors on the review page
                            for sel in review_page_selectors:
                                try:
                                    rev_el = await page2.query_selector(sel)
                                    if rev_el:
                                        txt = (await rev_el.inner_text() or "").strip()
                                        if txt:
                                            # ignore Steam's "no more reviews that match the filters" placeholder
                                            if "no more reviews" in txt.lower():
                                                continue
                                            sample_review = txt.replace("\n", " ")[:1200]
                                            break
                                except Exception:
                                    continue
                        except Exception:
                            # If navigation to the candidate link failed, ignore and fall back
                            sample_review = sample_review or ""

                    # If no candidate link or extraction failed, fall back to scanning review blocks on profile page
                    if not sample_review:
                        for sel in review_page_selectors:
                            try:
                                rev_els = await page2.query_selector_all(sel)
                                if not rev_els:
                                    continue
                                # prefer a review that mentions the appid (or app_name) inside the review element or its anchors
                                found_review = None
                                for rev_el in rev_els:
                                    try:
                                        txt = (await rev_el.inner_text() or "").strip()
                                        # ignore Steam's generic no-results text
                                        if "no more reviews" in (txt or "").lower():
                                            continue
                                        anchors = await rev_el.query_selector_all('a')
                                        matched = False
                                        for a in anchors:
                                            ahref = await a.get_attribute('href') or ''
                                            if ahref and appid and re.search(rf"{re.escape(str(appid))}", ahref):
                                                matched = True
                                                break
                                        if not matched and app_name and app_name.lower() in (txt or "").lower():
                                            matched = True
                                        if matched:
                                            found_review = txt
                                            break
                                    except Exception:
                                        continue
                                if found_review:
                                    sample_review = found_review.replace("\n", " ")[:1200]
                                    break
                                # fallback: if no matching review found yet, keep the first available as fallback
                                if not sample_review and rev_els:
                                    try:
                                        first_txt = (await rev_els[0].inner_text() or "").strip()
                                        if first_txt and "no more reviews" not in first_txt.lower():
                                            sample_review = first_txt.replace("\n", " ")[:1200]
                                    except Exception:
                                        pass
                            except Exception:
                                continue

                except Exception:
                    # Non-fatal: leave sample_review empty if anything fails
                    sample_review = sample_review or ""

                # About page (may contain an email and about text)
                about_link_el = await page2.query_selector("a.about")
                if about_link_el:
                    about_url = await about_link_el.get_attribute("href")
                    if about_url:
                        for attempt in range(NAV_RETRIES + 2):  # Increase retries
                            try:
                                await page2.goto(about_url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                                break
                            except PlaywrightTimeoutError:
                                if attempt < NAV_RETRIES + 1:
                                    await asyncio.sleep(NAV_RETRY_SLEEP)
                                else:
                                    print(f"[{name}] Timeout navigating to About page after {NAV_RETRIES + 2} attempts")

                        desc_el = await page2.query_selector(
                            "div.about_container div.desc p.tagline, div.about_container div.desc"
                        )
                        if desc_el:
                            text = await desc_el.inner_text()
                            about_me = (text or "").strip()
                            print(f"[DEBUG] Extracted 'about_me' from About page: {about_me}")

                        # Additional fallback: extract from main profile page if About fails
                        if not about_me:
                            try:
                                body_text = (await page2.inner_text('body') or "").strip()
                                about_me = body_text[:500]  # Limit to 500 chars
                                print(f"[DEBUG] Fallback 'about_me' extracted from body: {about_me}")
                            except Exception as e:
                                print(f"[DEBUG] Failed to extract 'about_me' from body: {e}")

                        # Enhanced fallback logic for 'About Me' extraction
                        if not about_me:
                            try:
                                # Additional wait for dynamic content
                                await asyncio.sleep(2)  # Wait for 2 seconds to allow dynamic content to load

                                # Attempt alternative selectors for 'About Me'
                                for selector in [
                                    "div.profile_about p",
                                    "div.profile_about",
                                    "div.curator_about",
                                    "div.curator_description",
                                    "body"
                                ]:
                                    try:
                                        about_me_elem = await page2.query_selector(selector)
                                        about_me = (await about_me_elem.inner_text()).strip() if about_me_elem else about_me
                                        if about_me:
                                            print(f"[DEBUG] Extracted 'about_me' using selector '{selector}': {about_me}")
                                            break
                                    except Exception as e:
                                        print(f"[DEBUG] Failed to extract 'about_me' using selector '{selector}': {e}")

                            except Exception as e:
                                print(f"[DEBUG] Failed to extract 'about_me' using enhanced fallback: {e}")

                            # Remove 'followers' and 'reviews posted' from 'about_me'
                            if about_me:
                                # Clean the 'about_me' field to remove unwanted text
                                about_me = re.sub(r"\n?\s*[\d,]+\s*(?:CURATOR|CREATOR)?\s*FOLLOWERS\b.*", "", about_me, flags=re.I)
                                about_me = re.sub(r"\n?\s*[\d,]+\s*(?:REVIEWS|REVIEWS POSTED|POSTED)\b.*", "", about_me, flags=re.I)
                                about_me = re.sub(r"\bPOSTED\b", "", about_me, flags=re.I)
                                about_me = re.sub(r"\s+", " ", about_me).strip()
                                print(f"[DEBUG] Cleaned 'about_me': {about_me}")

                # If we still don't have a reviews_count, try scanning the page body for a reviews badge
                if not reviews_count:
                    try:
                        body_text = (await page2.inner_text('body') or "").strip()
                        m2 = re.search(r"([\d,]+)\s*(?:REVIEWS|REVIEWS POSTED|POSTED)", body_text, flags=re.I)
                        if m2:
                            try:
                                reviews_count = int(m2.group(1).replace(",", ""))
                                print(f"[DEBUG] Extracted 'reviews_count': {reviews_count}")
                            except Exception as e:
                                print(f"[DEBUG] Failed to parse 'reviews_count': {e}")
                        else:
                            print("[DEBUG] No match found for 'reviews_count' in body text.")
                    except Exception as e:
                        print(f"[DEBUG] Failed to extract 'reviews_count' from body: {e}")

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
            "external_site": external_site,
            "about_me": about_me,
            "sample_review": sample_review,
            "email": email_found,
            "reviews": reviews_count,
        }

    except Exception as e:
        print(f"[{name if name else 'N/A'}] Error processing profile: {e}")
        return {
            "curator_name": name if name else "N/A",
            "steam_profile": profile_link if profile_link else "",
            "followers": followers if followers else "N/A",
            "external_site": "",
            "about_me": "",
            "sample_review": "",
            "email": "",
            "reviews": reviews_count,
        }


async def main():
    # Command-line args: allow passing an existing CSV to incrementally update
    parser = argparse.ArgumentParser(description="Steam curator scraper (incremental mode supported)")
    parser.add_argument("--input-csv", dest="input_csv", help="Existing curator CSV to load and update (optional)")
    parser.add_argument("--games-file", dest="games_file", help="File with appids (one per line). Overrides RAW_GAME_IDS if provided.")
    parser.add_argument("--appid", dest="single_appid", help="Single Steam appid to scrape (optional)")
    parser.add_argument("--scroll-until-end", dest="scroll_until_end", action="store_true", help="Enable SCROLL_UNTIL_END mode for large listings")
    parser.add_argument("--concurrency", dest="concurrency", type=int, help="Override MAX_CONCURRENT")
    parser.add_argument("--output-file", dest="output_file", help="Force the output CSV filename (optional)")
    parser.add_argument("--export-new-only", dest="export_new_only", action="store_true", help="Export only newly discovered curators (requires --input-csv)")
    # By default the script runs in headless mode to avoid opening visible browser windows.
    # Provide --no-headless to force visible browser windows when debugging.
    parser.add_argument("--no-headless", dest="no_headless", action="store_true", help="Run browser with visible windows (non-headless)")
    args = parser.parse_args()

    # Default to headless mode unless user passes --no-headless
    headless_mode = not getattr(args, 'no_headless', False)

    # Allow overriding flags via CLI
    global SCROLL_UNTIL_END, MAX_CONCURRENT
    if args.scroll_until_end:
        SCROLL_UNTIL_END = True
    if args.concurrency:
        MAX_CONCURRENT = max(1, args.concurrency)

    # Determine which games to process (priority: --appid, --games-file, RAW_GAME_IDS)
    game_input = RAW_GAME_IDS
    if getattr(args, 'single_appid', None):
        # single appid provided on command line
        game_input = [str(args.single_appid).strip()]
    elif args.games_file:
        # load appids from provided file (one per line)
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
    # Respect explicit output filename if provided
    if getattr(args, 'output_file', None):
        OUTPUT_FILE = args.output_file

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
                    'external_site': r.get('external_site') or '',
                    'about_me': r.get('about_me') or '',
                    'sample_review': r.get('sample_review') or '',
                    'email': r.get('email') or '',
                    'reviews': int(r.get('reviews') or 0) if r.get('reviews') else 0,
                }
                agg[key] = {'data': rec, 'games': games}
        return agg

    # Load existing CSV into aggregator if provided
    aggregated = {}
    if args.input_csv:
        aggregated = load_existing_csv(args.input_csv)
        print(f"Loaded {len(aggregated)} curators from {args.input_csv}")

    # Track which keys were newly discovered during this run so we can optionally export only new ones
    newly_added_keys = set()

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

    # Add retry mechanism for page creation
    async with async_playwright() as p:
        try:
            print(f"[DEBUG] Launching browser in {'headless' if headless_mode else 'non-headless'} mode...")
            # Ensure all browser launches respect the headless_mode setting
            browser = await p.chromium.launch(headless=headless_mode)  # Toggle headless mode
            print("[DEBUG] Browser launched in headless mode:", headless_mode)

            # Ensure all new pages respect the headless mode
            page = await browser.new_page()
            print("[DEBUG] New page created in browser.")
        except Exception as e:
            print(f"[ERROR] Failed during browser or page setup: {e}")
            raise

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

        # New: worker that accepts plain data (no ElementHandle) to avoid keeping page handles alive
        async def process_curator_by_url(profile_link, name, page_pool, followers=None, appid=None, app_name=None, listing_review=None):
            """Visit a curator profile URL using a pooled page and extract details.
            This mirrors the logic in process_curator but works from strings only to avoid
            holding ElementHandle references from the listing page (which Playwright may GC).
            """
            about_me = ""
            sample_review = ""
            external_site = ""
            email_found = ""
            # Start with the followers value extracted from the listing (if provided)
            followers = followers or "N/A"
            reviews_count = 0

            if not profile_link:
                return {
                    "curator_name": name or 'N/A',
                    "steam_profile": profile_link or '',
                    "followers": followers,
                    "external_site": external_site,
                    "about_me": about_me,
                    "sample_review": sample_review,
                    "reviews": reviews_count,
                    "email": email_found,
                }

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

                # Try to find followers on the profile page
                try:
                    follower_elem = await page2.query_selector("div.followers span")
                    if follower_elem:
                        followers = (await follower_elem.inner_text()).strip() or 'N/A'
                except Exception:
                    pass

                # External link under profile name
                try:
                    site_link_el = await page2.query_selector("a.curator_url.ttip")
                    if site_link_el:
                        external_site, email_from_link = await extract_email_from_link(site_link_el)
                        if email_from_link:
                            email_found = email_from_link
                except Exception:
                    pass

                # Sample review extraction: prefer listing_review provided earlier
                if listing_review and not sample_review:
                    try:
                        sample_review = (listing_review or "").strip()[:800]
                    except Exception:
                        pass

                # Search for candidate review links or review blocks on the profile page
                try:
                    review_page_selectors = [
                        "div.apphub_UserReviewCardContent", "div.review_box", "div.user_review",
                        "div.review_body", "div.review_text", "div.reviews p", "div.text"
                    ]

                    candidate_review_href = None
                    try:
                        anchors = await page2.query_selector_all('a')
                        for a in anchors:
                            ahref = await a.get_attribute('href') or ''
                            if not ahref:
                                continue
                            if appid and (f"/app/{appid}" in ahref or f"app={appid}" in ahref or re.search(rf"{re.escape(str(appid))}", ahref)):
                                candidate_review_href = urllib.parse.urljoin(page2.url, ahref)
                                break
                    except Exception:
                        candidate_review_href = None

                    if candidate_review_href:
                        try:
                            await page2.goto(candidate_review_href, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                            for sel in review_page_selectors:
                                try:
                                    rev_el = await page2.query_selector(sel)
                                    if rev_el:
                                        txt = (await rev_el.inner_text()).strip()
                                        if txt and "no more reviews" not in txt.lower():
                                            sample_review = txt.replace("\n", " ")[:1200]
                                            break
                                except Exception:
                                    continue
                        except Exception:
                            sample_review = sample_review or ""

                    if not sample_review:
                        for sel in review_page_selectors:
                            try:
                                rev_els = await page2.query_selector_all(sel)
                                if not rev_els:
                                    continue
                                found_review = None
                                for rev_el in rev_els:
                                    try:
                                        txt = (await rev_el.inner_text()).strip()
                                        if "no more reviews" in (txt or "").lower():
                                            continue
                                        anchors = await rev_el.query_selector_all('a')
                                        matched = False
                                        for a in anchors:
                                            ahref = await a.get_attribute('href') or ''
                                            if ahref and appid and re.search(rf"{re.escape(str(appid))}", ahref):
                                                matched = True
                                                break
                                        if not matched and app_name and app_name.lower() in (txt or "").lower():
                                            matched = True
                                        if matched:
                                            found_review = txt
                                            break
                                    except Exception:
                                        continue
                                if found_review:
                                    sample_review = found_review.replace("\n", " ")[:1200]
                                    break
                                if not sample_review and rev_els:
                                    try:
                                        first_txt = (await rev_els[0].inner_text()).strip()
                                        if first_txt and "no more reviews" not in first_txt.lower():
                                            sample_review = first_txt.replace("\n", " ")[:1200]
                                    except Exception:
                                        pass
                            except Exception:
                                continue
                except Exception:
                    sample_review = sample_review or ""

                # About page (may contain an email and about text)
                try:
                    about_link_el = await page2.query_selector("a.about")
                    if about_link_el:
                        about_url = await about_link_el.get_attribute("href")
                        if about_url:
                            for attempt in range(NAV_RETRIES + 2):  # Increase retries
                                try:
                                    await page2.goto(about_url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                                    break
                                except PlaywrightTimeoutError:
                                    if attempt < NAV_RETRIES + 1:
                                        await asyncio.sleep(NAV_RETRY_SLEEP)
                                    else:
                                        print(f"[{name}] Timeout navigating to About page after {NAV_RETRIES + 2} attempts")

                            desc_el = await page2.query_selector(
                                "div.about_container div.desc p.tagline, div.about_container div.desc"
                            )
                            if desc_el:
                                text = await desc_el.inner_text()
                                about_me = (text or "").strip()
                                print(f"[DEBUG] Extracted 'about_me' from About page: {about_me}")

                                # Additional fallback: extract from main profile page if About fails
                                if not about_me:
                                    try:
                                        body_text = (await page2.inner_text('body') or "").strip()
                                        about_me = body_text[:500]  # Limit to 500 chars
                                        print(f"[DEBUG] Fallback 'about_me' extracted: {about_me}")
                                    except Exception as e:
                                        print(f"[DEBUG] Failed to extract 'about_me' from body: {e}")
                except Exception:
                    pass

                # If we still don't have a reviews_count, try scanning the page body for a reviews badge
                try:
                    if not reviews_count:
                        try:
                            body_text = (await page2.inner_text('body') or "").strip()
                            m2 = re.search(r"([\d,]+)\s*(?:REVIEWS|REVIEWS POSTED|POSTED)", body_text, flags=re.I)
                            if m2:
                                try:
                                    reviews_count = int(m2.group(1).replace(",", ""))
                                    print(f"[DEBUG] Extracted 'reviews_count': {reviews_count}")
                                except Exception as e:
                                    print(f"[DEBUG] Failed to parse 'reviews_count': {e}")
                            else:
                                print("[DEBUG] No match found for 'reviews_count' in body text.")
                        except Exception as e:
                            print(f"[DEBUG] Failed to extract 'reviews_count' from body: {e}")
                except Exception:
                    pass

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
                "curator_name": name or 'N/A',
                "steam_profile": profile_link or '',
                "followers": followers,
                "external_site": external_site,
                "about_me": about_me,
                "sample_review": sample_review,
                "reviews": reviews_count,
                "email": email_found,
            }

        async def sem_task(curator_data, appid=None, app_name=None, listing_review=None):
            async with semaphore:
                # curator_data is a tuple (profile_link, name, followers)
                profile_link, name, followers = curator_data
                return await process_curator_by_url(profile_link, name, page_pool, followers=followers, appid=appid, app_name=app_name, listing_review=listing_review)

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

            # Retry navigating to the curator page
            for attempt in range(NAV_RETRIES + 1):
                try:
                    await page.goto(curator_page_url, timeout=NAV_TIMEOUT_MS * 2, wait_until="networkidle")
                    break  # Exit loop if navigation succeeds
                except Exception as e:
                    if attempt < NAV_RETRIES:
                        print(f"[WARNING] Retry {attempt + 1}/{NAV_RETRIES} for appid {appid}: {e}")
                        await asyncio.sleep(NAV_RETRY_SLEEP)
                    else:
                        print(f"[ERROR] Failed to load curator page for appid {appid} after {NAV_RETRIES + 1} attempts: {e}")
                        await page.close()
                        return

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
                # Extract follower count from the listing block (preserve this value)
                follower_elem = await curator.query_selector("div.followers span")
                follower_text = (await follower_elem.inner_text()).strip() if follower_elem else "N/A"
                key = profile_link if profile_link else name
                if key in aggregated:
                    aggregated[key]["games"].add(app_name)
                    continue
                # Try to extract a short review snippet directly from the listing block (preferred)
                listing_snippet = ""
                try:
                    # First, look for store capsule anchors that reference this appid and extract their nearby text
                    try:
                        anchors = await curator.query_selector_all('a.store_capsule, a.app_impression_tracked, a')
                        for a in anchors:
                            ds_appid = await a.get_attribute('data-ds-appid') or ''
                            ahref = await a.get_attribute('href') or ''
                            if (ds_appid and str(ds_appid) == str(appid)) or (f"/app/{appid}" in ahref) or (f"app={appid}" in ahref):
                                # prefer a div.text inside the anchor or its parent
                                txt_el = await a.query_selector('div.text')
                                if not txt_el:
                                    # check parent node for a div.text
                                    parent = await a.evaluate_handle('node => node.parentElement')
                                    try:
                                        if parent:
                                            txt_el = await parent.as_element().query_selector('div.text')
                                    except Exception:
                                        txt_el = None
                                if txt_el:
                                    txt = (await txt_el.inner_text() or '').strip()
                                    if txt and 'no more reviews' not in txt.lower():
                                        listing_snippet = txt.replace('\n', ' ')[:800]
                                        break
                    except Exception:
                        pass

                    # fallback to existing selectors if we didn't find a targeted snippet
                    if not listing_snippet:
                        for sel in ["div.review_text", "div.curator_review", "div.recent_review", "div.review_body", "p.tagline", "div.review", "div.text"]:
                            el = await curator.query_selector(sel)
                            if el:
                                txt = (await el.inner_text() or "").strip()
                                if txt and 'no more reviews' not in txt.lower():
                                    listing_snippet = txt.replace("\n", " ")[:800]
                                    break
                except Exception:
                    listing_snippet = ""

                # Immediately extract the minimal data (strings) and schedule the worker that uses only URLs/names.
                curator_data = (profile_link, name, follower_text)
                tasks.append(sem_task(curator_data, appid, app_name, listing_review=listing_snippet))
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
                newly_added_keys.add(key)

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

            # Ensure we have a numeric reviews value (may have been populated by worker)
            try:
                row["reviews"] = int(row.get("reviews") or 0)
            except Exception:
                row["reviews"] = 0

            # Validate that the email field contains a proper email pattern; clear it otherwise
            email_val = (row.get("email") or "").strip()
            if email_val and re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", email_val):
                row["has_email"] = 1
                row["email"] = email_val
            else:
                row["has_email"] = 0
                row["email"] = ""

            # Initialize 'about_me' with a default value to avoid scope issues
            about_me = row.get("about_me", "[ERROR: Unable to extract 'about me' section]")
            if not about_me:
                about_me = "[ERROR: Unable to extract 'about me' section]"
            print(f"[DEBUG] Final 'about_me' before saving: {about_me}")

            # Apply cleaning logic to 'about_me' before saving
            about_me = re.sub(r"\n?\s*[\d,]+\s*(?:CURATOR|CREATOR)?\s*FOLLOWERS\b.*", "", about_me, flags=re.I)
            about_me = re.sub(r"\n?\s*[\d,]+\s*(?:REVIEWS|REVIEWS POSTED|POSTED)\b.*", "", about_me, flags=re.I)
            about_me = re.sub(r"\bPOSTED\b", "", about_me, flags=re.I)
            about_me = re.sub(r"\s+", " ", about_me).strip()
            print(f"[DEBUG] Cleaned 'about_me' before saving: {about_me}")
            row["about_me"] = about_me

            final_rows.append(row)

        # If user requested only newly discovered curators and an input CSV was provided,
        # filter the rows accordingly.
        rows_to_write = final_rows
        if getattr(args, 'export_new_only', False) and args.input_csv:
            # determine which rows correspond to newly_added_keys
            rows_to_write = [r for k, r in zip(aggregated.keys(), final_rows) if k in newly_added_keys]

        # Save CSV (include reviews, game and has_email columns)
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["curator_name", "steam_profile", "followers", "reviews", "external_site", "about_me", "sample_review", "email", "has_email", "game"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_to_write)

        print(f"💾 Saved {len(rows_to_write)} unique curators to {OUTPUT_FILE}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
