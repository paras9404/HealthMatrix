"""One-off audit: how does the live Unbox Health product list compare to what's
already in our DB? Read-only — does not mutate anything."""
from __future__ import annotations

import re
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.models import Rating, Source, Supplement
from app.services.unbox_scraper import fetch_product_urls
from app.utils import slugify


def main():
    app = create_app()
    with app.app_context():
        source = Source.query.filter_by(slug="unbox-health").first()
        if not source:
            print("ERR: unbox-health source not seeded.", file=sys.stderr)
            sys.exit(1)

        # 1. Pull live URLs from unboxhealth.in/explore/products-list.
        print("Fetching live product list from unboxhealth.in/explore/products-list ...")
        live_urls = fetch_product_urls()
        print(f"Live URLs discovered: {len(live_urls)}\n")

        # Each Unbox URL ends with /<slug>/<uuid>. Build per-URL lookup keys.
        def keys(url: str):
            parts = url.rstrip("/").split("/")
            return {
                "url": url,
                "uuid": parts[-1] if len(parts) >= 2 else None,
                "slug": slugify(parts[-2]) if len(parts) >= 2 else None,
            }
        live = [keys(u) for u in live_urls]

        # 2. Pull our existing Unbox-Health-rated products.
        ratings = Rating.query.filter_by(source_id=source.id).all()
        db_urls = {r.report_url for r in ratings if r.report_url}
        # Build a slug index for cases where the rating row's report_url drifted.
        db_slug_idx = {s.slug for s in Supplement.query.with_entities(Supplement.slug).all()}

        print(f"DB ratings from Unbox Health: {len(ratings)}")
        print(f"DB total supplements (any source): {len(db_slug_idx)}")
        print()

        matched_by_url = 0
        matched_by_slug_only = 0
        new_urls: list[str] = []
        for entry in live:
            if entry["url"] in db_urls:
                matched_by_url += 1
                continue
            # Slug fallback — same product, possibly different report_url (a previous
            # import might have stored a different canonical form).
            if entry["slug"] and entry["slug"] in db_slug_idx:
                matched_by_slug_only += 1
                continue
            new_urls.append(entry["url"])

        # Live URLs that were probably retired by Unbox but still in our DB.
        live_url_set = {e["url"] for e in live}
        live_slug_set = {e["slug"] for e in live if e["slug"]}
        possibly_retired = []
        for r in ratings:
            if r.report_url in live_url_set:
                continue
            slug_part = None
            if r.report_url:
                parts = r.report_url.rstrip("/").split("/")
                slug_part = slugify(parts[-2]) if len(parts) >= 2 else None
            if slug_part and slug_part in live_slug_set:
                continue  # found by slug, just URL drift
            possibly_retired.append(r)

        print("=" * 60)
        print("MATCH SUMMARY (live vs DB)")
        print("=" * 60)
        print(f"  matched by exact report_url    : {matched_by_url}")
        print(f"  matched by slug only (URL drift): {matched_by_slug_only}")
        print(f"  NEW (not in DB)                 : {len(new_urls)}")
        print(f"  in DB but no longer in live list: {len(possibly_retired)}")
        print()

        # Pre-classify the new URLs by URL-segment hints — full classification needs
        # a per-page fetch but the URL slug alone resolves the obvious food cases
        # (paneer, ghee, oil, ice-cream, noodles) that our pipeline always skips.
        FOOD_HINTS = (
            "paneer", "ghee", "olive-oil", "mustard-oil", "cooking-oil", "coconut-oil",
            "ice-cream", "ice-cream-cone", "noodles", "idli-dosa-batter", "idly-dosa-batter",
            "dahi", "yogurt", "yoghurt", "milk", "honey", "chocolate", "cookies", "biscuit",
            "cereals", "muesli", "cornflakes", "bread", "snack-bars", "chips", "puffs",
            "peanut-butter", "almond-butter", "kombucha", "coffee", "snack",
        )

        def looks_like_food(url: str) -> bool:
            slug = url.rstrip("/").split("/")[-2].lower() if "/" in url else ""
            return any(h in slug for h in FOOD_HINTS)

        food_like = [u for u in new_urls if looks_like_food(u)]
        supp_like = [u for u in new_urls if not looks_like_food(u)]

        print(f"Of those {len(new_urls)} new URLs:")
        print(f"  • probably non-supplement (food/skip)  : {len(food_like)}")
        print(f"  • probably supplements (will import)   : {len(supp_like)}")
        print()

        print("First 15 LIKELY-NEW SUPPLEMENT URLs:")
        for u in supp_like[:15]:
            print(f"  + {u}")
        if len(supp_like) > 15:
            print(f"  ... and {len(supp_like) - 15} more")
        print()

        print("First 10 LIKELY-FOOD URLs that would be skipped:")
        for u in food_like[:10]:
            print(f"  - {u}")
        if len(food_like) > 10:
            print(f"  ... and {len(food_like) - 10} more")

        if possibly_retired:
            print()
            print("Sample of DB-only Unbox ratings (retired/renamed on Unbox?):")
            for r in possibly_retired[:5]:
                supp_name = r.supplement.name if r.supplement else "?"
                print(f"  • #{r.id} {supp_name} → {r.report_url}")


if __name__ == "__main__":
    main()
