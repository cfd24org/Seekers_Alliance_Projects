from playwright.sync_api import sync_playwright
import csv
import time
import urllib.parse

# --- CONFIG ---
GAME_ID = "3112170"  # Portal 2 by default
TEST_MODE = False  # set False for full run
MAX_SCROLLS = 2 if TEST_MODE else 20
WAIT_BETWEEN_SCROLLS = 1.5  # seconds
OUTPUT_FILE = f"curators_{GAME_ID}_{'test' if TEST_MODE else 'full'}.csv"

curator_page_url = f"https://store.steampowered.com/curators/curatorsreviewing/?appid={GAME_ID}"

def extract_email_from_link(elem):
    """Try to extract email from a <a class='curator_url'> element."""
    if not elem:
        return ("N/A", "N/A")

    href = elem.get_attribute("href") or "N/A"
    text = elem.inner_text().strip() if elem.inner_text() else ""
    email = "N/A"

    # If the visible text looks like an email, use it
    if "@" in text and "." in text:
        email = text
    else:
        decoded = urllib.parse.unquote(href)
        if "mailto:" in decoded:
            email = decoded.split("mailto:")[-1]
        elif "@" in decoded:
            email = decoded  # fallback if broken encoding like &40gmail

    return (href, email)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(curator_page_url)
    page.wait_for_load_state("networkidle")

    # Scroll the page
    for i in range(MAX_SCROLLS):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        print(f"Scrolled {i + 1} times")
        time.sleep(WAIT_BETWEEN_SCROLLS)

    curator_divs = page.query_selector_all("div.curator_page")
    curators_data = []

    for i, curator in enumerate(curator_divs, start=1):
        name_elem = curator.query_selector("div.name span")
        name = name_elem.inner_text().strip() if name_elem else "N/A"

        profile_link_elem = curator.query_selector("a.profile_avatar")
        profile_link = profile_link_elem.get_attribute("href") if profile_link_elem else "N/A"

        follower_elem = curator.query_selector("div.followers span")
        followers = follower_elem.inner_text().strip() if follower_elem else "N/A"

        rec_elem = curator.query_selector("span.review_direction")
        recommendation = rec_elem.inner_text().strip().upper() if rec_elem else "N/A"

        # Visit curator page for external link/email
        external_site, email = ("N/A", "N/A")
        if profile_link != "N/A":
            try:
                curator_tab = browser.new_page()
                curator_tab.goto(profile_link, timeout=30000)
                curator_tab.wait_for_load_state("domcontentloaded")

                link_elem = curator_tab.query_selector("a.curator_url")
                external_site, email = extract_email_from_link(link_elem)
                curator_tab.close()

            except Exception as e:
                print(f"⚠️ Error visiting {profile_link}: {e}")

        curators_data.append([name, profile_link, followers, recommendation, external_site, email])
        print(f"[{i}] {name} → {external_site} | {email}")

    # Save to CSV
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["curator_name", "steam_profile", "followers", "recommendation", "external_site", "email"])
        writer.writerows(curators_data)

    print(f"💾 Saved {len(curators_data)} curators to {OUTPUT_FILE}")
    browser.close()
