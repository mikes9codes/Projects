#!/usr/bin/env python3
"""Dining Room Chair Search 2026 - Flask Web Application"""

import json
import os
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
from scraper import run_all_scrapers, _is_excluded

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'results.json')


def load_results():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load results: {e}")
    return {"listings": [], "last_updated": None, "search_stats": {}}


def save_results(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def run_scheduled_search():
    logger.info("Running scheduled dining chair search...")
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
        save_results(data)
        logger.info(f"Search complete: {len(listings)} listings ({len(usa)} USA, {len(intl)} international)")
    except Exception as e:
        logger.error(f"Scheduled search failed: {e}", exc_info=True)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/listings')
def api_listings():
    data = load_results()
    listings = [l for l in data.get('listings', []) if not _is_excluded(l)]

    country = request.args.get('country', '')
    source = request.args.get('source', '')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    sort = request.args.get('sort', 'price_asc')

    if country == 'usa':
        listings = [l for l in listings if l.get('is_usa')]
    elif country == 'international':
        listings = [l for l in listings if not l.get('is_usa')]

    if source:
        listings = [l for l in listings if l.get('source', '') == source]

    if min_price is not None:
        listings = [l for l in listings if (l.get('price_numeric') or 0) >= min_price]
    if max_price is not None:
        listings = [l for l in listings if l.get('price_numeric') is None or l.get('price_numeric') <= max_price]

    if sort == 'price_asc':
        listings.sort(key=lambda x: x.get('price_numeric') or float('inf'))
    elif sort == 'price_desc':
        listings.sort(key=lambda x: -(x.get('price_numeric') or 0))
    elif sort == 'date':
        listings.sort(key=lambda x: x.get('date_found', ''), reverse=True)

    return jsonify({
        "listings": listings,
        "total": len(listings),
        "last_updated": data.get('last_updated'),
        "search_stats": data.get('search_stats', {}),
    })


@app.route('/api/refresh', methods=['POST'])
def refresh():
    run_scheduled_search()
    data = load_results()
    return jsonify({
        "status": "success",
        "total": len(data.get('listings', [])),
        "last_updated": data.get('last_updated'),
    })


@app.route('/api/stats')
def stats():
    data = load_results()
    return jsonify(data.get('search_stats', {}))


if __name__ == '__main__':
    if not os.path.exists(DATA_FILE):
        logger.info("No existing data - running initial search...")
        run_scheduled_search()

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scheduled_search, 'cron', hour=8, minute=0, id='daily_search')
    scheduler.start()
    logger.info("Daily search scheduled at 08:00 UTC")

    app.run(debug=False, host='0.0.0.0', port=5000)
