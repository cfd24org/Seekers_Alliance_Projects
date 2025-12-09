import csv
import os
import pytest

from src.generate_csv import generate_csv

def test_generate_csv(tmp_path):
    # Sample data for testing
    youtubers = [
        {
            'name': 'YouTuber One',
            'bio': 'This is a bio for YouTuber One.',
            'channel_link': 'https://www.youtube.com/channel/UC1',
            'social_media': {
                'twitter': 'https://twitter.com/youtuberone',
                'instagram': 'https://instagram.com/youtuberone',
            },
            'email': 'youtuberone@example.com',
            'recent_video': {
                'title': 'Recent Video One',
                'url': 'https://www.youtube.com/watch?v=video1',
            }
        },
        {
            'name': 'YouTuber Two',
            'bio': 'This is a bio for YouTuber Two.',
            'channel_link': 'https://www.youtube.com/channel/UC2',
            'social_media': {
                'twitter': 'https://twitter.com/youtubertwo',
                'instagram': 'https://instagram.com/youtubertwo',
            },
            'email': 'youtubertwo@example.com',
            'recent_video': {
                'title': 'Recent Video Two',
                'url': 'https://www.youtube.com/watch?v=video2',
            }
        }
    ]

    # Define the expected CSV output
    expected_output = [
        ['Name', 'Bio', 'Channel Link', 'Twitter', 'Instagram', 'Email', 'Recent Video Title', 'Recent Video URL'],
        ['YouTuber One', 'This is a bio for YouTuber One.', 'https://www.youtube.com/channel/UC1', 'https://twitter.com/youtuberone', 'https://instagram.com/youtuberone', 'youtuberone@example.com', 'Recent Video One', 'https://www.youtube.com/watch?v=video1'],
        ['YouTuber Two', 'This is a bio for YouTuber Two.', 'https://www.youtube.com/channel/UC2', 'https://twitter.com/youtubertwo', 'https://instagram.com/youtubertwo', 'youtubertwo@example.com', 'Recent Video Two', 'https://www.youtube.com/watch?v=video2'],
    ]

    # Create a temporary CSV file path
    csv_file_path = tmp_path / "test_youtubers.csv"

    # Generate the CSV
    generate_csv(youtubers, csv_file_path)

    # Read the generated CSV and verify its contents
    with open(csv_file_path, mode='r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        output = list(reader)

    assert output == expected_output