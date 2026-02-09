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
from datetime import datetime, timedelta

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

def extract_links(text):
    """Extract URLs from text."""
    url_pattern = r'https?://[^\s]+'
    links = re.findall(url_pattern, text)
    return list(set(links))

def discover_channels(output_file, max_total=1000, queries=None, include_recent_date=False, include_avg_views=False):
    if queries is None:
        queries = QUERIES
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    channels = {}
    total_channels = 0
    
    # Collect channels (cost: 100 units per search page)
    for query in queries:
        if total_channels >= max_total:
            break
        page_token = None
        while total_channels < max_total:
            try:
                search_request = youtube.search().list(
                    q=query,
                    type='video',
                    part='snippet',
                    maxResults=50,
                    order='relevance',
                    pageToken=page_token
                )
                search_response = search_request.execute()
                
                for item in search_response['items']:
                    channel_id = item['snippet']['channelId']
                    if channel_id not in channels:
                        channels[channel_id] = {
                            'channel_name': item['snippet']['channelTitle'],
                            'channel_url': f'https://www.youtube.com/channel/{channel_id}',
                            'channel_description': '',
                            'emails': [],
                            'links': [],
                            'subscribers': 'N/A',
                            'recent_video_date': 'N/A',
                            'avg_views_last_month': 'N/A'
                        }
                        total_channels += 1
                        if total_channels >= max_total:
                            break
                
                page_token = search_response.get('nextPageToken')
                if not page_token or total_channels >= max_total:
                    break
            except HttpError as e:
                print(f"Error searching for {query}: {e}")
                break
    
    # Fetch descriptions and stats for unique channels (cost: 1 unit per channel for snippet/statistics)
    for channel_id, data in list(channels.items())[:max_total]:
        try:
            channel_request = youtube.channels().list(
                part='snippet,statistics',
                id=channel_id
            )
            channel_response = channel_request.execute()
            if 'items' in channel_response and channel_response['items']:
                item = channel_response['items'][0]
                description = item['snippet']['description']
                data['channel_description'] = description
                data['emails'] = extract_emails(description)
                data['links'] = extract_links(description)
                data['subscribers'] = item.get('statistics', {}).get('subscriberCount', 'N/A')
                
                if include_recent_date:
                    # Get most recent video date (cost: 100 units)
                    recent_request = youtube.search().list(
                        channelId=channel_id,
                        type='video',
                        part='snippet',
                        order='date',
                        maxResults=1
                    )
                    recent_response = recent_request.execute()
                    if recent_response['items']:
                        data['recent_video_date'] = recent_response['items'][0]['snippet']['publishedAt']
                
                if include_avg_views:
                    # Get average views last month (cost: ~100-500 units)
                    one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
                    views_request = youtube.search().list(
                        channelId=channel_id,
                        type='video',
                        part='id',
                        publishedAfter=one_month_ago,
                        maxResults=50
                    )
                    views_response = views_request.execute()
                    video_ids = [item['id']['videoId'] for item in views_response['items']]
                    if video_ids:
                        videos_request = youtube.videos().list(
                            part='statistics',
                            id=','.join(video_ids)
                        )
                        videos_response = videos_request.execute()
                        total_views = sum(int(video['statistics'].get('viewCount', 0)) for video in videos_response['items'])
                        data['avg_views_last_month'] = total_views / len(videos_response['items']) if videos_response['items'] else 'N/A'
        except HttpError as e:
            print(f"Error fetching channel {channel_id}: {e}")
            continue
    
    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['channel_id', 'channel_name', 'channel_url', 'channel_description', 'emails', 'links', 'subscribers', 'recent_video_date', 'avg_views_last_month']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for channel_id, data in channels.items():
            writer.writerow({
                'channel_id': channel_id,
                'channel_name': data['channel_name'],
                'channel_url': data['channel_url'],
                'channel_description': data['channel_description'],
                'emails': ';'.join(data['emails']),
                'links': ';'.join(data['links']),
                'subscribers': data['subscribers'],
                'recent_video_date': data['recent_video_date'],
                'avg_views_last_month': data['avg_views_last_month']
            })

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', help='Single query to search (optional, overrides default list)')
    parser.add_argument('--max-channels', type=int, default=1000, help='Max total channels to collect')
    parser.add_argument('--output', default='outputs/discovered_channels.csv', help='Output CSV file')
    parser.add_argument('--include-recent-date', action='store_true', help='Include most recent video date (costs ~100 units per channel)')
    parser.add_argument('--include-avg-views', action='store_true', help='Include average views last month (costs ~100-500 units per channel)')
    args = parser.parse_args()
    
    queries = [args.query] if args.query else QUERIES
    discover_channels(args.output, args.max_channels, queries, args.include_recent_date, args.include_avg_views)