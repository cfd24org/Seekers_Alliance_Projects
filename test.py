import asyncio
from playwright.async_api import async_playwright
import csv
import urllib.parse
import requests

# --- CONFIG ---
APP_IDS = ["3112170", "578080"]  # example: Portal 2, Dead by Daylight
TEST_MODE = True  # True = limit curators per game for testing
MAX_CURATORS_PER_GAME = 20 if TEST_MODE else 99999
CONCURRENT_WORKERS = 3
OUTPUT_FILE = f"curators_multi_games_{'test' if TEST_MODE else 'full'}.csv"

# --- Helper functions ---
def get_game_name(appid):
    """Fetch Steam game name from app ID."""
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp[str(appid)]["success"]:
            return resp[str(appid)]["data"]["name"]
    except:
        pass
    return f"Unknown ({appid})"

def extract_email_from_text(text):
    """Extract first email-looking substring from text."""
    import re
    matches = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return matches[0] if matches else "N/A"

# async def extract_email_from_link(elem):
#     """Try to extract email from a <a class='curator_url'> element."""
#     if not elem:
#         return ("N/A", "N/A")
#     href = await elem.get_attribute("href")  # must be awaited in async
#     text = await elem.inner_text()
#     text = text.strip() if text else ""
#     email = "N/A"
#     if "@" in text and "." in text:
#         email = text
#     else:
#         decoded = urllib.parse.unquote(href)
#         if "mailto:" in decoded:
#             email = decoded.split("mailto:")[-1]
#         elif "@" in decoded:
#             email = decoded
#     return (href, email)

async def extract_email_from_link(elem):
    """Extract email from a <a class='curator_url'> element, only the address."""
    import re
    if not elem:
        return "N/A", "N/A"
    href = await elem.get_attribute("href") or "N/A"
    text = await elem.inner_text() or ""
    email = "N/A"

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

# --- Async scraping functions ---
async def process_curator(curator, browser, app_name):
    """Process a single curator: get profile, external site, email."""
    try:
        name_elem = await curator.query_selector("div.name span")
        name = await name_elem.inner_text() if name_elem else "N/A"

        profile_link_elem = await curator.query_selector("a.profile_avatar")
        profile_link = await profile_link_elem.get_attribute("href") if profile_link_elem else "N/A"

        follower_elem = await curator.query_selector("div.followers span")
        followers = await follower_elem.inner_text() if follower_elem else "N/A"

        rec_elem = await curator.query_selector("span.review_direction")
        recommendation = (await rec_elem.inner_text()).upper() if rec_elem else "N/A"

        external_site = "N/A"
        email_found = "N/A"

        if profile_link != "N/A":
            page2 = await browser.new_page()
            await page2.goto(profile_link)
            await asyncio.sleep(2)

            # External site / link
            site_link_el = await page2.query_selector("a.curator_url.ttip")
            if site_link_el:
                external_site, email_from_link = await extract_email_from_link(site_link_el)
                if email_from_link != "N/A":
                    email_found = email_from_link

            # About page inside curator page
            about_link_el = await page2.query_selector("a.about")
            if about_link_el:
                about_url = await about_link_el.get_attribute("href")
                if about_url:
                    await page2.goto(about_url)
                    await asyncio.sleep(1.5)
                    desc_el = await page2.query_selector(
                        "div.about_container div.desc, div.about_container p.tagline"
                    )
                    if desc_el:
                        text = await desc_el.inner_text()
                        possible_email = extract_email_from_text(text)
                        if possible_email != "N/A":
                            email_found = possible_email
            await page2.close()

        return {
            "curator_name": name,
            "steam_profile": profile_link,
            "followers": followers,
            "recommendation": recommendation,
            "external_site": external_site,
            "email": email_found,
            "game": app_name,
        }
    except Exception as e:
        print(f"[{name if 'name' in locals() else 'UNKNOWN'}] Error processing profile: {e}")
        return None

async def scrape_game(appid, browser, seen_profiles):
    """Scrape curators for a single game."""
    curators_data = []
    app_name = get_game_name(appid)
    url = f"https://store.steampowered.com/curators/curatorsreviewing/?appid={appid}"
    page = await browser.new_page()
    await page.goto(url)
    await page.wait_for_load_state("networkidle")

    # Scroll
    scrolls = 2 if TEST_MODE else 20
    for i in range(scrolls):
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        print(f"[{app_name}] Scrolled {i + 1} times")
        await asyncio.sleep(1.5)

    curator_divs = await page.query_selector_all("div.curator_page")
    print(f"[{app_name}] Found {len(curator_divs)} curators on page")

    for curator in curator_divs:
        name_elem = await curator.query_selector("div.name span")
        name = await name_elem.inner_text() if name_elem else "N/A"
        if name in seen_profiles:
            continue
        curator_data = await process_curator(curator, browser, app_name)
        if curator_data:
            curators_data.append(curator_data)
            seen_profiles.add(name)
            if TEST_MODE and len(curators_data) >= MAX_CURATORS_PER_GAME:
                break
    await page.close()
    return curators_data

async def main():
    seen_profiles = set()
    all_data = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        tasks = [scrape_game(appid, browser, seen_profiles) for appid in APP_IDS]
        results = await asyncio.gather(*tasks)
        for game_data in results:
            all_data.extend(game_data)
        await browser.close()

    # Save CSV
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["curator_name","steam_profile","followers",
                                               "recommendation","external_site","email","game"])
        writer.writeheader()
        writer.writerows(all_data)

    print(f"💾 Saved {len(all_data)} unique curators to {OUTPUT_FILE}")

# --- Run ---
if __name__ == "__main__":
    asyncio.run(main())
