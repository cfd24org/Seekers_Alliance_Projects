from playwright.sync_api import sync_playwright
import re
import time

def debug_curator_link(playwright, game_url):
    browser = playwright.chromium.launch(headless=False)  # headless=False so you can watch it
    page = browser.new_page()
    print(f"\n🔍 Opening {game_url}")
    page.goto(game_url)
    page.wait_for_load_state("networkidle")

    # Scroll gradually to bottom to ensure lazy-loaded content appears
    for i in range(5):
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
        time.sleep(1)

    # Final scroll to bottom and wait a bit
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(5000)

    html = page.content()

    # Save full HTML for inspection
    with open("portal2_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("💾 Saved page source to portal2_debug.html")

    # Print last part of the HTML to console
    print("\n--- LAST 1000 CHARACTERS OF HTML ---\n")
    print(html[-1000:])
    print("\n------------------------------------\n")

    # Try to match the curator link
    match = re.search(r'https://store\.steampowered\.com/curator/curatorlist/app/\d+/', html)
    if match:
        print(f"✅ Found curator list link: {match.group(0)}")
    else:
        print("❌ Could not find curator link in HTML.")
    browser.close()


def main():
    game_url = "https://store.steampowered.com/app/620/Portal_2/"
    with sync_playwright() as playwright:
        debug_curator_link(playwright, game_url)


if __name__ == "__main__":
    main()
