# youtube-contacts-scraper

## Overview
The YouTube Contacts Scraper is a Python project designed to discover YouTubers based on specific search queries and generate a CSV file containing their names, bios, channel links, social media accounts, emails, and details of their most recent YouTube videos. This project utilizes web scraping techniques to gather the necessary information from YouTube.

## Project Structure
```
youtube-contacts-scraper/
├── src/
│   ├── discover_youtubers.py  # Script for discovering YouTubers
│   ├── generate_csv.py         # Script for generating CSV files
│   ├── yt_utils.py             # Utility functions for web scraping
│   └── __init__.py             # Package initialization
├── tests/
│   ├── test_discover.py        # Unit tests for discover_youtubers.py
│   └── test_generate_csv.py     # Unit tests for generate_csv.py
├── requirements.txt             # Project dependencies
├── pyproject.toml               # Project configuration
├── .gitignore                   # Files to ignore in version control
└── README.md                    # Project documentation
```

## Usage
1. **Install Dependencies**: Ensure you have the required libraries by installing them via pip:
   ```
   pip install -r requirements.txt
   ```

2. **Discover YouTubers**: Run the `discover_youtubers.py` script with the desired search query to find YouTubers.
   ```
   python src/discover_youtubers.py --query "your search query"
   ```

3. **Generate CSV**: Use the `generate_csv.py` script to create a CSV file from the discovered YouTubers' data.
   ```
   python src/generate_csv.py --input "input_file.json" --output "output_file.csv"
   ```

## Contributing
Contributions are welcome! Please feel free to submit a pull request or open an issue for any enhancements or bug fixes.

## License
This project is licensed under the MIT License - see the LICENSE file for details.