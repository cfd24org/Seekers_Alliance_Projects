from playwright.sync_api import sync_playwright
import csv
import time
import urllib.parse
import re

curator_page_url = "https://store.steampowered.com/curators/curatorsreviewing/?appid=620"
MAX_SCROLLS = 20
WAIT_BETWEEN_SCROLLS = 1.5

def extract_email_from_url(url):
    """Try to decode a Steam mailto redirect into an actual email."""
    if not url:
        return "N/A"
    decoded = urllib.parse.unquote(url)
    match = re.search(r"mailto:([\w\.-]+@[\w\.-]+)", decoded)
    return match.group(1) if match else "N/A"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(curator_page_url)

    # Scroll to load curators
    for i in range(MAX_SCROLLS):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        print(f"Scrolled {i + 1} times")
        time.sleep(WAIT_BETWEEN_SCROLLS)

    curator_blocks = page.query_selector_all("div.curator_page")
    curators = []

    for idx, block in enumerate(curator_blocks, start=1):
        # name
        name_el = block.query_selector("div.name span")
        name = name_el.inner_text().strip() if name_el else "N/A"

        # Steam curator profile link
        link_el = block.query_selector("a.profile_avatar")
        curator_link = link_el.get_attribute("href") if link_el else "N/A"

        # follower count
        follower_el = block.query_selector("div.followers span")
        followers = follower_el.inner_text().strip() if follower_el else "0"

        # recommendation
        rec_el = block.query_selector("div.curations span.review_direction")
        recommendation = rec_el.inner_text().strip() if rec_el else "N/A"

        external_link = "N/A"
        email = "N/A"

        if curator_link != "N/A":
            try:
                curator_page = browser.new_page()
                curator_page.goto(curator_link, timeout=20000)
                curator_page.wait_for_timeout(2000)

                # find external site link
                ext_link_el = curator_page.query_selector("a.curator_url")
                if ext_link_el:
                    external_link = ext_link_el.get_attribute("href")
                    email = extract_email_from_url(external_link)

                curator_page.close()
                print(f"[{idx}] {name} → {email if email != 'N/A' else external_link}")
            except Exception as e:
                print(f"[{idx}] Failed for {name}: {e}")

        curators.append([name, curator_link, followers, recommendation, external_link, email])

    # Save to CSV
    with open("curators_full.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["curator_name", "steam_profile", "followers", "recommendation", "external_site", "email"])
        writer.writerows(curators)

    print(f"💾 Saved {len(curators)} curators to curators_full.csv")
    browser.close()
