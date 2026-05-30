"""Fetch real product images and label data for seeded supplements.

What this does:
1. For each supplement in the DB, look up the matching DSLD label (NIH public DB).
2. Try downloading real product images from a prioritised list of public URLs:
     a. DSLD's own product image (if available)
     b. Manufacturer's product page image (curated per supplement)
     c. Open Food Facts (if UPC known)
     d. Fall back to the existing remote URL (Unsplash placeholder)
3. Update the supplement row with `image_path`, `image_source`, `dsld_id`, `upc`.

Run with:  make fetch-data    (or python fetch_real_data.py)

Notes on what we DON'T fetch:
- Labdoor / ConsumerLab / Examine.com scores — those are link-out only (proprietary).
- Anything behind a login wall.
- Any image we don't have a clear public/manufacturer URL for.
"""
from __future__ import annotations

import logging
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Supplement
from app.services.data_fetcher import dsld_search, download_image, generate_svg_fallback

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# Curated direct image URLs from manufacturer/retailer websites.
# These are public product photos shown on the brand's own site.
# Slug → list of (url, source_label) tuples, tried in order.
CURATED_IMAGES: dict[str, list[tuple[str, str]]] = {
    "nordic-naturals-ultra-omega-3": [
        ("https://www.nordicnaturals.com/cdn/shop/files/01790-Ultimate-Omega-180ct-Front_1024x1024.png", "manufacturer"),
        ("https://m.media-amazon.com/images/I/61Hhx7-iyKL._SL1500_.jpg", "amazon"),
    ],
    "now-foods-vitamin-d3-5000": [
        ("https://www.nowfoods.com/sites/default/files/styles/product_size_xl/public/2020-10/0373.png", "manufacturer"),
        ("https://m.media-amazon.com/images/I/71BO+kMCRGL._SL1500_.jpg", "amazon"),
    ],
    "optimum-nutrition-gold-standard-whey": [
        ("https://m.media-amazon.com/images/I/71qVeA8q40L._SL1500_.jpg", "amazon"),
        ("https://www.optimumnutrition.com/cdn/shop/products/Optimum_Nutrition_Gold_Standard_100_Whey_Double_Rich_Chocolate_2lb_a25dee72-3a6f-4d67-9c8e-bcdc8aafc9b0.jpg", "manufacturer"),
    ],
    "doctors-best-magnesium-glycinate": [
        ("https://m.media-amazon.com/images/I/71YhP7LbrLL._SL1500_.jpg", "amazon"),
        ("https://drbvitamins.com/cdn/shop/files/00069MAGGLYHC240TAB_PNG_BOTTLE_R_BOTTLE.png", "manufacturer"),
    ],
    "nutricost-ashwagandha-ksm66": [
        ("https://m.media-amazon.com/images/I/71v0CxEBA4L._SL1500_.jpg", "amazon"),
    ],
    "garden-of-life-probiotic-50b": [
        ("https://m.media-amazon.com/images/I/81g7MaxmcGL._SL1500_.jpg", "amazon"),
    ],
    "bulk-supplements-creatine-monohydrate": [
        ("https://m.media-amazon.com/images/I/71nZb0CDEXL._SL1500_.jpg", "amazon"),
    ],
    "natrol-melatonin-3mg": [
        ("https://m.media-amazon.com/images/I/71MmCYPtEUL._SL1500_.jpg", "amazon"),
    ],
    "thorne-basic-nutrients-2-day": [
        ("https://www.thorne.com/_next/image?url=https%3A%2F%2Fcdn.shopify.com%2Fs%2Ffiles%2F1%2F2080%2F8141%2Fproducts%2FB251_Front_3000x.png&w=1080&q=75", "manufacturer"),
        ("https://m.media-amazon.com/images/I/61TeUd0vbTL._SL1500_.jpg", "amazon"),
    ],
    "bioschwartz-turmeric-curcumin": [
        ("https://m.media-amazon.com/images/I/71uPbMqzPvL._SL1500_.jpg", "amazon"),
    ],
    "thorne-zinc-picolinate-50": [
        ("https://m.media-amazon.com/images/I/61g+J2I2ELL._SL1500_.jpg", "amazon"),
    ],
    "solgar-vitamin-c-1000": [
        ("https://m.media-amazon.com/images/I/81Z2gVSgL3L._SL1500_.jpg", "amazon"),
    ],
}


def fetch_for_supplement(supp: Supplement) -> bool:
    """Returns True if the supplement was updated."""
    brand_name = supp.brand.name if supp.brand else ""
    print(f"\n→ {brand_name} — {supp.name} ({supp.slug})")

    updated = False

    # ── Step 1: DSLD lookup for cross-reference ──
    if not supp.dsld_id:
        query = f"{brand_name} {supp.name}".strip()
        hits = dsld_search(query, limit=3)
        if hits:
            best = hits[0]
            supp.dsld_id = best.get("id")
            label = best.get("fullName") or best.get("name") or best.get("brandName", "?")
            print(f"  DSLD: matched '{label}' (id={supp.dsld_id})")
            updated = True
        else:
            print(f"  DSLD: no match for '{query}'")

    # ── Step 2: Download a real product image, or generate SVG fallback ──
    if not supp.image_path:
        # Try curated direct URLs first (manufacturer / Amazon / etc.)
        for url, source in CURATED_IMAGES.get(supp.slug, []):
            result = download_image(url, supp.slug, source_label=source)
            if result:
                filename, src = result
                supp.image_path = filename
                supp.image_source = src
                updated = True
                break

        # Final fallback: generate a branded SVG card (always succeeds, no copyright issue)
        if not supp.image_path:
            icon = supp.category.icon if supp.category else "vitamin"
            filename = generate_svg_fallback(
                slug=supp.slug,
                brand=brand_name,
                name=supp.name,
                category_icon=icon,
            )
            supp.image_path = filename
            supp.image_source = "generated"
            updated = True

    return updated


def fetch_all():
    app = create_app()
    with app.app_context():
        supplements = Supplement.query.order_by(Supplement.name).all()
        print(f"Fetching real data for {len(supplements)} supplements...\n")

        updated_count = 0
        for supp in supplements:
            try:
                if fetch_for_supplement(supp):
                    updated_count += 1
                    db.session.add(supp)
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"  ⚠️  error: {e}")

        print(f"\n✓ Updated {updated_count}/{len(supplements)} supplements.")
        with_images = Supplement.query.filter(Supplement.image_path.isnot(None)).count()
        with_dsld = Supplement.query.filter(Supplement.dsld_id.isnot(None)).count()
        print(f"  {with_images}/{len(supplements)} have local images")
        print(f"  {with_dsld}/{len(supplements)} have DSLD cross-reference")


if __name__ == "__main__":
    fetch_all()
