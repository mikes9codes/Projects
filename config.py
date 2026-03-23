"""Configuration for Dining Room Chair Search 2026"""
import os

# Search query
SEARCH_QUERY = "set of 12 dining chairs"

# Data storage
DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'results.json')

# Request settings
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1.5  # seconds between requests

# Optional: SerpAPI key for Google Shopping results
SERP_API_KEY = os.environ.get('SERP_API_KEY', '')

# Optional: eBay App ID for Finding API
EBAY_APP_ID = os.environ.get('EBAY_APP_ID', '')

# Craigslist cities to search (city_code, display_name)
CRAIGSLIST_CITIES = [
    ('newyork', 'New York, NY'),
    ('losangeles', 'Los Angeles, CA'),
    ('chicago', 'Chicago, IL'),
    ('houston', 'Houston, TX'),
    ('phoenix', 'Phoenix, AZ'),
    ('sfbay', 'San Francisco Bay Area, CA'),
    ('seattle', 'Seattle, WA'),
    ('miami', 'Miami, FL'),
    ('boston', 'Boston, MA'),
    ('denver', 'Denver, CO'),
    ('atlanta', 'Atlanta, GA'),
    ('dallas', 'Dallas, TX'),
    ('portland', 'Portland, OR'),
    ('minneapolis', 'Minneapolis, MN'),
    ('sandiego', 'San Diego, CA'),
    ('detroit', 'Detroit, MI'),
    ('nashville', 'Nashville, TN'),
    ('austin', 'Austin, TX'),
    ('charlotte', 'Charlotte, NC'),
    ('lasvegas', 'Las Vegas, NV'),
]

# International eBay sites
INTL_EBAY_SITES = [
    ('https://www.ebay.co.uk', 'UK'),
    ('https://www.ebay.ca', 'Canada'),
    ('https://www.ebay.com.au', 'Australia'),
    ('https://www.ebay.de', 'Germany'),
    ('https://www.ebay.fr', 'France'),
    ('https://www.ebay.it', 'Italy'),
]

# Source type labels
SOURCE_TYPES = {
    'eBay': 'auction/marketplace',
    'Craigslist': 'secondary market',
    'Chairish': 'design resale',
    '1stDibs': 'luxury/design',
    'Etsy': 'marketplace/vintage',
    'LiveAuctioneers': 'auction',
}
