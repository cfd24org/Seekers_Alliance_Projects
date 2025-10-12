import asyncio
import csv
import re
import urllib.parse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

GAME_ID = "3112170"  # Portal 2
TEST_MODE = True
MAX_SCROLLS = 2 if TEST_MODE else 20
WAIT_BETWEEN_SCROLLS = 1.5
OUTPUT_FILE = f"curators_{GAME_ID}_{'test' if TEST_MODE else 'full'}.csv"
MAX_CONCURRENT = 3  # number of parallel tabs


async def extract_email_from_text(text: str):
    """Extract the first email found in a text block."""
    if not text:
        return "N/A"
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    return match.group(0) if match else "N/A"


async def extract_email_from_link(elem):
    """Extract email from a <a class='curator_url'> element, only the address."""
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


async def process_curator(curator, browser):
    """Scrape info from a single curator block."""
    try:
        # Basic info
        name_elem = await curator.query_selector("div.name span")
        name = (await name_elem.inner_text()).strip() if name_elem else "N/A"

        profile_elem = await curator.query_selector("a.profile_avatar")
        profile_link = await profile_elem.get_attribute("href") if profile_elem else "N/A"

        follower_elem = await curator.query_selector("div.followers span")
        followers = (await follower_elem.inner_text()).strip() if follower_elem else "N/A"

        rec_elem = await curator.query_selector("span.review_direction")
        recommendation = (await rec_elem.inner_text()).strip().upper() if rec_elem else "N/A"

        external_site = "N/A"
        email_found = "N/A"

        if profile_link != "N/A":
            page2 = await browser.new_page()
            try:
                await page2.goto(profile_link, timeout=15000)

                # External link under profile name
                site_link_el = await page2.query_selector("a.curator_url.ttip")
                if site_link_el:
                    external_site, email_from_link = await extract_email_from_link(site_link_el)
                    if email_from_link != "N/A":
                        email_found = email_from_link

                # About section inside curator page
                about_link_el = await page2.query_selector("a.about")
                if about_link_el:
                    about_url = await about_link_el.get_attribute("href")
                    if about_url:
                        await page2.goto(about_url, timeout=15000)
                        desc_el = await page2.query_selector(
                            "div.about_container div.desc, div.about_container p.tagline"
                        )
                        if desc_el:
                            text = await desc_el.inner_text()
                            possible_email = await extract_email_from_text(text)
                            if possible_email != "N/A":
                                email_found = possible_email
            except PlaywrightTimeoutError:
                print(f"[{name}] Timeout on profile page")
            finally:
                await page2.close()

        return {
            "curator_name": name,
            "steam_profile": profile_link,
            "followers": followers,
            "recommendation": recommendation,
            "external_site": external_site,
            "email": email_found,
        }

    except Exception as e:
        print(f"[{name if 'name' in locals() else 'N/A'}] Error processing profile: {e}")
        return {
            "curator_name": name if 'name' in locals() else "N/A",
            "steam_profile": profile_link if 'profile_link' in locals() else "N/A",
            "followers": followers if 'followers' in locals() else "N/A",
            "recommendation": recommendation if 'recommendation' in locals() else "N/A",
            "external_site": "N/A",
            "email": "N/A",
        }


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        curator_page_url = f"https://store.steampowered.com/curators/curatorsreviewing/?appid={GAME_ID}"
        await page.goto(curator_page_url)
        await page.wait_for_load_state("networkidle")

        # Scroll the page
        for i in range(MAX_SCROLLS):
            await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            print(f"Scrolled {i + 1} times")
            await asyncio.sleep(WAIT_BETWEEN_SCROLLS)

        # Grab curator blocks
        curator_divs = await page.query_selector_all("div.curator_page")
        print(f"Found {len(curator_divs)} curators on page")

        # Process with concurrency
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        async def sem_task(curator):
            async with semaphore:
                return await process_curator(curator, browser)

        tasks = [sem_task(c) for c in curator_divs]
        results = await asyncio.gather(*tasks)

        # Save CSV
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["curator_name", "steam_profile", "followers", "recommendation", "external_site", "email"])
            writer.writeheader()
            writer.writerows(results)

        print(f"💾 Saved {len(results)} curators to {OUTPUT_FILE}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
