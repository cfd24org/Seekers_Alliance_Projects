from playwright.sync_api import sync_playwright
import csv
import time

curator_page_url = "https://store.steampowered.com/curators/curatorsreviewing/?appid=620"
MAX_SCROLLS = 20
WAIT_BETWEEN_SCROLLS = 1.5

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(curator_page_url)

    # Scroll down multiple times to load more curators
    for i in range(MAX_SCROLLS):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        print(f"Scrolled {i + 1} times")
        time.sleep(WAIT_BETWEEN_SCROLLS)

    # Select each curator block
    curator_blocks = page.query_selector_all("div.curator_page")

    curators = []
    for block in curator_blocks:
        # name
        name_el = block.query_selector("div.name span")
        name = name_el.inner_text().strip() if name_el else "N/A"

        # profile link
        link_el = block.query_selector("a.profile_avatar")
        link = link_el.get_attribute("href") if link_el else "N/A"

        # follower count
        follower_el = block.query_selector("div.followers span")
        followers = follower_el.inner_text().strip() if follower_el else "0"

        # recommendation status
        rec_el = block.query_selector("div.curations span.review_direction")
        recommendation = rec_el.inner_text().strip() if rec_el else "N/A"

        curators.append([name, link, followers, recommendation])

    print(f"✅ Found {len(curators)} curators")

    # sanity check printout
    for c in curators[:10]:
        print(c)

    # Save to CSV
    with open("curators_detailed.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["curator_name", "profile_link", "followers", "recommendation"])
        writer.writerows(curators)

    print("💾 Saved curators_detailed.csv")
    browser.close()
