import csv
import os

def merge_csvs(run1_path, run2_path, output_path):
    channels = {}
    
    # Load run1
    if os.path.exists(run1_path):
        with open(run1_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                channel_id = row.get('channel_id')
                if channel_id:
                    channels[channel_id] = row
    
    # Load run2 and merge
    if os.path.exists(run2_path):
        with open(run2_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                channel_id = row.get('channel_id')
                if channel_id and channel_id not in channels:
                    channels[channel_id] = row
    
    # Write merged to output
    if channels:
        fieldnames = list(channels[next(iter(channels))].keys())
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in channels.values():
                writer.writerow(row)
        print(f"Merged CSV created at {output_path}")
    else:
        print("No data to merge.")

if __name__ == '__main__':
    merge_csvs('outputs/run1.csv', 'outputs/run2.csv', 'outputs/run3.csv')