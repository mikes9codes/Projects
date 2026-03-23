# Dining Room Chair Search 2026

Automatically searches the internet **daily** for sets of 12 dining chairs across secondary markets, design platforms, and auction houses. USA listings are highlighted separately from international ones.

## Features

- **8 sources** searched simultaneously: eBay (US + 6 international sites), Craigslist (20 US cities via RSS), Chairish, 1stDibs, Etsy, LiveAuctioneers, and Pamono
- **USA section** with all domestic listings (eBay, Craigslist, Chairish, Etsy, LiveAuctioneers)
- **International section** for listings from UK, Canada, Australia, Germany, France, Italy, and Europe
- Each listing shows: **photo**, **price**, **description**, **platform badge**, **location**, and a direct **link**
- **Filter** by price range, platform, sort order, and condition
- **Daily auto-update** via GitHub Actions (runs at 8 AM UTC)
- Manual **Refresh Now** button in the UI

## Platforms Covered

| Platform | Type | Region |
|---|---|---|
| eBay | Auction & Buy It Now | USA + UK, CA, AU, DE, FR, IT |
| Craigslist | Secondary market | 20 US cities (RSS) |
| Chairish | Design resale | USA |
| 1stDibs | Luxury / vintage | USA & International |
| Etsy | Marketplace / vintage | USA |
| LiveAuctioneers | Live auctions | USA & International |
| Pamono | European design | Europe / International |

## Setup

### Local Development

```bash
# Clone the repo
git clone https://github.com/mikes9codes/DiningRoomChairs2026.git
cd DiningRoomChairs2026
git checkout claude/dining-chair-search-tool-WF1IC

# Install dependencies
pip install -r requirements.txt

# Run one-off search and save results
python run_scraper.py

# Start the web server
python main.py
# Open http://localhost:5000
```

### GitHub Actions (Daily Auto-Update)

The workflow `.github/workflows/daily_search.yml` runs every day at 8:00 AM UTC.
It saves results to `data/results.json` and commits the file automatically.

You can also trigger it manually from the **Actions** tab.

#### Optional API Keys (GitHub Secrets)

| Secret | Purpose |
|---|---|
| `SERP_API_KEY` | Google Shopping results via SerpAPI (optional) |
| `EBAY_APP_ID` | eBay Finding API for more detailed results (optional) |

The app works without these keys — they just unlock additional data sources.

### Production Deployment

```bash
# Using gunicorn
gunicorn main:app --bind 0.0.0.0:5000 --workers 2
```

## Project Structure

```
DiningRoomChairs2026/
├── main.py                  # Flask web app + daily scheduler
├── scraper.py               # Multi-source scraper engine
├── run_scraper.py           # CLI script (used by GitHub Actions)
├── config.py                # Configuration & constants
├── requirements.txt
├── templates/
│   └── index.html           # Main UI (responsive)
├── static/
│   ├── style.css            # Styling
│   ├── app.js               # Frontend JS
│   └── placeholder.svg      # Fallback image
├── data/
│   └── results.json         # Cached search results (auto-updated)
└── .github/
    └── workflows/
        └── daily_search.yml # Daily search automation
```

## Notes

- Results are cached in `data/results.json` and refreshed daily
- Web scraping results depend on each platform's current HTML structure; the scraper handles errors gracefully
- Always verify listings directly on the source platform before purchasing
- Prices shown are at time of indexing and may have changed
