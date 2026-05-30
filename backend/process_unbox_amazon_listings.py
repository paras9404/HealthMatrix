"""Batch-apply the image-validation import flow to every Unbox-Health-verified product.

For each supplement that has an unbox-health Rating with a buy_url (the Amazon
affiliate URL curated on unboxhealth.in) and isn't already linked to an Amazon
listing, we:

  1. Scrape the Amazon page for title, ASIN, gallery images, specs, "About"
     bullets, brand, price.
  2. Patch the supplement: amazon_url / amazon_asin / amazon_data, rename to
     the Amazon title, clear the legacy single-image fields.
  3. Replace the gallery: create new SupplementImage rows for every Amazon
     image, then delete any pre-existing rows.

This mirrors the per-product flow that runs when an admin clicks "Use this
listing" → "Replace gallery with N images + save Amazon info" in the Image
Validation page. It's safe to run repeatedly — products that already have
amazon_url set are skipped by default.

Run with:
    python process_unbox_amazon_listings.py             # process unprocessed only
    python process_unbox_amazon_listings.py --redo      # re-process even those with amazon_url already
    python process_unbox_amazon_listings.py --limit 5   # smoke test
    python process_unbox_amazon_listings.py --dry-run   # preview what would change
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Rating, Source, Supplement, SupplementImage
from app.routes.admin.image_validation import scrape_amazon

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _build_amazon_data(scraped: dict) -> dict:
    return {
        "title": scraped.get("title"),
        "brand": scraped.get("brand"),
        "price": scraped.get("price"),
        "specs": scraped.get("specs") or {},
        "about": scraped.get("about") or [],
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


def process_one(supp: Supplement, buy_url: str, *, dry_run: bool = False) -> str:
    """Apply the import flow to one supplement. Returns a short status string."""
    try:
        scraped = scrape_amazon(buy_url)
    except Exception as e:
        return f"scrape_failed: {str(e)[:120]}"

    images = scraped.get("images") or []
    if not images:
        return "no_images"

    if dry_run:
        return f"would_import: {len(images)} images, title='{(scraped.get('title') or '')[:60]}'"

    # 1) Patch supplement metadata.
    supp.amazon_url = scraped.get("url") or buy_url
    supp.amazon_asin = scraped.get("asin")
    supp.amazon_data = _build_amazon_data(scraped)
    if scraped.get("title"):
        supp.name = scraped["title"]
    supp.image_url = None
    supp.image_path = None

    # 2) Phase 1: create new gallery rows.
    new_rows = []
    for idx, img in enumerate(images):
        url = img.get("url")
        if not url:
            continue
        new_rows.append(SupplementImage(
            supplement_id=supp.id,
            image_url=url,
            image_type="main" if idx == 0 else "other",
            alt_text=(scraped.get("title") or supp.name)[:200],
            display_order=idx,
        ))
    if not new_rows:
        return "no_images"

    # Pre-collect existing image ids before adding new ones (so the deletion
    # phase doesn't accidentally pick up the rows we just created).
    existing_ids = [r.id for r in supp.images]

    db.session.add_all(new_rows)
    db.session.flush()

    # 3) Phase 2: delete pre-existing gallery rows.
    if existing_ids:
        SupplementImage.query.filter(SupplementImage.id.in_(existing_ids)).delete(
            synchronize_session=False
        )

    return f"imported: {len(new_rows)} images" + (
        f", renamed → '{scraped['title'][:50]}…'" if scraped.get("title") and scraped["title"] != supp.name else ""
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--redo", action="store_true",
                        help="Re-process products that already have amazon_url set.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N supplements.")
    parser.add_argument("--throttle", type=float, default=1.0,
                        help="Seconds to sleep between Amazon scrapes (default 1.0).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing to the DB.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        unbox = Source.query.filter_by(slug="unbox-health").first()
        if not unbox:
            logger.error("Unbox Health source not in DB.")
            sys.exit(1)

        # Pull every supplement that has an unbox-health rating with buy_url.
        rows = (db.session.query(Rating.supplement_id, Rating.buy_url)
                .filter(Rating.source_id == unbox.id, Rating.buy_url.isnot(None))
                .all())
        targets: list[tuple[int, str]] = list(rows)
        logger.info(f"Found {len(targets)} unbox-health products with verified Amazon URLs.")

        if not args.redo:
            already = {s.id for s in Supplement.query
                       .filter(Supplement.id.in_([t[0] for t in targets]),
                               Supplement.amazon_url.isnot(None)).all()}
            targets = [t for t in targets if t[0] not in already]
            logger.info(f"Skipping {len(already)} already-linked. {len(targets)} to process.")

        if args.limit:
            targets = targets[: args.limit]

        stats = {"imported": 0, "skipped_no_supp": 0, "scrape_failed": 0,
                 "no_images": 0, "errors": 0}

        for i, (supp_id, buy_url) in enumerate(targets, 1):
            supp = Supplement.query.get(supp_id)
            if not supp:
                stats["skipped_no_supp"] += 1
                continue
            logger.info(f"[{i}/{len(targets)}] {supp.slug[:50]:<50}")
            try:
                status = process_one(supp, buy_url, dry_run=args.dry_run)
                logger.info(f"  → {status}")
                if status.startswith("imported") or status.startswith("would_import"):
                    stats["imported"] += 1
                elif status.startswith("scrape_failed"):
                    stats["scrape_failed"] += 1
                elif status == "no_images":
                    stats["no_images"] += 1
                if not args.dry_run and i % 10 == 0:
                    db.session.commit()
                    logger.info(f"  (committed batch at {i})")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"  ! error: {e}")
                stats["errors"] += 1
            time.sleep(args.throttle)

        if not args.dry_run:
            db.session.commit()
        logger.info("\nDone.")
        for k, v in stats.items():
            logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    main()
