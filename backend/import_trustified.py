"""Import all Trustified pass/fail products into the database.

Pipeline:
1. Fetch the Trustified pass/fail sitemap (~230 product URLs).
2. For each URL, scrape the product page (1 sec rate limit).
3. Map Trustified category → one of our existing supplement categories.
   Skip non-supplement products (rice, milk, salt, masala, etc.) — we are a supplement-only platform.
4. Auto-create the Brand if we don't have it.
5. Create or update the Supplement (with full info: name, description, image_url, slug).
6. Create or update the Rating from the "Trustified" source, with verdict, batch_no, tested_by, etc.
   Only Pass products get a buy_url (Trustified policy).
7. Download the product image from static.wixstatic.com → backend/static/images/supplements/.

Run with: make import-trustified  (or python import_trustified.py)
Optional: --limit N to import only the first N products (for testing).
"""
from __future__ import annotations

import argparse
import re
import logging
import sys
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Brand, Category, Source, Supplement, Rating
from app.services.trustified_scraper import (
    TrustifiedProduct,
    fetch_product,
    fetch_product_urls,
)
from app.services.data_fetcher import download_image, generate_svg_fallback

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ---------- Category mapping ----------
#
# Trustified tests both supplements and grocery food/condiments. We import
# everything: supplement keywords map to the supplement categories; food
# keywords map to the food/grocery categories the catalog gained (dairy,
# spreads, beverages, …) plus the more recent spices/grains/meat additions.
# `map_category` walks the longest keyword first so "peanut protein" wins
# over "peanut butter" when both could match.

CATEGORY_KEYWORD_MAP: dict[str, str] = {
    # ----- Protein -----
    "whey protein": "protein",
    "whey isolate": "protein",
    "whey": "protein",
    "plant protein": "protein",
    "soy protein": "protein",
    "pea protein": "protein",
    "casein": "protein",
    "mass gainer": "protein",
    "muscle gainer": "protein",
    "protein bar": "protein",
    "yeast protein": "protein",
    "peanut protein": "protein",

    # ----- Sports & performance -----
    "creatine": "sports-performance",
    "pre-workout": "sports-performance",
    "preworkout": "sports-performance",
    "pre workout": "sports-performance",
    "eaa": "sports-performance",
    "bcaa": "sports-performance",

    # ----- Vitamins -----
    "multivitamin": "vitamins",
    "multi vitamin": "vitamins",
    "vitamin c": "vitamins",
    "vitamin d": "vitamins",
    "vitamin": "vitamins",
    "vitamins & minerals": "vitamins",

    # ----- Minerals -----
    "magnesium": "minerals",
    "zinc": "minerals",
    "calcium": "minerals",
    "iron": "minerals",
    "mineral": "minerals",

    # ----- Omega -----
    "omega 3": "omega-fish-oil",
    "omega-3": "omega-fish-oil",
    "fish oil": "omega-fish-oil",
    "omega": "omega-fish-oil",

    # ----- Probiotics -----
    "probiotic": "probiotics",

    # ----- Herbal -----
    "ashwagandha": "herbal",
    "shilajit": "herbal",
    "turmeric": "herbal",
    "curcumin": "herbal",
    "apple cider vinegar": "herbal",
    "isabgol": "herbal",
    "psyllium": "herbal",
    "glutathione": "herbal",
    "shatavari": "herbal",

    # ----- Sleep & stress -----
    "melatonin": "sleep-stress",
    "ksm-66": "herbal",  # ashwagandha extract

    # ----- Dairy -----
    "milk": "dairy",
    "ghee": "dairy",
    "paneer": "dairy",
    "butter": "dairy",
    "cheese": "dairy",
    "yogurt": "dairy",
    "yoghurt": "dairy",
    "dahi": "dairy",

    # ----- Cooking oils -----
    "mustard oil": "cooking-oils",
    "olive oil": "cooking-oils",
    "cooking oil": "cooking-oils",

    # ----- Spreads / honey / condiments -----
    "peanut butter": "spreads",
    "honey": "spreads",
    "ketchup": "spreads",

    # ----- Snacks & bars -----
    "snack bar": "snacks-bars",
    "chips": "snacks-bars",
    "puffs": "snacks-bars",
    "biscuit": "snacks-bars",
    "cookie": "snacks-bars",
    "makhana": "snacks-bars",

    # ----- Chocolate / frozen desserts -----
    "chocolate": "chocolate-frozen",
    "cocoa": "chocolate-frozen",
    "ice cream": "chocolate-frozen",
    "ice-cream": "chocolate-frozen",

    # ----- Cereals & bread -----
    "bread": "cereals-bread",
    "oats": "cereals-bread",
    "muesli": "cereals-bread",
    "cornflakes": "cereals-bread",
    "granola": "cereals-bread",

    # ----- Ready-to-eat -----
    "instant noodles": "ready-to-eat",
    "noodles": "ready-to-eat",
    "idli": "ready-to-eat",
    "dosa": "ready-to-eat",
    "soya chunks": "ready-to-eat",
    "soy chunks": "ready-to-eat",

    # ----- Coffee & beverages -----
    "coffee": "beverages",
    "tea": "beverages",
    "juice": "beverages",
    "energy drink": "beverages",
    "beverage": "beverages",

    # ----- Spices & condiments (new category) -----
    "garam masala": "spices-condiments",
    "turmeric powder": "spices-condiments",
    "haldi": "spices-condiments",
    "kashmiri": "spices-condiments",
    "chilli": "spices-condiments",
    "masala": "spices-condiments",
    "spice": "spices-condiments",
    "salt": "spices-condiments",
    "pickle": "spices-condiments",
    "chutney": "spices-condiments",

    # ----- Grains & pulses (new category) -----
    "rice": "grains-pulses",
    "atta": "grains-pulses",
    "flour": "grains-pulses",
    "dal": "grains-pulses",
    "lentil": "grains-pulses",

    # ----- Meat & eggs (new category) -----
    "chicken": "meat-eggs",
    "meat": "meat-eggs",
    "egg": "meat-eggs",
    "fish ": "meat-eggs",  # trailing space avoids matching "fish oil"
}

