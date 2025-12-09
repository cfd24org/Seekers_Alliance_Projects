import csv

def generate_csv(youtubers, output_file):
    """
    Generates a CSV file containing YouTuber information.

    Parameters:
    youtubers (list of dict): A list of dictionaries where each dictionary contains
                               information about a YouTuber (name, bio, channel link,
                               social media accounts, emails, and recent video details).
    output_file (str): The path to the output CSV file.
    """
    if not youtubers:
        print("No YouTuber data provided.")
        return

    fieldnames = ['name', 'bio', 'channel_link', 'social_media', 'emails', 'recent_video_details']
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for youtuber in youtubers:
            writer.writerow({
                'name': youtuber.get('name', ''),
                'bio': youtuber.get('bio', ''),
                'channel_link': youtuber.get('channel_link', ''),
                'social_media': '; '.join(youtuber.get('social_media', [])),
                'emails': '; '.join(youtuber.get('emails', [])),
                'recent_video_details': youtuber.get('recent_video_details', '')
            })

    print(f"CSV file '{output_file}' generated successfully.")