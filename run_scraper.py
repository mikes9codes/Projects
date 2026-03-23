#!/usr/bin/env python3
"""CLI script to run the chair search - used by GitHub Actions for daily updates."""

import json
import os
import sys
import logging
from datetime import datetime
from scraper import run_all_scrapers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'results.json')


def main():
    logger.info("=" * 60)
    logger.info("Dining Room Chair Search 2026 - Starting daily search")
    logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    try:
        listings = run_all_scrapers()

        usa = [l for l in listings if l.get('is_usa')]
        intl = [l for l in listings if not l.get('is_usa')]
        sources = sorted(set(l.get('source', '') for l in listings))
        priced = [l for l in listings if l.get('price_numeric')]
        avg_price = sum(l['price_numeric'] for l in priced) / len(priced) if priced else 0

        data = {
            "listings": listings,
            "last_updated": datetime.now().isoformat(),
            "search_stats": {
                "total": len(listings),
                "usa_count": len(usa),
                "intl_count": len(intl),
                "sources": sources,
                "avg_price": round(avg_price, 2),
                "date": datetime.now().strftime('%Y-%m-%d'),
            }
        }

        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info("Search complete!")
        logger.info(f"  Total listings  : {len(listings)}")
        logger.info(f"  USA listings    : {len(usa)}")
        logger.info(f"  International  : {len(intl)}")
        logger.info(f"  Sources        : {', '.join(sources)}")
        if avg_price:
            logger.info(f"  Avg price      : ${avg_price:,.0f}")
        logger.info(f"  Saved to       : {DATA_FILE}")
        return 0

    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
