from playwright.sync_api import sync_playwright
import csv
import time

curator_page_url = "https://store.steampowered.com/curators/curatorsreviewing/?appid=620"
MAX_SCROLLS = 20  # max number of scrolls
WAIT_BETWEEN_SCROLLS = 1.5  # seconds

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(curator_page_url)

    # Scroll the page
    for i in range(MAX_SCROLLS):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        print(f"Scrolled {i + 1} times")
        time.sleep(WAIT_BETWEEN_SCROLLS)

    # Grab curator names
    curator_divs = page.query_selector_all("div.curator_page div.name span")
    curators = [c.inner_text().strip() for c in curator_divs]

    print(f"Found {len(curators)} curators:")
    for c in curators[:10]:  # print first 10 for sanity check
        print("-", c)

    # Save to CSV
    with open("curators.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["curator_name"])
        for name in curators:
            writer.writerow([name])

    print("Saved curators to curators.csv")
    browser.close()
