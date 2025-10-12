from playwright.sync_api import sync_playwright
import csv
import time
import urllib.parse
import re

#3112170 - dice legends
#620 - Portal 2
#646570 - slay the spire

# 🎮 CHANGE THIS TO SCRAPE A DIFFERENT GAME
APP_ID = 3112170
curator_page_url = f"https://store.steampowered.com/curators/curatorsreviewing/?appid={APP_ID}"

# ⚙️ TEST SETTINGS
TEST_MODE = False  # ⬅️ set to False for full run
MAX_SCROLLS = 2 if TEST_MODE else 20
MAX_CURATORS = 5 if TEST_MODE else None
WAIT_BETWEEN_SCROLLS = 1.2

def extract_email_from_url(url):
    if not url:
        return "N/A"
    decoded = urllib.parse.unquote(url)
    match = re.search(r"mailto:([\w\.-]+@[\w\.-]+)", decoded)
    return match.group(1) if match else "N/A"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(curator_page_url)

    for i in range(MAX_SCROLLS):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        print(f"Scrolled {i + 1} times")
        time.sleep(WAIT_BETWEEN_SCROLLS)

    curator_blocks = page.query_selector_all("div.curator_page")
    if MAX_CURATORS:
        curator_blocks = curator_blocks[:MAX_CURATORS]

    curators = []
    for idx, block in enumerate(curator_blocks, start=1):
        name_el = block.query_selector("div.name span")
        name = name_el.inner_text().strip() if name_el else "N/A"

        link_el = block.query_selector("a.profile_avatar")
        curator_link = link_el.get_attribute("href") if link_el else "N/A"

        follower_el = block.query_selector("div.followers span")
        followers = follower_el.inner_text().strip() if follower_el else "0"

        rec_el = block.query_selector("div.curations span.review_direction")
        recommendation = rec_el.inner_text().strip() if rec_el else "N/A"

        external_link, email = "N/A", "N/A"

        if curator_link != "N/A":
            try:
                curator_page = browser.new_page()
                curator_page.goto(curator_link, timeout=20000)
                curator_page.wait_for_timeout(1500)

                ext_link_el = curator_page.query_selector("a.curator_url")
                if ext_link_el:
                    external_link = ext_link_el.get_attribute("href")
                    email = extract_email_from_url(external_link)

                curator_page.close()
                print(f"[{idx}] {name} → {email if email != 'N/A' else external_link}")
            except Exception as e:
                print(f"[{idx}] Failed for {name}: {e}")

        curators.append([name, curator_link, followers, recommendation, external_link, email])

    filename = f"curators_{APP_ID}{'_test' if TEST_MODE else ''}.csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["curator_name", "steam_profile", "followers", "recommendation", "external_site", "email"])
        writer.writerows(curators)

    print(f"💾 Saved {len(curators)} curators to {filename}")
    browser.close()