# Backward-compat alias — older code paths (e.g. in source_import.py) still
# reference SUPPLEMENT_CATEGORY_MAP.
SUPPLEMENT_CATEGORY_MAP = CATEGORY_KEYWORD_MAP

# Nothing is unconditionally skipped now. Kept as an empty list so any callers
# expecting the symbol still work.
SKIP_KEYWORDS: list[str] = []


def map_category(trustified_category: Optional[str], product_name: str = "",
                 url_slug: Optional[str] = None) -> Optional[str]:
    """Return our category slug, or None when no keyword matches.

    Many Trustified pages don't populate the on-page Category or Product Name
    fields — `product_name` ends up echoing the brand. We accept an optional
    `url_slug` so callers can fall back to keyword-matching the slug itself
    (e.g. `everestmeatmasala`, `dmarthaldipowder`)."""
    haystack = f"{trustified_category or ''} {product_name} {url_slug or ''}".lower()

    # Walk the longest keyword first so "peanut protein" beats "peanut butter"
    # and "whey isolate" beats "whey".
    for kw in sorted(CATEGORY_KEYWORD_MAP, key=len, reverse=True):
        if kw in haystack:
            return CATEGORY_KEYWORD_MAP[kw]
    return None


# ---------- Slug helpers ----------

def slugify(text: str, max_len: int = 200) -> str:
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


