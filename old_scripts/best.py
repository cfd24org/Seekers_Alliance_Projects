from playwright.sync_api import sync_playwright
import csv
import time
import re
import urllib.parse

# --- CONFIG ---
GAME_ID = "2825560"  # Portal 2 by default
TEST_MODE = True  # True for short test scrolls, False for full run
MAX_SCROLLS = 2 if TEST_MODE else 20
WAIT_BETWEEN_SCROLLS = 1.5  # seconds
OUTPUT_FILE = f"curators_{GAME_ID}_{'test' if TEST_MODE else 'full'}.csv"

curator_page_url = f"https://store.steampowered.com/curators/curatorsreviewing/?appid={GAME_ID}"

# --- UTILITY TO EXTRACT EMAIL ---
# def extract_email_from_text(text):
#     if not text:
#         return "N/A"
#     match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
#     return match.group(0) if match else "N/A"

def extract_email_from_text(text):
    """Extract only the email address from a string, ignoring extra words."""
    if not text:
        return "N/A"
    # Match a standard email pattern
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return match.group(0) if match else "N/A"


def extract_email_from_link(elem):
    """Try to extract email from a <a class='curator_url'> element."""
    if not elem:
        return ("N/A", "N/A")
    href = elem.get_attribute("href") or "N/A"
    text = elem.inner_text().strip() if elem.inner_text() else ""
    email = "N/A"

    # If visible text looks like an email, use it
    if "@" in text and "." in text:
        email = text
    else:
        decoded = urllib.parse.unquote(href)
        if "mailto:" in decoded:
            email = decoded.split("mailto:")[-1]
        elif "@" in decoded:
            email = decoded  # fallback for weird encoding

    return (href, email)


# --- MAIN SCRAPER ---
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

    # Get all curator divs
    curator_divs = page.query_selector_all("div.curator_page")
    curators_data = []

    for i, curator in enumerate(curator_divs, start=1):
        # --- Basic info ---
        name_elem = curator.query_selector("div.name span")
        name = name_elem.inner_text().strip() if name_elem else "N/A"

        profile_elem = curator.query_selector("a.profile_avatar")
        profile_link = profile_elem.get_attribute("href") if profile_elem else "N/A"

        follower_elem = curator.query_selector("div.followers span")
        followers = follower_elem.inner_text().strip() if follower_elem else "N/A"

        rec_elem = curator.query_selector("span.review_direction")
        recommendation = rec_elem.inner_text().strip().upper() if rec_elem else "N/A"

        # --- Visit curator page for external link and About email ---
        external_site = "N/A"
        email_found = "N/A"

        if profile_link != "N/A":
            page2 = browser.new_page()
            page2.goto(profile_link)
            page2.wait_for_timeout(2000)

            # External site link / email
            site_link_el = page2.query_selector("a.curator_url.ttip")
            if site_link_el:
                external_site, email_from_link = extract_email_from_link(site_link_el)
                if email_from_link != "N/A":
                    email_found = email_from_link

            # --- About tab inside curator page ---
            about_link_el = page2.query_selector("a.about")
            if about_link_el:
                about_url = about_link_el.get_attribute("href")
                if about_url:
                    page2.goto(about_url)
                    page2.wait_for_timeout(1500)

                    # Look for email in the About section
                    desc_el = page2.query_selector("div.about_container div.desc, div.about_container p.tagline")
                    if desc_el:
                        text = desc_el.inner_text()
                        possible_email = extract_email_from_text(text)
                        if possible_email != "N/A":
                            email_found = possible_email

            page2.close()

        curators_data.append([
            name, profile_link, followers, recommendation, external_site, email_found
        ])
        print(f"[{i}] {name} → {email_found or external_site}")

    # --- Save to CSV ---
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["curator_name", "steam_profile", "followers", "recommendation", "external_site", "email"])
        writer.writerows(curators_data)

    print(f"💾 Saved {len(curators_data)} curators to {OUTPUT_FILE}")
    browser.close()
