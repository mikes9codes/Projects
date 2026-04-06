#!/usr/bin/env python3
"""Multi-source scraper for sets of 12 dining chairs.

Primary sources (API-based, reliable):
  - SerpAPI Google Shopping
  - SerpAPI eBay search
  - eBay Finding API

Fallback / supplemental sources (HTML scraping):
  - Craigslist RSS, Chairish, 1stDibs
  - Auction houses: Sotheby's, Christie's, Phillips, Doyle, Heritage, Wright20
  - High-end retail: Rove Concepts, Perigold, Triode Design, Ormond Editions,
    Collection Particuliere, Mary Ratcliffe Studio, Studio Twenty Seven,
    The Invisible Collection, Miyazaki Chair
"""

import hashlib
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus, urlencode

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SERP_API_KEY = os.environ.get('SERP_API_KEY', '')
EBAY_APP_ID  = os.environ.get('EBAY_APP_ID', '')

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

CRAIGSLIST_CITIES = [
    ('newyork', 'New York, NY'), ('losangeles', 'Los Angeles, CA'),
    ('chicago', 'Chicago, IL'), ('houston', 'Houston, TX'),
    ('phoenix', 'Phoenix, AZ'), ('sfbay', 'San Francisco Bay Area, CA'),
    ('seattle', 'Seattle, WA'), ('miami', 'Miami, FL'),
    ('boston', 'Boston, MA'), ('denver', 'Denver, CO'),
    ('atlanta', 'Atlanta, GA'), ('dallas', 'Dallas, TX'),
    ('portland', 'Portland, OR'), ('minneapolis', 'Minneapolis, MN'),
    ('sandiego', 'San Diego, CA'), ('detroit', 'Detroit, MI'),
    ('nashville', 'Nashville, TN'), ('austin', 'Austin, TX'),
    ('charlotte', 'Charlotte, NC'), ('lasvegas', 'Las Vegas, NV'),
]

INTL_EBAY_SITES = [
    ('https://www.ebay.co.uk', 'UK'),
    ('https://www.ebay.ca', 'Canada'),
    ('https://www.ebay.com.au', 'Australia'),
    ('https://www.ebay.de', 'Germany'),
    ('https://www.ebay.fr', 'France'),
    ('https://www.ebay.it', 'Italy'),
]

US_STATE_ABBRS = {
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN',
    'IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV',
    'NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN',
    'TX','UT','VT','VA','WA','WV','WI','WY','DC',
}

US_CITIES = {
    'new york','los angeles','chicago','houston','phoenix','philadelphia',
    'san antonio','san diego','dallas','san jose','austin','jacksonville',
    'fort worth','columbus','charlotte','indianapolis','san francisco',
    'seattle','denver','nashville','oklahoma city','el paso','washington',
    'boston','portland','las vegas','memphis','louisville','baltimore',
    'milwaukee','albuquerque','tucson','fresno','sacramento','mesa',
    'atlanta','omaha','colorado springs','raleigh','long beach','miami',
    'minneapolis','tampa','tulsa','arlington','new orleans','cleveland',
}

# ---------------------------------------------------------------------------
# Filter constants
# ---------------------------------------------------------------------------

# Style keywords to exclude (antique/period pieces not wanted)
# Matches: antique, georgian, louis, louis xiv, louis xv, louis xvi, etc.
EXCLUDED_STYLE_RE = re.compile(
    r'\b(antique|georgian|louis(\s+(xiii|xiv|xv|xvi|xvii|xviii|xix|xx|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i))?)\b',
    re.IGNORECASE
)

# Mass-market retailer domains to exclude
EXCLUDED_DOMAINS = frozenset([
    'bedbathandbeyond.com',
    'target.com',
    'homedepot.com',
    'walmart.com',
    'bestbuy.com',
])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:14]


def parse_price(s: str) -> float | None:
    if not s:
        return None
    s = re.sub(r'[^\d.]', '', s.replace(',', ''))
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def is_usa(location: str) -> bool:
    if not location:
        return False
    loc = location.lower().strip()
    if any(x in loc for x in ('united states', 'usa', 'u.s.a')):
        return True
    for abbr in US_STATE_ABBRS:
        if re.search(r'\b' + abbr + r'\b', location):
            return True
    for city in US_CITIES:
        if city in loc:
            return True
    if re.search(r'\b\d{5}\b', location):
        return True
    return False


