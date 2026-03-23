#!/usr/bin/env python3
"""Multi-source scraper for sets of 12 dining chairs.

Sources:
  USA    - eBay, Craigslist (20 cities), Chairish, Etsy, LiveAuctioneers
  Intl   - eBay UK/CA/AU/DE/FR/IT, Pamono, Sellingantiques
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from urllib.parse import quote_plus, urljoin

import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
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
# Helpers
# ---------------------------------------------------------------------------


def _id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:14]


def parse_price(s: str) -> float | None:
    if not s:
        return None
    s = re.sub(r'[^\d.,]', '', s.replace(',', ''))
    parts = re.split(r'[^\d.]', s)
    for p in parts:
        try:
            v = float(p)
            if v > 0:
                return v
        except ValueError:
            continue
    return None


def is_usa(location: str) -> bool:
    if not location:
        return False
    loc = location.lower().strip()
    # Explicit USA / United States
    if any(x in loc for x in ('united states', 'usa', 'u.s.a')):
        return True
    # State abbreviations (e.g. ", NY" or "NY, US")
    for abbr in US_STATE_ABBRS:
        if re.search(r'\b' + abbr + r'\b', location):
            return True
    # Known city names
    for city in US_CITIES:
        if city in loc:
            return True
    # US ZIP code
    if re.search(r'\b\d{5}\b', location):
        return True
    return False


def _get(url: str, timeout: int = 15) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        logger.warning(f"GET {url} failed: {e}")
        return None


def _make_listing(**kwargs) -> dict:
    loc = kwargs.get('location', '')
    usa_flag = kwargs.get('is_usa', is_usa(loc))
    return {
        'id': kwargs.get('id', _id(kwargs.get('listing_url', '') or kwargs.get('title', ''))),
        'title': kwargs.get('title', ''),
        'price': kwargs.get('price', 'See listing'),
        'price_numeric': kwargs.get('price_numeric', parse_price(kwargs.get('price', ''))),
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


# ---------------------------------------------------------------------------
# eBay USA
# ---------------------------------------------------------------------------


def scrape_ebay_us(query: str = 'set of 12 dining chairs') -> list[dict]:
    listings = []
    encoded = quote_plus(query)
    # Buy It Now + best match
    for suffix in ['&LH_BIN=1', '&LH_Auction=1']:
        url = f'https://www.ebay.com/sch/i.html?_nkw={encoded}&_sop=10{suffix}&_ipg=48'
        r = _get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('.s-item'):
            try:
                title_el = item.select_one('.s-item__title')
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if 'Shop on eBay' in title:
                    continue

                link_el = item.select_one('a.s-item__link')
                url_listing = link_el['href'].split('?')[0] if link_el else ''

                price_el = item.select_one('.s-item__price')
                price_str = price_el.get_text(strip=True) if price_el else ''

                img_el = item.select_one('.s-item__image-wrapper img')
                img = ''
                if img_el:
                    img = img_el.get('src') or img_el.get('data-src', '')

                loc_el = item.select_one('.s-item__location')
                location = loc_el.get_text(strip=True).replace('Located in:', '').strip() if loc_el else 'USA'

                cond_el = item.select_one('.SECONDARY_INFO')
                condition = cond_el.get_text(strip=True) if cond_el else 'See listing'

                listings.append(_make_listing(
                    id=_id(url_listing or title),
                    title=title,
                    price=price_str,
                    image_url=img,
                    listing_url=url_listing,
                    source='eBay',
                    source_type='auction/marketplace',
                    location=location,
                    condition=condition,
                ))
            except Exception:
                continue
        time.sleep(1.5)
    logger.info(f"  eBay US: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# eBay International
# ---------------------------------------------------------------------------


def scrape_ebay_international(query: str = 'set of 12 dining chairs') -> list[dict]:
    listings = []
    encoded = quote_plus(query)
    for base_url, country_name in INTL_EBAY_SITES:
        url = f'{base_url}/sch/i.html?_nkw={encoded}&_sop=10&_ipg=24'
        r = _get(url)
        if not r:
            time.sleep(1)
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        count = 0
        for item in soup.select('.s-item'):
            if count >= 6:
                break
            try:
                title_el = item.select_one('.s-item__title')
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if 'Shop on eBay' in title:
                    continue

                link_el = item.select_one('a.s-item__link')
                url_listing = link_el['href'].split('?')[0] if link_el else ''

                price_el = item.select_one('.s-item__price')
                price_str = price_el.get_text(strip=True) if price_el else ''

                img_el = item.select_one('.s-item__image-wrapper img')
                img = img_el.get('src', '') if img_el else ''

                loc_el = item.select_one('.s-item__location')
                location = loc_el.get_text(strip=True).replace('Located in:', '').strip() if loc_el else country_name

                listings.append(_make_listing(
                    id=_id(url_listing or title + country_name),
                    title=title,
                    price=price_str,
                    image_url=img,
                    listing_url=url_listing,
                    source=f'eBay {country_name}',
                    source_type='auction/marketplace',
                    location=location or country_name,
                    country=country_name,
                    is_usa=False,
                ))
                count += 1
            except Exception:
                continue
        time.sleep(2)
    logger.info(f"  eBay International: {len(listings)} listings")
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
            # Parse RSS with built-in XML parser
            ns = {'rss': 'http://purl.org/rss/1.0/', 'dc': 'http://purl.org/dc/elements/1.1/'}
            root = ET.fromstring(r.content)
            # Support both RSS 2.0 (item) and RSS 1.0 (rss:item)
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

                # Extract first image from description HTML
                img = ''
                if '<img' in summary:
                    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
                    if m:
                        img = m.group(1)

                desc = BeautifulSoup(summary, 'html.parser').get_text()[:300] if summary else title

                listings.append(_make_listing(
                    id=_id(link),
                    title=title,
                    price=price_str,
                    description=desc,
                    image_url=img,
                    listing_url=link,
                    source='Craigslist',
                    source_type='secondary market',
                    location=city_name,
                    condition='Used',
                    is_usa=True,
                ))
        except Exception as e:
            logger.debug(f"Craigslist {city_code} failed: {e}")
        time.sleep(0.5)
    logger.info(f"  Craigslist: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Chairish
# ---------------------------------------------------------------------------


def scrape_chairish() -> list[dict]:
    listings = []
    urls = [
        'https://www.chairish.com/keyword/set-of-12-dining-chairs',
        'https://www.chairish.com/keyword/twelve-dining-chairs',
    ]
    for url in urls:
        r = _get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')

        # Try __NEXT_DATA__ JSON
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
                    price_str = f"${price_raw:,.0f}" if isinstance(price_raw, (int, float)) else str(price_raw)
                    img = p.get('primaryImage', {}).get('url', '') if isinstance(p.get('primaryImage'), dict) else p.get('imageUrl', '')
                    path = p.get('canonicalPath') or p.get('path', '')
                    link = f'https://www.chairish.com{path}' if path else ''
                    listings.append(_make_listing(
                        id=_id(link or title),
                        title=title,
                        price=price_str,
                        description=p.get('description', '')[:300],
                        image_url=img,
                        listing_url=link,
                        source='Chairish',
                        source_type='design resale',
                        location='USA',
                        condition='Pre-owned',
                        is_usa=True,
                    ))
            except Exception as e:
                logger.debug(f"Chairish JSON parse: {e}")

        # HTML fallback
        if not listings:
            for item in soup.select('[data-product-id], [data-testid*="product"], .product-card, [class*="ProductCard"]')[:20]:
                title_el = item.select_one('h2, h3, [class*="title"]')
                price_el = item.select_one('[class*="price"], [class*="Price"]')
                img_el = item.select_one('img')
                link_el = item.select_one('a[href]')
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                price_str = price_el.get_text(strip=True) if price_el else 'See listing'
                img = img_el.get('src', '') if img_el else ''
                href = link_el['href'] if link_el else ''
                if href and not href.startswith('http'):
                    href = 'https://www.chairish.com' + href
                listings.append(_make_listing(
                    id=_id(href or title),
                    title=title, price=price_str, image_url=img, listing_url=href,
                    source='Chairish', source_type='design resale',
                    location='USA', condition='Pre-owned', is_usa=True,
                ))
        time.sleep(2)
    logger.info(f"  Chairish: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# 1stDibs
# ---------------------------------------------------------------------------


def scrape_1stdibs() -> list[dict]:
    listings = []
    urls = [
        'https://www.1stdibs.com/furniture/seating/dining-room-chairs/?q=set+of+12',
        'https://www.1stdibs.com/furniture/seating/dining-chairs-sets/',
    ]
    for url in urls:
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
                    pp.get('listings', []) or
                    pp.get('results', []) or
                    pp.get('data', {}).get('listings', {}).get('items', [])
                )
                for p in items[:20]:
                    title = p.get('title') or p.get('name', '')
                    if not title:
                        continue
                    price_info = p.get('price', {})
                    if isinstance(price_info, dict):
                        price_str = price_info.get('displayAmount') or str(price_info.get('amount', 'See listing'))
                    else:
                        price_str = str(price_info) if price_info else 'See listing'
                    images = p.get('images', []) or p.get('media', [])
                    img = images[0].get('src', '') if images and isinstance(images[0], dict) else ''
                    path = p.get('path') or p.get('pdpPath', '')
                    link = f'https://www.1stdibs.com{path}' if path else ''
                    loc = p.get('seller', {}).get('address', {}).get('city', '') if isinstance(p.get('seller'), dict) else ''

                    listings.append(_make_listing(
                        id=_id(link or title),
                        title=title, price=price_str, image_url=img, listing_url=link,
                        source='1stDibs', source_type='luxury/design',
                        location=loc or 'USA', condition='Vintage/Pre-owned',
                    ))
            except Exception as e:
                logger.debug(f"1stDibs JSON parse: {e}")

        # HTML fallback
        if not listings:
            for item in soup.select('[data-tn="product-list-item"], [class*="ProductTile"], [class*="product-tile"]')[:20]:
                title_el = item.select_one('h2, h3, [class*="title"], [data-tn*="title"]')
                price_el = item.select_one('[class*="price"], [data-tn*="price"]')
                img_el = item.select_one('img')
                link_el = item.select_one('a[href]')
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                price_str = price_el.get_text(strip=True) if price_el else 'See listing'
                img = img_el.get('src', '') if img_el else ''
                href = link_el['href'] if link_el else ''
                if href and not href.startswith('http'):
                    href = 'https://www.1stdibs.com' + href
                listings.append(_make_listing(
                    id=_id(href or title), title=title, price=price_str,
                    image_url=img, listing_url=href,
                    source='1stDibs', source_type='luxury/design',
                    location='USA', condition='Vintage/Pre-owned',
                ))
        time.sleep(2)
    logger.info(f"  1stDibs: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Etsy
# ---------------------------------------------------------------------------


def scrape_etsy() -> list[dict]:
    listings = []
    query = quote_plus('set of 12 dining chairs')
    url = f'https://www.etsy.com/search?q={query}&explicit=1&ref=pagination'
    r = _get(url)
    if not r:
        logger.info('  Etsy: 0 listings (request failed)')
        return listings
    soup = BeautifulSoup(r.text, 'html.parser')

    for item in soup.select('[data-listing-id], .v2-listing-card, [class*="listing-card"]')[:20]:
        title_el = item.select_one('h3, h2, [class*="title"], [class*="name"]')
        price_el = item.select_one('[class*="price"] span, [class*="currency-value"]')
        img_el = item.select_one('img')
        link_el = item.select_one('a[href]')
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        price_str = price_el.get_text(strip=True) if price_el else 'See listing'
        img = img_el.get('src', '') if img_el else ''
        href = link_el['href'] if link_el else ''
        if href and not href.startswith('http'):
            href = 'https://www.etsy.com' + href
        listings.append(_make_listing(
            id=_id(href or title), title=title, price=price_str,
            image_url=img, listing_url=href,
            source='Etsy', source_type='marketplace/vintage',
            location='USA', condition='Pre-owned/Handmade', is_usa=True,
        ))
    logger.info(f"  Etsy: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# LiveAuctioneers
# ---------------------------------------------------------------------------


def scrape_liveauctioneers() -> list[dict]:
    listings = []
    query = quote_plus('set 12 dining chairs')
    url = f'https://www.liveauctioneers.com/search/?keyword={query}&status=all&sort=relevance'
    r = _get(url)
    if not r:
        logger.info('  LiveAuctioneers: 0 listings (request failed)')
        return listings
    soup = BeautifulSoup(r.text, 'html.parser')

    # Check for JSON data
    for script in soup.find_all('script', type='application/json'):
        try:
            data = json.loads(script.string or '')
            items = data.get('lots', data.get('results', data.get('items', [])))
            for p in items[:15]:
                title = p.get('title') or p.get('name', '')
                if not title:
                    continue
                price_est = p.get('estimate_low') or p.get('sold_price') or p.get('starting_bid', 0)
                price_str = f"Est. ${price_est:,}" if price_est else 'See auction'
                img = p.get('image_url') or p.get('thumbnail', '')
                lid = p.get('item_id') or p.get('id', '')
                link = f"https://www.liveauctioneers.com/item/{lid}/" if lid else ''
                loc = p.get('seller', {}).get('city', '') if isinstance(p.get('seller'), dict) else ''
                listings.append(_make_listing(
                    id=_id(link or title), title=title, price=price_str,
                    image_url=img, listing_url=link,
                    source='LiveAuctioneers', source_type='auction',
                    location=loc or 'USA', condition='See auction',
                ))
        except Exception:
            continue

    # HTML fallback
    if not listings:
        for item in soup.select('[class*="ItemCard"], [class*="lot-card"], [data-lot-id]')[:15]:
            title_el = item.select_one('h2, h3, [class*="title"]')
            price_el = item.select_one('[class*="price"], [class*="estimate"]')
            img_el = item.select_one('img')
            link_el = item.select_one('a[href]')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            price_str = price_el.get_text(strip=True) if price_el else 'See auction'
            img = img_el.get('src', '') if img_el else ''
            href = link_el['href'] if link_el else ''
            if href and not href.startswith('http'):
                href = 'https://www.liveauctioneers.com' + href
            listings.append(_make_listing(
                id=_id(href or title), title=title, price=price_str,
                image_url=img, listing_url=href,
                source='LiveAuctioneers', source_type='auction',
                location='USA', condition='See auction',
            ))
    logger.info(f"  LiveAuctioneers: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Pamono (International designer/vintage)
# ---------------------------------------------------------------------------


def scrape_pamono() -> list[dict]:
    listings = []
    query = quote_plus('set of 12 dining chairs')
    url = f'https://www.pamono.com/en/search?q={query}&category=chairs'
    r = _get(url)
    if not r:
        logger.info('  Pamono: 0 listings (request failed)')
        return listings
    soup = BeautifulSoup(r.text, 'html.parser')

    nd = soup.find('script', id='__NEXT_DATA__')
    if nd:
        try:
            data = json.loads(nd.string)
            items = (
                data.get('props', {}).get('pageProps', {}).get('products', []) or
                data.get('props', {}).get('pageProps', {}).get('items', [])
            )
            for p in items[:15]:
                title = p.get('name') or p.get('title', '')
                if not title:
                    continue
                price = p.get('price', {}).get('value') or p.get('price', 0)
                currency = p.get('price', {}).get('currency', 'EUR') if isinstance(p.get('price'), dict) else 'EUR'
                price_str = f"{currency} {price:,.0f}" if price else 'See listing'
                img = (p.get('images', [{}]) or [{}])[0].get('url', '') if isinstance((p.get('images', []) or [None])[0], dict) else ''
                path = p.get('url') or p.get('slug', '')
                link = f'https://www.pamono.com{path}' if path and not path.startswith('http') else path
                country = p.get('country') or p.get('location', {}).get('country', 'Europe')
                listings.append(_make_listing(
                    id=_id(link or title), title=title, price=price_str,
                    image_url=img, listing_url=link,
                    source='Pamono', source_type='luxury/design',
                    location=country, country=country, is_usa=False,
                ))
        except Exception as e:
            logger.debug(f"Pamono JSON parse: {e}")

    if not listings:
        for item in soup.select('[class*="ProductCard"], [class*="product-card"]')[:15]:
            title_el = item.select_one('h2, h3, [class*="title"]')
            price_el = item.select_one('[class*="price"]')
            img_el = item.select_one('img')
            link_el = item.select_one('a[href]')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            price_str = price_el.get_text(strip=True) if price_el else 'See listing'
            img = img_el.get('src', '') if img_el else ''
            href = link_el['href'] if link_el else ''
            if href and not href.startswith('http'):
                href = 'https://www.pamono.com' + href
            listings.append(_make_listing(
                id=_id(href or title), title=title, price=price_str,
                image_url=img, listing_url=href,
                source='Pamono', source_type='luxury/design',
                location='Europe', country='Europe', is_usa=False,
            ))
    logger.info(f"  Pamono: {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Deduplicate & aggregate
# ---------------------------------------------------------------------------


def deduplicate(listings: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for l in listings:
        if l['id'] not in seen:
            seen.add(l['id'])
            result.append(l)
    return result


def run_all_scrapers() -> list[dict]:
    """Run all scrapers and return deduplicated, sorted listings."""
    all_listings: list[dict] = []

    scrapers = [
        ('eBay USA', scrape_ebay_us),
        ('eBay International', scrape_ebay_international),
        ('Craigslist', scrape_craigslist),
        ('Chairish', scrape_chairish),
        ('1stDibs', scrape_1stdibs),
        ('Etsy', scrape_etsy),
        ('LiveAuctioneers', scrape_liveauctioneers),
        ('Pamono', scrape_pamono),
    ]

    for name, fn in scrapers:
        logger.info(f"Scraping {name}...")
        try:
            results = fn()
            all_listings.extend(results)
        except Exception as e:
            logger.error(f"{name} scraper raised: {e}", exc_info=True)
        time.sleep(1.5)

    all_listings = deduplicate(all_listings)
    all_listings.sort(key=lambda x: x.get('price_numeric') or float('inf'))

    logger.info(f"Total unique listings: {len(all_listings)}")
    return all_listings


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    results = run_all_scrapers()
    print(json.dumps(results[:3], indent=2))
