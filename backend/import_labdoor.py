"""Import all currently-listed Labdoor products into the database.

Pipeline:
1. Fetch labdoor.com/rankings to discover all category slugs (~42).
2. For each category, fetch its rankings page to discover live product URLs.
   (We avoid the sitemap because ~50% of those URLs are stale 404s.)
3. For each product, scrape the static HTML for: name, brand, score (0-100),
   grade letter, image URL, category, certification flags, and the buy/affiliate URL.
4. Map Labdoor's category slug → our internal category. Skip non-supplement
   categories (energy drinks, milk chocolate, coca-cola, etc.).
5. Auto-create the Brand if we don't have it.
6. Upsert the Supplement (slug derived from Labdoor's review slug; numeric suffix
   added by unique_slug() in the rare case of a collision with another source).
7. Create or update the Labdoor Rating with the score, grade, certification verdict,
   buy URL, and a meaningful summary.
8. Download the product image from cdn.labdoor.io to backend/static/images/supplements/.

Run with: make import-labdoor [LIMIT=N]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Brand, Category, Source, Supplement, Rating
from app.utils import unique_slug as _unique_slug
from app.services.labdoor_scraper import (
    LabdoorProduct,
    fetch_product,
    fetch_product_urls,
    map_category,
)
from app.services.data_fetcher import download_image, generate_svg_fallback

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def slugify(text: str, max_len: int = 240) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "unknown"


def get_or_create_brand(name: str) -> Brand:
    slug = slugify(name)
    brand = Brand.query.filter_by(slug=slug).first()
    if brand:
        return brand
    brand = Brand(name=name, slug=slug, country="USA")
    db.session.add(brand)
    db.session.flush()
    return brand


def import_product(prod: LabdoorProduct, source: Source, stats: dict) -> None:
    cat_slug = map_category(prod.category_slug)
    if not cat_slug:
        logger.info(f"  [skip non-supp] {prod.slug:<55}  cat={prod.category_slug!r}")
        stats["skipped_non_supplement"] += 1
        return

    if not prod.brand:
        logger.info(f"  [skip no-brand] {prod.slug}")
        stats["skipped_no_brand"] += 1
        return

    if not prod.score and not prod.is_upcoming and not prod.is_certified:
        # If no score AND no certification AND not upcoming → page might be malformed
        logger.info(f"  [skip empty]    {prod.slug}")
        stats["skipped_empty"] += 1
        return

    category = Category.query.filter_by(slug=cat_slug).first()
    if not category:
        logger.warning(f"  [error] category {cat_slug!r} not in DB → skipping")
        stats["error"] += 1
        return

    brand = get_or_create_brand(prod.brand)

    # Compose supplement name. The product_name is what's after the brand in OG title.
    pname = prod.product_name or prod.title or prod.slug
    full_name = pname if prod.brand.lower() in pname.lower() else f"{prod.brand} {pname}"
    if len(full_name) > 180:
        full_name = full_name[:180].rsplit(" ", 1)[0] + "…"

    desired_slug = slugify(prod.slug)

    # Description
    desc_parts = [f"{prod.brand} {pname}".strip()]
    if prod.category_name:
        desc_parts.append(f"Category: {prod.category_name}.")
    if prod.score is not None:
        desc_parts.append(f"Labdoor quality score: {prod.score}/100 (Grade {prod.grade}).")
    description = " ".join(desc_parts)

    supp = Supplement.query.filter_by(slug=desired_slug).first()
    is_new = supp is None
    if is_new:
        # If the bare slug is taken by an unrelated supplement, fall back to a
        # numeric suffix — duplicates are then handled by merge_duplicates.py.
        final_slug = _unique_slug(Supplement, desired_slug)
        supp = Supplement(
            slug=final_slug,
            name=full_name,
            brand=brand,
            category=category,
            description=description,
            is_published=True,
        )
        db.session.add(supp)
    else:
        supp.name = full_name
        supp.brand = brand
        supp.category = category
        supp.description = description
    db.session.flush()

    # Image
    if prod.image_url and not supp.image_path:
        result = download_image(prod.image_url, supp.slug, source_label="labdoor")
        if result:
            supp.image_path, supp.image_source = result
        else:
            supp.image_path = generate_svg_fallback(
                slug=supp.slug, brand=prod.brand, name=pname,
                category_icon=category.icon or "vitamin",
            )
            supp.image_source = "generated"
    elif not supp.image_path:
        supp.image_path = generate_svg_fallback(
            slug=supp.slug, brand=prod.brand, name=pname,
            category_icon=category.icon or "vitamin",
        )
        supp.image_source = "generated"

    # Rating
    if prod.is_upcoming:
        verdict = "Upcoming"
    elif prod.is_expired:
        verdict = "Expired"
    elif prod.is_certified:
        verdict = "Certified"
    elif prod.score is not None and prod.score >= 60:
        verdict = "Pass"
    elif prod.score is not None:
        verdict = "Fail"
    else:
        verdict = None

    summary_bits = []
    if prod.score is not None:
        summary_bits.append(f"Quality score: {prod.score}/100 (Grade {prod.grade}).")
    if prod.is_certified:
        summary_bits.append("Labdoor Certified.")
    if prod.is_expired:
        summary_bits.append("Test report expired.")
    if prod.is_upcoming:
        summary_bits.append("Upcoming review.")
    summary_text = " ".join(summary_bits) or "Labdoor review."

    rating = Rating.query.filter_by(supplement_id=supp.id, source_id=source.id).first()
    rating_data = {
        "score": prod.score,
        "max_score": 100.0,
        "verdict": verdict,
        "summary": summary_text,
        "report_url": prod.url,
        # Per Labdoor's policy, all live products have an Amazon affiliate redirect.
        # Skip buy URLs for expired/upcoming products since the product is not currently sold.
        "buy_url": prod.buy_url if (prod.is_certified or (prod.score and prod.score >= 60)) else None,
    }

    if rating:
        for k, v in rating_data.items():
            setattr(rating, k, v)
    else:
        db.session.add(Rating(supplement=supp, source=source, **rating_data))

    if is_new:
        stats["new"] += 1
    else:
        stats["updated"] += 1
    cert_flag = "C" if prod.is_certified else ("E" if prod.is_expired else ("U" if prod.is_upcoming else "-"))
    logger.info(
        f"  ✓ {('NEW' if is_new else 'UPD')} {supp.slug[:50]:<50} {prod.brand[:18]:<18} "
        f"{(str(prod.score) if prod.score else '-'):<5} grade={prod.grade or '-'} "
        f"flag={cert_flag} buy={'Y' if rating_data['buy_url'] else '-'}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only import the first N (testing).")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        source = Source.query.filter_by(slug="labdoor").first()
        if not source:
            logger.error("Labdoor source not in DB. Run `make seed` first.")
            sys.exit(1)

        logger.info("Discovering live product URLs from Labdoor rankings pages...")
        urls = fetch_product_urls()
        logger.info(f"\nDiscovered {len(urls)} live product URLs across all rankings.\n")

        if args.limit:
            urls = urls[:args.limit]
            logger.info(f"Limiting to first {len(urls)} for this run.\n")

        stats = {"new": 0, "updated": 0, "skipped_non_supplement": 0,
                 "skipped_no_brand": 0, "skipped_empty": 0, "error": 0, "fetch_fail": 0}

        for i, url in enumerate(urls, 1):
            slug = url.rstrip("/").split("/")[-1]
            logger.info(f"[{i}/{len(urls)}] {slug}")
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