def _get(url: str, timeout: int = 15, params: dict = None) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        logger.warning(f'GET {url} failed: {e}')
        return None


def _make_listing(**kwargs) -> dict:
    loc = kwargs.get('location', '')
    usa_flag = kwargs.get('is_usa', is_usa(loc))
    price_str = kwargs.get('price', 'See listing')
    return {
        'id': kwargs.get('id', _id(kwargs.get('listing_url', '') or kwargs.get('title', ''))),
        'title': kwargs.get('title', ''),
        'price': price_str,
        'price_numeric': kwargs.get('price_numeric', parse_price(price_str)),
        'description': kwargs.get('description', ''),
        'image_url': kwargs.get('image_url', ''),
        'listing_url': kwargs.get('listing_url', ''),
        'source': kwargs.get('source', ''),
        'source_type': kwargs.get('source_type', ''),
        'location': loc,
        'country': 'USA' if usa_flag else kwargs.get('country', 'International'),
        'is_usa': usa_flag,
        'condition': kwargs.get('condition', 'See listing'),
        'date_found': datetime.now().strftime('%Y-%m-%d'),
    }


def _html_scrape(url: str, source: str, source_type: str,
                 location: str = 'See listing', is_usa_flag: bool = False,
                 condition: str = 'See listing', max_items: int = 20) -> list[dict]:
    """Generic HTML card scraper used by many single-page sources."""
    listings = []
    r = _get(url)
    if not r:
        return listings
    soup = BeautifulSoup(r.text, 'html.parser')

    # Try __NEXT_DATA__ JSON first
    nd = soup.find('script', id='__NEXT_DATA__')
    if nd:
        try:
            data = json.loads(nd.string)
            pp = data.get('props', {}).get('pageProps', {})
            items = (
                pp.get('products', []) or pp.get('results', []) or
                pp.get('items', []) or
                pp.get('data', {}).get('listings', {}).get('items', [])
            )
            for p in items[:max_items]:
                title = p.get('title') or p.get('name', '')
                if not title:
                    continue
                price_raw = p.get('price') or p.get('listPrice', 0)
                if isinstance(price_raw, dict):
                    price_str = price_raw.get('displayAmount') or str(price_raw.get('amount', 'See listing'))
                elif isinstance(price_raw, (int, float)):
                    price_str = f'${price_raw:,.0f}'
                else:
                    price_str = str(price_raw) if price_raw else 'See listing'
                img = ''
                pi = p.get('primaryImage') or p.get('image') or {}
                if isinstance(pi, dict):
                    img = pi.get('url', pi.get('src', ''))
                elif isinstance(p.get('images'), list) and p['images']:
                    img = p['images'][0].get('src', '') if isinstance(p['images'][0], dict) else ''
                else:
                    img = p.get('imageUrl', p.get('thumbnail', ''))
                path = p.get('canonicalPath') or p.get('path') or p.get('pdpPath') or p.get('url', '')
                base = url.split('/')[0] + '//' + url.split('/')[2] if '//' in url else ''
                link = (base + path) if path and not path.startswith('http') else path
                listings.append(_make_listing(
                    id=_id(link or title), title=title, price=price_str,
                    description=p.get('description', '')[:300],
                    image_url=img, listing_url=link,
                    source=source, source_type=source_type,
                    location=location, condition=condition, is_usa=is_usa_flag,
                ))
            if listings:
                return listings
        except Exception as e:
            logger.debug(f'{source} JSON parse: {e}')

    # HTML card fallback
    selectors = [
        '[data-product-id]', '[data-listing-id]', '[data-lot-id]',
        '[class*="ProductCard"]', '[class*="product-card"]',
        '[class*="ItemCard"]', '[class*="lot-card"]',
        '[class*="card"]', 'article',
    ]
    candidates = []
    for sel in selectors:
        candidates = soup.select(sel)[:max_items]
        if candidates:
            break

    for item in candidates:
        title_el = item.select_one('h2, h3, h4, [class*="title"], [class*="name"]')
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if len(title) < 5:
            continue
        price_el = item.select_one('[class*="price"], [class*="Price"], [class*="estimate"]')
        img_el = item.select_one('img')
        link_el = item.select_one('a[href]')
        price_str = price_el.get_text(strip=True) if price_el else 'See listing'
        img = (img_el.get('src') or img_el.get('data-src', '')) if img_el else ''
        href = link_el['href'] if link_el else ''
        base = url.split('/')[0] + '//' + url.split('/')[2] if '//' in url else ''
        if href and not href.startswith('http'):
            href = base + href
        listings.append(_make_listing(
            id=_id(href or title), title=title, price=price_str,
            image_url=img, listing_url=href,
            source=source, source_type=source_type,
            location=location, condition=condition, is_usa=is_usa_flag,
        ))
    return listings


