"""Refresh Amazon affiliate buy_urls on Unbox Health ratings.

The original importer (`import_unboxhealth.py`) only stored buy_url for products
graded A or B — that gate makes sense for the public site (don't steer users to
a poor product) but it leaves the image-validation tool without a verified
Amazon URL for ~30% of the catalog.

This script re-scrapes the unboxhealth.in product page (already known via
Rating.report_url) and writes the affiliate URL to Rating.buy_url unconditionally,
so the validation tool can show a Verified-by-Unbox-Health candidate for every
product that has one available.

Run with:
    python refresh_unbox_buy_urls.py            # only products missing buy_url
    python refresh_unbox_buy_urls.py --all      # re-fetch every product
    python refresh_unbox_buy_urls.py --limit 5  # smoke test
"""
from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Rating, Source
from app.services.unbox_scraper import fetch_product

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="Re-fetch every unbox-health product (default: only those missing buy_url).")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N products.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        source = Source.query.filter_by(slug="unbox-health").first()
        if not source:
            logger.error("Unbox Health source not in DB.")
            sys.exit(1)

        q = Rating.query.filter(Rating.source_id == source.id, Rating.report_url.isnot(None))
        if not args.all:
            q = q.filter(Rating.buy_url.is_(None))
        ratings = q.order_by(Rating.id).all()
        if args.limit:
            ratings = ratings[: args.limit]

        logger.info(f"Refreshing buy_url on {len(ratings)} unbox-health rating(s).")
        stats = {"set": 0, "unchanged": 0, "no_buy_url": 0, "fetch_fail": 0}

        for i, r in enumerate(ratings, 1):
            url = r.report_url
            logger.info(f"[{i}/{len(ratings)}] {url}")
            try:
                prod = fetch_product(url)
            except Exception as e:
                logger.warning(f"  fetch error: {e}")
                stats["fetch_fail"] += 1
                continue
            if not prod:
                stats["fetch_fail"] += 1
                continue
            if not prod.buy_url:
                logger.info("  no buy_url on page")
                stats["no_buy_url"] += 1
                continue
            if r.buy_url == prod.buy_url:
                stats["unchanged"] += 1
                continue
            r.buy_url = prod.buy_url
            stats["set"] += 1
            logger.info(f"  ✓ set {prod.buy_url[:90]}")
            if i % 20 == 0:
                db.session.commit()

        db.session.commit()
        logger.info("\nDone.")
        for k, v in stats.items():
            logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    main()
