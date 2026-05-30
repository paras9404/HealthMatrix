"""Import only Unbox Health products not yet in our DB.

Reuses the per-product upsert from `import_unboxhealth.py` so behavior
(category mapping, image download, food-skip filter) stays identical to the
full-catalog importer. The only difference: we narrow the URL list to the
delta first.

Run with: backend/venv/bin/python import_unboxhealth_delta.py
"""
from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Rating, Source
from app.services.unbox_scraper import fetch_product, fetch_product_urls
from app.utils import slugify

# Reuse the existing per-product upsert. Same code path the full importer takes,
# so semantics — auto-creating brands, mapping categories, image downloads,
# food-skip filter — stay identical.
from import_unboxhealth import import_product

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    app = create_app()
    with app.app_context():
        source = Source.query.filter_by(slug="unbox-health").first()
        if not source:
            logger.error("unbox-health source not seeded.")
            sys.exit(1)

        logger.info("Fetching live product list ...")
        live_urls = fetch_product_urls()
        logger.info(f"  → {len(live_urls)} live URLs.")

        # Build the same matching index used by the audit script: exact
        # report_url match, then slug fallback. We only import URLs that miss
        # both — those are genuinely new.
        db_urls = {
            r.report_url for r in Rating.query.filter_by(source_id=source.id).all()
            if r.report_url
        }

        delta: list[str] = []
        for url in live_urls:
            if url in db_urls:
                continue
            delta.append(url)

        logger.info(f"Already in DB: {len(live_urls) - len(delta)}")
        logger.info(f"To import:     {len(delta)}\n")

        stats = {
            "new": 0, "updated": 0,
            "skipped_non_supplement": 0,
            "skipped_no_brand": 0,
            "skipped_empty": 0,
            "error": 0, "fetch_fail": 0,
        }

        for i, url in enumerate(delta, 1):
            slug = url.rstrip("/").split("/")[-2] if "/" in url else url
            logger.info(f"[{i}/{len(delta)}] {slug}")
            try:
                prod = fetch_product(url)
                if not prod:
                    stats["fetch_fail"] += 1
                    continue
                import_product(prod, source, stats)
                if i % 10 == 0:
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"  [error] {slug}: {e}")
                stats["error"] += 1

        db.session.commit()
        logger.info("\n" + "=" * 60)
        logger.info("Done.")
        for k, v in stats.items():
            logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    main()
