"""
discover_channels_api.py

Discover YouTube channels related to card games, roguelike games, Steam Next Fest, and indie/demo games.
Fetch channel descriptions and extract emails using YouTube Data API v3.
Output CSV with channel info and emails.
"""

import csv
import os
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import re
from datetime import datetime

# YouTube API Key
API_KEY = 'AIzaSyDKxMNig7b0V6Ji79W8CZ_ugfM6uDYV89Y'

# Queries for discovery
QUERIES = [
    "hearthstone", "magic the gathering", "pokemon card game",
    "slay the spire", "balatro", "hades game", "binding of isaac",
    "steam next fest", "indie games", "demo games", "new games"
]

def extract_emails(text):
    """Extract email addresses from text."""
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_pattern, text)
    return list(set(emails))

def discover_channels(output_file, max_channels_per_query=50, queries=QUERIES):
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    channels = {}
    
    for query in queries:
        try:
            # Search for videos
            search_request = youtube.search().list(
                q=query,
                type='video',
                part='snippet',
                maxResults=min(max_channels_per_query, 50),
                order='relevance'
            )
            search_response = search_request.execute()
            
            for item in search_response['items']:
                channel_id = item['snippet']['channelId']
                if channel_id not in channels:
                    channels[channel_id] = {
                        'channel_name': item['snippet']['channelTitle'],
                        'channel_url': f'https://www.youtube.com/channel/{channel_id}',
                        'channel_description': '',
                        'emails': []
                    }
        except HttpError as e:
            print(f"Error searching for {query}: {e}")
            continue
    
    # Fetch descriptions for unique channels
    for channel_id, data in channels.items():
        try:
            channel_request = youtube.channels().list(
                part='snippet',
                id=channel_id
            )
            channel_response = channel_request.execute()
            if 'items' in channel_response and channel_response['items']:
                description = channel_response['items'][0]['snippet']['description']
                data['channel_description'] = description
                data['emails'] = extract_emails(description)
        except HttpError as e:
            print(f"Error fetching channel {channel_id}: {e}")
            continue
    
    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['channel_id', 'channel_name', 'channel_url', 'channel_description', 'emails']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for channel_id, data in channels.items():
            writer.writerow({
                'channel_id': channel_id,
                'channel_name': data['channel_name'],
                'channel_url': data['channel_url'],
                'channel_description': data['channel_description'],
                'emails': ';'.join(data['emails'])
            })

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', help='Single query to search (optional, overrides default list)')
    parser.add_argument('--max-channels', type=int, default=50, help='Max channels per query')
    parser.add_argument('--output', default='outputs/discovered_channels.csv', help='Output CSV file')
    args = parser.parse_args()
    
    queries = [args.query] if args.query else QUERIES
    discover_channels(args.output, args.max_channels, queries)