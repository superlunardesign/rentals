# Rental Property Search - Tumwater/Olympia, WA

A Python web scraper and dashboard for finding rental properties in the Tumwater/Olympia area.

## Features

- **Automated Scraping**: Scrapes multiple property management websites hourly
- **Smart Matching**: Categorizes listings into tiers based on your preferences:
  - **Best Match**: Within budget, within radius, has preferred keywords
  - **Match**: Within budget and radius
  - **Flexible**: Slightly over budget or further away
- **Keyword Tagging**: Highlights listings with features you want (office, fence, garage, etc.)
- **Web Dashboard**: Easy-to-use interface for browsing listings
- **Favorites & Hiding**: Mark favorites and hide listings you're not interested in

## Quick Start

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Your Preferences

Edit `config.yaml` to set:
- Your budget (`budget.max_rent`)
- Location radius (`location.radius_miles`)
- Minimum bedrooms/sqft (`rooms.*`)
- Preferred keywords (`keywords.preferred`)
- Dealbreaker keywords (`keywords.dealbreakers`)

### 3. Run the Application

```bash
# Start the web dashboard with automatic hourly scraping
python main.py

# Or run a one-time scrape
python main.py --scrape

# Start dashboard without auto-scraping
python main.py --no-schedule
```

Then open http://127.0.0.1:8000 in your browser.

## Configuration

### Budget Settings

```yaml
budget:
  max_rent: 1800        # Your maximum monthly rent
  flexible_buffer: 150  # Show "Flexible" listings up to this much over
```

### Location Settings

```yaml
location:
  center_zip: "98512"
  radius_miles: 15          # Primary search radius
  flexible_radius_miles: 20 # Extended radius for "Flexible" tier
```

### Keywords

```yaml
keywords:
  preferred:      # Boost to "Best Match" if present
    - office
    - fence
    - garage
  dealbreakers:   # Hide listings with these
    - shared
    - no pets
```

## Adding New Property Sources

1. Add the source to `config.yaml`:

```yaml
sources:
  - name: "New Property Manager"
    scraper: "newpm"
    url: "https://example.com/rentals"
    enabled: true
```

2. Create a scraper in `src/scrapers/newpm.py`:

```python
from .base import BaseScraper, ScrapedListing

class NewPMScraper(BaseScraper):
    def __init__(self, url):
        super().__init__(source_name="newpm", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        # Your scraping logic here
        pass
```

3. Register it in `src/scrapers/__init__.py`

## Project Structure

```
rentals/
├── main.py              # Application entry point
├── config.yaml          # Your preferences
├── requirements.txt     # Python dependencies
├── src/
│   ├── api/            # FastAPI routes
│   ├── models/         # Database models
│   ├── scrapers/       # Site-specific scrapers
│   ├── services/       # Business logic
│   ├── templates/      # HTML templates
│   ├── config.py       # Config loader
│   └── scheduler.py    # Background job scheduler
└── data/
    └── rentals.db      # SQLite database (auto-created)
```

## License

MIT
