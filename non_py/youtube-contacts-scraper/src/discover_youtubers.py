#!/usr/bin/env python3
"""
discover_youtubers.py

This script is responsible for discovering YouTubers based on a search query.
It uses web scraping techniques to gather information about channels, including
names, bios, and links.

Usage:
  python discover_youtubers.py --query "your search query"

Requirements: 
  - playwright (and browsers installed via `python -m playwright install`)

Notes:
- This script uses Playwright for reliable page rendering.
"""

import argparse
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from yt_utils import extract_links_and_emails, normalize_url

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

def discover_youtubers(query):
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        
        try:
            page.goto(search_url, timeout=30000)
            page.wait_for_selector('ytd-channel-renderer', timeout=8000)
        except PlaywrightTimeoutError:
            print('Search page load timeout')
            return results

        channel_links = page.query_selector_all('ytd-channel-renderer a#main-link')
        for channel in channel_links:
            channel_url = channel.get_attribute('href')
            channel_name = channel.inner_text().strip()
            results.append({'name': channel_name, 'url': normalize_url('https://www.youtube.com', channel_url)})

        browser.close()
    return results

def main():
    parser = argparse.ArgumentParser(description='Discover YouTubers based on a search query.')
    parser.add_argument('--query', required=True, help='Search query to discover YouTubers')
    args = parser.parse_args()

    youtubers = discover_youtubers(args.query)
    for youtuber in youtubers:
        print(f"Name: {youtuber['name']}, URL: {youtuber['url']}")

if __name__ == '__main__':
    main()