def parse_iso_date(s: Optional[str]) -> Optional[datetime]:
    """Parse a 'date published' string into a date. Trustified uses '17 July 2024' or '23 April 2025'."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ---------- Import a single product ----------

def _record_skip(stats: dict, prod: TrustifiedProduct, reason: str) -> None:
    """Append a skipped product to stats['skipped_items'] (if the caller opted
    in by passing such a list). Caps to 500 entries so a long bulk run can't
    blow up admin response payloads."""
    items = stats.get("skipped_items")
    if items is None or len(items) >= 500:
        return
    items.append({
        "slug": prod.slug,
        "name": prod.product_name or prod.title or prod.slug,
        "url": prod.url,
        "category": prod.category,
        "verdict": prod.verdict,
        "reason": reason,
    })


def import_product(prod: TrustifiedProduct, source: Source, stats: dict) -> None:
    cat_slug = map_category(prod.category, prod.product_name or "", prod.slug)
    if not cat_slug:
        logger.info(f"  [skip uncategorized]  {prod.slug}  category={prod.category!r}")
        stats["skipped_food"] += 1
        _record_skip(stats, prod, "uncategorized")
        return

    # Verdict-less products are still worth importing — the rating just won't
    # carry a Pass/Fail score. Brand-less products, on the other hand, would
    # require us to guess at the brand from page text, and the admin asked for
    # those to be surfaced for manual review instead of auto-inferred.
    if not prod.brand:
        logger.info(f"  [skip no-brand]       {prod.slug}")
        stats["skipped_no_brand"] += 1
        _record_skip(stats, prod, "no-brand")
        return

    category = Category.query.filter_by(slug=cat_slug).first()
    if not category:
        logger.warning(f"  [error] category {cat_slug!r} not in DB — skipping {prod.slug}")
        stats["error"] += 1
        _record_skip(stats, prod, f"category {cat_slug!r} missing in DB")
        return

    brand = get_or_create_brand(prod.brand)

    # Form the supplement name. Prefer "<Brand> <ProductName>" if pname doesn't already include the brand.
    pname = prod.product_name or prod.title or prod.slug
    if pname and prod.brand and prod.brand.lower() not in pname.lower():
        full_name = f"{prod.brand} {pname}".strip()
    else:
        full_name = pname

    # Some Trustified pages embed the entire test report into the "Product Name"
    # field (no proper field separator). Cap names to 180 chars at a word boundary.
    if len(full_name) > 180:
        full_name = full_name[:180].rsplit(" ", 1)[0] + "…"

    supp_slug = slugify(prod.slug or full_name, max_len=240)

    # Description: brief auto-summary for the catalogue
    desc_parts = [f"{prod.brand} {pname}"]
    if prod.category:
        desc_parts.append(f"Category: {prod.category}.")
    if prod.tested_by:
        desc_parts.append(f"Tested by {prod.tested_by}.")
    if prod.date_published:
        desc_parts.append(f"Tested on {prod.date_published}.")
    description = " ".join(desc_parts)

    supp = Supplement.query.filter_by(slug=supp_slug).first()
    is_new = supp is None
    if is_new:
        supp = Supplement(
            slug=supp_slug,
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

    # Download image (or generate SVG fallback if remote fails)
    if prod.image_url:
        result = download_image(prod.image_url, supp.slug, source_label="trustified")
        if result:
            filename, src = result
            supp.image_path = filename
            supp.image_source = src
        else:
            supp.image_path = generate_svg_fallback(
                slug=supp.slug, brand=prod.brand, name=pname,
                category_icon=category.icon or "vitamin",
            )
            supp.image_source = "generated"
    else:
        if not supp.image_path:
            supp.image_path = generate_svg_fallback(
                slug=supp.slug, brand=prod.brand, name=pname,
                category_icon=category.icon or "vitamin",
            )
            supp.image_source = "generated"

    # Build / update the Trustified Rating. When the Trustified page didn't
    # surface a Pass/Fail verdict (some FMCG pages don't), keep the rating
    # row with score=None instead of forcing it to 0.0 — that way the listing
    # shows "Untested" rather than a misleading fail.
    rating = Rating.query.filter_by(supplement_id=supp.id, source_id=source.id).first()
    verdict_lower = (prod.verdict or "").lower()
    is_pass = "pass" in verdict_lower and "fail" not in verdict_lower
    is_fail = "fail" in verdict_lower
    if is_pass:
        score: Optional[float] = 100.0
    elif is_fail:
        score = 0.0
    else:
        score = None
    summary_bits = []
    if prod.tested_by:
        summary_bits.append(f"Tested by {prod.tested_by}.")
    if prod.batch_no:
        summary_bits.append(f"Batch {prod.batch_no}.")
    if prod.verdict:
        summary_bits.append(f"Status: {prod.verdict}.")
    summary_text = " ".join(summary_bits) or "Trustified pass/fail report."

    rating_data = {
        "score": score,
        "max_score": 100.0,
        "verdict": prod.verdict,
        "summary": summary_text,
        "report_url": prod.url,
        "buy_url": prod.buy_url if is_pass else None,
        "tested_at": parse_iso_date(prod.date_published),
        "batch_no": prod.batch_no,
        "manufacturing_date": prod.manufacturing_date,
        "expiration_date": prod.expiration_date,
        "tested_by": prod.tested_by,
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
        f"  ✓ {('NEW' if is_new else 'UPD')} {supp.slug:<50} {prod.brand:<20} {(prod.verdict or '—'):<8} "
        f"buy={'Y' if rating_data['buy_url'] else '-'} img={supp.image_source}"
    )


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Only import the first N products (for testing).")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        source = Source.query.filter_by(slug="trustified").first()
        if not source:
            logger.error("Trustified source not in DB. Run `make seed` first.")
            sys.exit(1)

        logger.info("Fetching sitemap...")
        urls = fetch_product_urls()
        logger.info(f"Found {len(urls)} product URLs in sitemap.\n")

        if args.limit:
            urls = urls[:args.limit]
            logger.info(f"Limiting to first {len(urls)} for this run.\n")

        stats = {"new": 0, "updated": 0, "skipped_food": 0, "skipped_empty": 0, "skipped_no_brand": 0, "error": 0, "fetch_fail": 0}

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
                    db.session.commit()  # flush periodically
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