# ---------------------------------------------------------------------------
# SerpAPI - Google Shopping  (primary, reliable)
# ---------------------------------------------------------------------------


def scrape_serp_google_shopping(query: str = 'set of 12 dining chairs') -> list[dict]:
    if not SERP_API_KEY:
        logger.info('  SerpAPI Google Shopping: skipped (no API key)')
        return []

    listings = []
    searches = [query, f'{query} used vintage']
    for q in searches:
        params = {
            'engine': 'google_shopping',
            'q': q,
            'api_key': SERP_API_KEY,
            'num': 40,
            'gl': 'us',
            'hl': 'en',
        }
        r = _get('https://serpapi.com/search', params=params)
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for item in data.get('shopping_results', []):
            title = item.get('title', '')
            if not title:
                continue
            price_str = item.get('price', 'See listing')
            price_num = item.get('extracted_price') or parse_price(price_str)
            link = item.get('link', '')
            img = item.get('thumbnail', '')
            source_name = item.get('source', 'Google Shopping')
            listings.append(_make_listing(
                id=_id(link or title),
                title=title,
                price=price_str,
                price_numeric=price_num,
                image_url=img,
                listing_url=link,
                source=source_name,
                source_type='google shopping',
                location='USA',
                is_usa=True,
            ))
        time.sleep(1)

    logger.info(f'  SerpAPI Google Shopping: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# SerpAPI - eBay search  (primary, reliable)
# ---------------------------------------------------------------------------


def scrape_serp_ebay(query: str = 'set of 12 dining chairs') -> list[dict]:
    if not SERP_API_KEY:
        logger.info('  SerpAPI eBay: skipped (no API key)')
        return []

    listings = []
    for domain, country, is_us in [
        ('ebay.com', 'USA', True),
        ('ebay.co.uk', 'UK', False),
        ('ebay.ca', 'Canada', False),
    ]:
        params = {
            'engine': 'ebay',
            'ebay_domain': domain,
            '_nkw': query,
            'api_key': SERP_API_KEY,
            'LH_ItemCondition': '0',
        }
        r = _get('https://serpapi.com/search', params=params)
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for item in data.get('organic_results', []):
            title = item.get('title', '')
            if not title:
                continue
            price_info = item.get('price', {})
            if isinstance(price_info, dict):
                price_str = price_info.get('raw', 'See listing')
                price_num = price_info.get('extracted') or parse_price(price_str)
            else:
                price_str = str(price_info) if price_info else 'See listing'
                price_num = parse_price(price_str)
            link = item.get('link', '')
            img = item.get('thumbnail', '')
            condition = item.get('condition', 'See listing')
            location = item.get('location', country)
            listings.append(_make_listing(
                id=_id(link or title),
                title=title,
                price=price_str,
                price_numeric=price_num,
                image_url=img,
                listing_url=link,
                source=f'eBay ({domain})',
                source_type='auction/marketplace',
                location=location,
                country=country,
                is_usa=is_us,
                condition=condition,
            ))
        time.sleep(1)

    logger.info(f'  SerpAPI eBay: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# eBay Finding API  (primary, reliable)
# ---------------------------------------------------------------------------


def scrape_ebay_api(query: str = 'set of 12 dining chairs') -> list[dict]:
    if not EBAY_APP_ID:
        logger.info('  eBay Finding API: skipped (no App ID)')
        return []

    listings = []
    url = 'https://svcs.ebay.com/services/search/FindingService/v1'
    params = {
        'OPERATION-NAME': 'findItemsByKeywords',
        'SERVICE-VERSION': '1.0.0',
        'SECURITY-APPNAME': EBAY_APP_ID,
        'RESPONSE-DATA-FORMAT': 'JSON',
        'keywords': query,
        'paginationInput.entriesPerPage': '50',
        'sortOrder': 'BestMatch',
    }
    r = _get(url, params=params)
    if not r:
        logger.info('  eBay Finding API: 0 listings (request failed)')
        return []

    try:
        data = r.json()
        response = data.get('findItemsByKeywordsResponse', [{}])[0]
        items = response.get('searchResult', [{}])[0].get('item', [])
    except Exception as e:
        logger.warning(f'  eBay Finding API parse error: {e}')
        return []

    for item in items:
        try:
            title = item.get('title', [''])[0]
            link = item.get('viewItemURL', [''])[0]
            img = item.get('galleryURL', [''])[0]
            location = item.get('location', ['USA'])[0]
            condition = (
                item.get('condition', [{}])[0]
                    .get('conditionDisplayName', ['See listing'])[0]
                if item.get('condition') else 'See listing'
            )
            price_raw = (
                item.get('sellingStatus', [{}])[0]
                    .get('currentPrice', [{}])[0]
                    .get('__value__', '')
            )
            price_num = float(price_raw) if price_raw else None
            price_str = f'${price_num:,.2f}' if price_num else 'See listing'
            listings.append(_make_listing(
                id=_id(link or title),
                title=title,
                price=price_str,
                price_numeric=price_num,
                image_url=img,
                listing_url=link,
                source='eBay',
                source_type='auction/marketplace',
                location=location,
                condition=condition,
            ))
        except Exception:
            continue

    logger.info(f'  eBay Finding API: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# Craigslist (RSS)
# ---------------------------------------------------------------------------


def scrape_craigslist() -> list[dict]:
    listings = []
    query = quote_plus('12 dining chairs')
    for city_code, city_name in CRAIGSLIST_CITIES:
        rss_url = f'https://{city_code}.craigslist.org/search/fua?query={query}&format=rss'
        try:
            r = _get(rss_url)
            if not r:
                time.sleep(0.5)
                continue
            ns = {'rss': 'http://purl.org/rss/1.0/'}
            root = ET.fromstring(r.content)
            items = root.findall('.//item') or root.findall('.//rss:item', ns)
            for entry in items[:4]:
                def _t(tag):
                    el = entry.find(tag) or entry.find(f'rss:{tag}', ns)
                    return (el.text or '').strip() if el is not None else ''
                title = _t('title')
                link = _t('link')
                summary = _t('description')
                if not title or not link:
                    continue
                price_m = re.search(r'\$[\d,]+', title + ' ' + summary)
                price_str = price_m.group(0) if price_m else 'See listing'
                img = ''
                if '<img' in summary:
                    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
                    if m:
                        img = m.group(1)
                desc = BeautifulSoup(summary, 'html.parser').get_text()[:300] if summary else title
                listings.append(_make_listing(
                    id=_id(link), title=title, price=price_str,
                    description=desc, image_url=img, listing_url=link,
                    source='Craigslist', source_type='secondary market',
                    location=city_name, condition='Used', is_usa=True,
                ))
        except Exception as e:
            logger.debug(f'Craigslist {city_code} failed: {e}')
        time.sleep(0.5)
    logger.info(f'  Craigslist: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# Chairish
# ---------------------------------------------------------------------------


def scrape_chairish() -> list[dict]:
    listings = []
    for url in [
        'https://www.chairish.com/keyword/set-of-12-dining-chairs',
        'https://www.chairish.com/keyword/twelve-dining-chairs',
    ]:
        r = _get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        nd = soup.find('script', id='__NEXT_DATA__')
        if nd:
            try:
                data = json.loads(nd.string)
                items = (
                    data.get('props', {}).get('pageProps', {}).get('products', []) or
                    data.get('props', {}).get('pageProps', {}).get('results', [])
                )
                for p in items[:20]:
                    title = p.get('title') or p.get('name', '')
                    if not title:
                        continue
                    price_raw = p.get('price') or p.get('listPrice', 0)
                    price_str = f'${price_raw:,.0f}' if isinstance(price_raw, (int, float)) else str(price_raw)
                    img = p.get('primaryImage', {}).get('url', '') if isinstance(p.get('primaryImage'), dict) else p.get('imageUrl', '')
                    path = p.get('canonicalPath') or p.get('path', '')
                    link = f'https://www.chairish.com{path}' if path else ''
                    listings.append(_make_listing(
                        id=_id(link or title), title=title, price=price_str,
                        image_url=img, listing_url=link,
                        source='Chairish', source_type='design resale',
                        location='USA', condition='Pre-owned', is_usa=True,
                    ))
            except Exception as e:
                logger.debug(f'Chairish JSON parse: {e}')
        time.sleep(2)
    logger.info(f'  Chairish: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# 1stDibs
# ---------------------------------------------------------------------------


def scrape_1stdibs() -> list[dict]:
    listings = []
    for url in [
        'https://www.1stdibs.com/furniture/seating/dining-room-chairs/?q=set+of+12',
        'https://www.1stdibs.com/furniture/seating/dining-chairs-sets/',
    ]:
        r = _get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        nd = soup.find('script', id='__NEXT_DATA__')
        if nd:
            try:
                data = json.loads(nd.string)
                pp = data.get('props', {}).get('pageProps', {})
                items = (
                    pp.get('listings', []) or pp.get('results', []) or
                    pp.get('data', {}).get('listings', {}).get('items', [])
                )
                for p in items[:20]:
                    title = p.get('title') or p.get('name', '')
                    if not title:
                        continue
                    price_info = p.get('price', {})
                    price_str = (
                        price_info.get('displayAmount')
                        if isinstance(price_info, dict)
                        else str(price_info)
                    ) or 'See listing'
                    images = p.get('images', []) or []
                    img = images[0].get('src', '') if images and isinstance(images[0], dict) else ''
                    path = p.get('path') or p.get('pdpPath', '')
                    link = f'https://www.1stdibs.com{path}' if path else ''
                    listings.append(_make_listing(
                        id=_id(link or title), title=title, price=price_str,
                        image_url=img, listing_url=link,
                        source='1stDibs', source_type='luxury/design',
                        location='USA', condition='Vintage/Pre-owned',
                    ))
            except Exception as e:
                logger.debug(f'1stDibs JSON parse: {e}')
        time.sleep(2)
    logger.info(f'  1stDibs: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# Auction Houses
# ---------------------------------------------------------------------------


def scrape_sothebys() -> list[dict]:
    listings = _html_scrape(
        'https://www.sothebys.com/en/buy/furniture/chairs',
        source="Sotheby's", source_type='auction house',
        location='See auction',
    )
    # Also try search results page
    if not listings:
        q = quote_plus('set of 12 dining chairs')
        listings = _html_scrape(
            f'https://www.sothebys.com/en/search-results?q={q}&f2=00000166-9abc-d542-a1e6-ffbf3ed60000',
            source="Sotheby's", source_type='auction house',
            location='See auction',
        )
    logger.info(f"  Sotheby's: {len(listings)} listings")
    return listings


def scrape_christies() -> list[dict]:
    q = quote_plus('12 dining chairs')
    listings = _html_scrape(
        f'https://www.christies.com/en/results?categories=FURNITURE&keyword={q}',
        source="Christie's", source_type='auction house',
        location='See auction',
    )
    logger.info(f"  Christie's: {len(listings)} listings")
    return listings


def scrape_phillips() -> list[dict]:
    q = quote_plus('dining chairs')
    listings = _html_scrape(
        f'https://www.phillips.com/search?query={q}&department=Design',
        source='Phillips', source_type='auction house',
        location='See auction',
    )
    logger.info(f'  Phillips: {len(listings)} listings')
    return listings


def scrape_doyle() -> list[dict]:
    q = quote_plus('12 dining chairs set')
    listings = _html_scrape(
        f'https://www.doyle.com/search#query={q}',
        source='Doyle Auctions', source_type='auction house',
        location='See auction',
    )
    logger.info(f'  Doyle: {len(listings)} listings')
    return listings


def scrape_heritage() -> list[dict]:
    q = quote_plus('set 12 dining chairs')
    listings = _html_scrape(
        f'https://www.ha.com/c/search-results.zx?N=790+231+4294967271&Ntt={q}',
        source='Heritage Auctions', source_type='auction house',
        location='See auction', is_usa_flag=True,
    )
    logger.info(f'  Heritage Auctions: {len(listings)} listings')
    return listings


def scrape_wright20() -> list[dict]:
    listings = _html_scrape(
        'https://www.wright20.com/auctions/upcoming',
        source='Wright20', source_type='auction house',
        location='Chicago, IL', is_usa_flag=True,
    )
    if not listings:
        listings = _html_scrape(
            'https://www.wright20.com',
            source='Wright20', source_type='auction house',
            location='Chicago, IL', is_usa_flag=True,
        )
    logger.info(f'  Wright20: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# High-end / Design Retail
# ---------------------------------------------------------------------------


def scrape_rove_concepts() -> list[dict]:
    listings = _html_scrape(
        'https://www.roveconcepts.com/collections/dining-chairs',
        source='Rove Concepts', source_type='design retail',
        location='USA', is_usa_flag=True, condition='New',
    )
    logger.info(f'  Rove Concepts: {len(listings)} listings')
    return listings


def scrape_perigold() -> list[dict]:
    q = quote_plus('set of 12 dining chairs')
    listings = _html_scrape(
        f'https://www.perigold.com/furniture/dining-chairs/?search-button=&langId=-1&keyword={q}',
        source='Perigold', source_type='luxury retail',
        location='USA', is_usa_flag=True, condition='New',
    )
    logger.info(f'  Perigold: {len(listings)} listings')
    return listings


def scrape_triode_design() -> list[dict]:
    """Triode Design - French contemporary design furniture."""
    listings = _html_scrape(
        'https://www.triodedesign.com/fr/produits',
        source='Triode Design', source_type='luxury/design',
        location='France', is_usa_flag=False, condition='New',
    )
    logger.info(f'  Triode Design: {len(listings)} listings')
    return listings


def scrape_ormond_editions() -> list[dict]:
    """Ormond Editions - contemporary collectible design."""
    listings = _html_scrape(
        'https://ormond-editions.com/en/product-category/furniture/',
        source='Ormond Editions', source_type='luxury/design',
        location='International', is_usa_flag=False, condition='New',
    )
    logger.info(f'  Ormond Editions: {len(listings)} listings')
    return listings


def scrape_collection_particuliere() -> list[dict]:
    """Collection Particuliere - French high-end furniture."""
    listings = _html_scrape(
        'https://collection-particuliere.fr/categories/furniture/',
        source='Collection Particuliere', source_type='luxury/design',
        location='France', is_usa_flag=False, condition='New',
    )
    logger.info(f'  Collection Particuliere: {len(listings)} listings')
    return listings


def scrape_mary_ratcliffe() -> list[dict]:
    """Mary Ratcliffe Studio - bespoke contemporary furniture."""
    listings = _html_scrape(
        'https://www.maryratcliffe.studio/en-us/collections/benches',
        source='Mary Ratcliffe Studio', source_type='luxury/design',
        location='USA', is_usa_flag=True, condition='New',
    )
    logger.info(f'  Mary Ratcliffe Studio: {len(listings)} listings')
    return listings


def scrape_studio_twenty_seven() -> list[dict]:
    """Studio Twenty Seven - curated contemporary chairs."""
    listings = _html_scrape(
        'https://studiotwentyseven.com/furnitureset/chairs/',
        source='Studio Twenty Seven', source_type='luxury/design',
        location='USA', is_usa_flag=True, condition='New',
    )
    logger.info(f'  Studio Twenty Seven: {len(listings)} listings')
    return listings


def scrape_invisible_collection() -> list[dict]:
    """The Invisible Collection - curated luxury designer furniture."""
    listings = _html_scrape(
        'https://theinvisiblecollection.com/products-category/seating/',
        source='The Invisible Collection', source_type='luxury/design',
        location='International', is_usa_flag=False, condition='New',
    )
    logger.info(f'  The Invisible Collection: {len(listings)} listings')
    return listings


def scrape_miyazaki_chair() -> list[dict]:
    """Miyazaki Chair Factory - Japanese craft chairs."""
    listings = _html_scrape(
        'https://miyazakichair.com/collection/?tax_product_cat=chair&unfilter=1',
        source='Miyazaki Chair', source_type='luxury/design',
        location='Japan', is_usa_flag=False, condition='New',
    )
    logger.info(f'  Miyazaki Chair: {len(listings)} listings')
    return listings


# ---------------------------------------------------------------------------
# Deduplication & aggregation
# ---------------------------------------------------------------------------


def deduplicate(listings: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for l in listings:
        if l['id'] not in seen:
            seen.add(l['id'])
            result.append(l)
    return result


def _passes_filters(listing: dict) -> bool:
    """Return True if the listing should be included in results."""
    # Price filter: exclude if price is known but below $100
    pn = listing.get('price_numeric')
    if pn is not None and pn < 100:
        return False

    # Style keyword filter: exclude antique/period-style results
    text = f"{listing.get('title', '')} {listing.get('description', '')}"
    if EXCLUDED_STYLE_RE.search(text):
        return False

    # Domain filter: exclude mass-market retailers
    url_lower = listing.get('listing_url', '').lower()
    if any(d in url_lower for d in EXCLUDED_DOMAINS):
        return False

    return True


def run_all_scrapers() -> list[dict]:
    """Run all scrapers, apply filters, and return deduplicated sorted listings."""
    all_listings: list[dict] = []

    # API-based scrapers (most reliable - run first)
    api_scrapers = [
        ('SerpAPI Google Shopping', scrape_serp_google_shopping),
        ('SerpAPI eBay',            scrape_serp_ebay),
        ('eBay Finding API',        scrape_ebay_api),
    ]

    # Established resale / marketplace scrapers
    resale_scrapers = [
        ('Craigslist',      scrape_craigslist),
        ('Chairish',        scrape_chairish),
        ('1stDibs',         scrape_1stdibs),
    ]

    # Auction house scrapers
    auction_scrapers = [
        ("Sotheby's",          scrape_sothebys),
        ("Christie's",         scrape_christies),
        ('Phillips',           scrape_phillips),
        ('Doyle Auctions',     scrape_doyle),
        ('Heritage Auctions',  scrape_heritage),
        ('Wright20',           scrape_wright20),
    ]

    # High-end / design vendor scrapers
    design_scrapers = [
        ('Rove Concepts',           scrape_rove_concepts),
        ('Perigold',                scrape_perigold),
        ('Triode Design',           scrape_triode_design),
        ('Ormond Editions',         scrape_ormond_editions),
        ('Collection Particuliere', scrape_collection_particuliere),
        ('Mary Ratcliffe Studio',   scrape_mary_ratcliffe),
        ('Studio Twenty Seven',     scrape_studio_twenty_seven),
        ('The Invisible Collection',scrape_invisible_collection),
        ('Miyazaki Chair',          scrape_miyazaki_chair),
    ]

    for name, fn in api_scrapers + resale_scrapers + auction_scrapers + design_scrapers:
        logger.info(f'Scraping {name}...')
        try:
            results = fn()
            all_listings.extend(results)
        except Exception as e:
            logger.error(f'{name} scraper raised: {e}', exc_info=True)
        time.sleep(1)

    # Deduplicate
    all_listings = deduplicate(all_listings)

    # Apply filters: price, style keywords, excluded domains
    before = len(all_listings)
    all_listings = [l for l in all_listings if _passes_filters(l)]
    logger.info(f'Filtered out {before - len(all_listings)} listings (price/style/domain rules)')

    # Sort by price ascending (unknown price goes last)
    all_listings.sort(key=lambda x: x.get('price_numeric') or float('inf'))

    logger.info(f'Total unique listings after filtering: {len(all_listings)}')
    return all_listings


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    results = run_all_scrapers()
    print(json.dumps(results[:3], indent=2))
