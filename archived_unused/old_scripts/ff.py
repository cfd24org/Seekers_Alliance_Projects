import csv
from playwright.sync_api import sync_playwright
import time

# ---------- CONFIG ----------
GAME_CURATOR_LINKS = {
    "Portal 2": "https://store.steampowered.com/curators/curatorsreviewing/?appid=620",
    "CS:GO": "https://store.steampowered.com/curators/curatorsreviewing/?appid=730",
    "Dota 2": "https://store.steampowered.com/curators/curatorsreviewing/?appid=570",
}

OUTPUT_CSV = "curators_full.csv"
# -----------------------------

def scrape_curator_page(page, curator_url):
    """Scrape info from individual curator page."""
    page.goto(curator_url)
    page.wait_for_timeout(2000)  # wait 2s for page to load

    # Example fields: name, followers
    name = page.query_selector('h2.pageheader_name')  # update selector if needed
    name_text = name.inner_text().strip() if name else ""

    followers = page.query_selector('div.pageheader_follower_count')  # update selector
    followers_text = followers.inner_text().strip() if followers else ""

    # Add more fields here if you want
    return {
        "curator_name": name_text,
        "followers": followers_text,
        "curator_url": curator_url
    }

def scrape_curators_for_game(browser, game_name, curator_page_url):
    page = browser.new_page()
    page.goto(curator_page_url)
    time.sleep(2)  # let page load JS

    curators = []

    # Each curator block
    curator_blocks = page.query_selector_all('div.curator_block')  # update selector
    for block in curator_blocks:
        # Name
        name_el = block.query_selector('a')  # usually first <a> is curator name
        if name_el:
            name = name_el.inner_text().strip()
            link = name_el.get_attribute('href')
            curators.append({
                "game_name": game_name,
                "curator_name": name,
                "curator_url": link
            })

    page.close()
    return curators

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        all_curators = []

        for game, link in GAME_CURATOR_LINKS.items():
            print(f"Scraping curators for {game}...")
            curators = scrape_curators_for_game(browser, game, link)
            all_curators.extend(curators)

        # Save to CSV
        keys = ["game_name", "curator_name", "curator_url"]
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_curators)

        browser.close()
        print(f"✅ Done! Saved {len(all_curators)} curators to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
