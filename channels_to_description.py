"""
channels_to_description.py

Script to add channel descriptions to a CSV of YouTube channels.

Input CSV columns: video_url, video_title, channel_url, channel_name
Output CSV adds: channel_description

Uses Playwright to visit each channel_url, click to open the About popup, and extract the description.
"""

import csv
import argparse
import os
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'


def dismiss_youtube_consent(page, timeout=2000):
    candidates = [
        'button:has-text("Reject all")',
        'button:has-text("Reject")',
        'button:has-text("Reject all cookies")',
        'button:has-text("No, thanks")',
        'button:has-text("No, thanks.")',
        'button:has-text("Rechazar todo")',
        'button:has-text("No aceptar")',
        'tp-yt-paper-button:has-text("Reject all")',
        'tp-yt-paper-button:has-text("Reject")',
        'tp-yt-paper-button:has-text("Rechazar todo")',
        'ytd-button-renderer:has-text("Reject all")',
    ]
    for sel in candidates:
        try:
            btn = page.query_selector(sel)
            if btn:
                btn.click()
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    # JS fallback
    try:
        clicked = page.evaluate(r"""
            () => {
                const texts = ["reject all","reject","rechazar todo","no aceptar","no, thanks","reject all cookies"];
                const nodes = Array.from(document.querySelectorAll('button, a, tp-yt-paper-button, ytd-button-renderer'));
                for (const n of nodes) {
                    try:
                        const t = (n.innerText || '').toLowerCase().trim();
                        for (const tt of texts) {
                            if (t === tt || t.includes(tt)) { n.click(); return true; }
                        }
                    } catch(e) { continue; }
                }
                return false;
            }
        """)
        if clicked:
            page.wait_for_timeout(500)
    except Exception:
        pass
    return False


def _expand_truncated_description(page):
    """Click to open the description popup."""
    try:
        desc_preview = page.query_selector('yt-description-preview-view-model')
        if desc_preview:
            desc_preview.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            bbox = desc_preview.bounding_box()
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] - 10)
            else:
                desc_preview.click(force=True)
            page.wait_for_timeout(1000)
            return True
    except Exception:
        pass
    return False


def extract_description(channel_url, page):
    """Extract description from the About popup."""
    description = ''
    try:
        page.goto(channel_url, timeout=25000)
        page.wait_for_load_state('networkidle', timeout=10000)
        dismiss_youtube_consent(page)
        _expand_truncated_description(page)
        desc_element = page.query_selector('tp-yt-paper-dialog yt-attributed-string#description-container span.yt-core-attributed-string')
        if desc_element:
            description = desc_element.text_content().strip()
        # Close popup
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
    except Exception:
        pass
    return description


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='Input CSV file')
    parser.add_argument('--output', required=True, help='Output CSV file')
    parser.add_argument('--no-headless', action='store_true', help='Run in non-headless mode')
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.no_headless)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        with open(args.input, 'r', encoding='utf-8') as infile, open(args.output, 'w', newline='', encoding='utf-8') as outfile:
            lines = infile.readlines()
            # Skip comment lines starting with #
            data_lines = [line for line in lines if not line.strip().startswith('#')]
            from io import StringIO
            data_io = StringIO(''.join(data_lines))
            reader = csv.DictReader(data_io)
            writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames + ['channel_description'])
            writer.writeheader()

            for row in reader:
                channel_url = row['channel_url']
                description = extract_description(channel_url, page)
                row['channel_description'] = description
                writer.writerow(row)

        context.close()
        browser.close()


if __name__ == '__main__':
    main()