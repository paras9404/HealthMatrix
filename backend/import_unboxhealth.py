"""Import all UnboxHealth lab-tested supplement reviews into the database.

Pipeline:
1. Discover all product URLs from www.unboxhealth.in/explore/products-list (~321 products).
2. For each product page, parse the embedded JSON-LD for product + breadcrumb data.
3. Map UnboxHealth's category slug → our internal category. Skip non-supplements
   (chocolates, biscuits, ghee, ice cream, etc.).
4. Auto-create the Brand if we don't have it.
5. Upsert the Supplement (slug derived from UnboxHealth's product slug; numeric
   suffix added by unique_slug() in the rare case of a collision with another source).
6. Create or update the Unbox Health Rating with score (0-100 normalized from 0-10),
   verdict, sub-scores summary, the affiliate buy URL, and the report URL.
7. Download the product image from S3 to backend/static/images/supplements/.

Run with: make import-unboxhealth [LIMIT=N]
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
from app.services.unbox_scraper import (
    UnboxProduct,
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
    brand = Brand(name=name, slug=slug, country="India")
    db.session.add(brand)
    db.session.flush()
    return brand


def import_product(prod: UnboxProduct, source: Source, stats: dict) -> None:
    cat_slug = map_category(prod.category_slug)
    if not cat_slug:
        logger.info(f"  [skip non-supp] {prod.slug[:48]:<48}  cat={prod.category_slug!r}")
        stats["skipped_non_supplement"] += 1
        return

    if not prod.brand:
        logger.info(f"  [skip no-brand] {prod.slug}")
        stats["skipped_no_brand"] += 1
        return

    if prod.score is None:
        logger.info(f"  [skip no-score] {prod.slug}")
        stats["skipped_empty"] += 1
        return

    category = Category.query.filter_by(slug=cat_slug).first()
    if not category:
        logger.warning(f"  [error] category {cat_slug!r} not in DB → skipping")
        stats["error"] += 1
        return

    brand = get_or_create_brand(prod.brand)

    # Compose supplement name. Strip the brand prefix if present so cards display cleanly.
    pname = prod.name or prod.slug
    full_name = pname if prod.brand.lower() in pname.lower() else f"{prod.brand} {pname}"
    if len(full_name) > 180:
        full_name = full_name[:180].rsplit(" ", 1)[0] + "…"

    desired_slug = slugify(prod.slug)

    desc_parts = [pname]
    if prod.category_name:
        desc_parts.append(f"Category: {prod.category_name}.")
    if prod.score is not None and prod.grade:
        desc_parts.append(f"Unbox Health rated {prod.grade} ({prod.score}/10).")
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

    # Image — UnboxHealth hosts on S3, very reliable
    if prod.image_url and not supp.image_path:
        result = download_image(prod.image_url, supp.slug, source_label="unbox-health")
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

    # Build / update the Rating
    summary_bits = []
    if prod.grade:
        summary_bits.append(f"Grade {prod.grade}.")
    if prod.label_accuracy is not None:
        summary_bits.append(f"Label Accuracy: {prod.label_accuracy}/10.")
    if prod.non_toxicity is not None:
        summary_bits.append(f"Non-Toxicity: {prod.non_toxicity}/10.")
    if prod.is_previous:
        summary_bits.append("(Previously rated.)")
    summary_text = " ".join(summary_bits) or "Unbox Health lab-tested rating."

    # Verdict from grade
    if prod.grade in ("A+", "A"):
        verdict = "Excellent"
    elif prod.grade in ("B+", "B"):
        verdict = "Good"
    elif prod.grade == "C":
        verdict = "Average"
    elif prod.grade in ("D", "F"):
        verdict = "Poor"
    else:
        verdict = None

    rating = Rating.query.filter_by(supplement_id=supp.id, source_id=source.id).first()
    rating_data = {
        "score": round(prod.normalized_score, 2) if prod.normalized_score is not None else None,
        "max_score": 100.0,
        "verdict": verdict,
        "summary": summary_text,
        "report_url": prod.url,
        # Always store the Amazon affiliate URL when present — the image-validation
        # admin tool surfaces it as the verified candidate. The "don't steer users
        # to a poor product" guard belongs at the rendering layer, not storage.
        "buy_url": prod.buy_url,
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
    logger.info(
        f"  ✓ {('NEW' if is_new else 'UPD')} {supp.slug[:50]:<50} {prod.brand[:18]:<18} "
        f"{prod.grade or '-':<3} score={prod.score} buy={'Y' if rating_data['buy_url'] else '-'}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only import the first N (testing).")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        source = Source.query.filter_by(slug="unbox-health").first()
        if not source:
            logger.error("Unbox Health source not in DB. Run `make seed` first.")
            sys.exit(1)

        logger.info("Discovering live product URLs from unboxhealth.in/explore/products-list...")
        urls = fetch_product_urls()
        logger.info(f"\nDiscovered {len(urls)} live product URLs.\n")

        if args.limit:
            urls = urls[:args.limit]
            logger.info(f"Limiting to first {len(urls)} for this run.\n")

        stats = {"new": 0, "updated": 0, "skipped_non_supplement": 0,
                 "skipped_no_brand": 0, "skipped_empty": 0, "error": 0, "fetch_fail": 0}

        for i, url in enumerate(urls, 1):
            slug = url.rsplit("/", 2)[-2]
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
