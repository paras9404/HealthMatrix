"""Seed reference data only — categories + supported sources.

This file does NOT create demo supplements/brands/ratings. Real product data is
imported from external scrapers (e.g., `import_trustified.py`, `import_labdoor.py`).

Re-running `seed.py` is safe (upsert): it adds new categories/sources and updates
existing ones in place, without touching imported supplements or ratings.

Run with: python seed.py  (or `make seed`)
Note: requires the DB schema to exist. Run `flask db upgrade` first.
"""
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Category, Source


CATEGORIES = [
    {"name": "Vitamins", "slug": "vitamins", "icon": "vitamin", "sort_order": 1,
     "description": "Essential vitamins like Vitamin C, D, B-complex, and multivitamins."},
    {"name": "Minerals", "slug": "minerals", "icon": "mineral", "sort_order": 2,
     "description": "Important minerals including magnesium, zinc, calcium, and iron."},
    {"name": "Protein", "slug": "protein", "icon": "protein", "sort_order": 3,
     "description": "Whey, casein, plant-based and collagen protein supplements."},
    {"name": "Omega & Fish Oil", "slug": "omega-fish-oil", "icon": "fish", "sort_order": 4,
     "description": "Fish oil, krill oil, and plant-based omega-3 supplements."},
    {"name": "Probiotics", "slug": "probiotics", "icon": "probiotic", "sort_order": 5,
     "description": "Gut-health probiotics and digestive aids."},
    {"name": "Herbal", "slug": "herbal", "icon": "leaf", "sort_order": 6,
     "description": "Ashwagandha, turmeric, ginseng, and traditional herbal extracts."},
    {"name": "Sports & Performance", "slug": "sports-performance", "icon": "dumbbell", "sort_order": 7,
     "description": "Pre-workout, creatine, BCAAs, and performance supplements."},
    {"name": "Sleep & Stress", "slug": "sleep-stress", "icon": "moon", "sort_order": 8,
     "description": "Melatonin, magnesium glycinate, L-theanine, and adaptogens."},
]

SOURCES = [
    {"name": "Labdoor", "slug": "labdoor", "website_url": "https://labdoor.com",
     "rating_scale": "0-100", "sort_order": 1,
     "description": "Independent supplement testing lab with quality and value scores.",
     "is_verified": True},
    {"name": "Trustified", "slug": "trustified", "website_url": "https://www.trustified.in",
     "rating_scale": "Pass/Fail", "sort_order": 2,
     "description": "ARPIT TRUSTIFIED CERTIFICATION PVT LTD — independent third-party testing of supplements (India). Blind-tests sealed retail products; publishes pass/fail with video evidence at /passandfail.",
     "is_verified": True},
    {"name": "Unbox Health", "slug": "unbox-health", "website_url": "https://www.unboxhealth.in",
     "rating_scale": "0-10 (A+ to D)", "sort_order": 6,
     "description": "Unbox Health (India) — independent lab-tested ratings for supplements and food. Scores 0-10 with letter grades (A+ to D) based on Label Accuracy and Non-Toxicity sub-scores.",
     "is_verified": True},
    {"name": "ConsumerLab", "slug": "consumerlab", "website_url": "https://www.consumerlab.com",
     "rating_scale": "Pass/Fail", "sort_order": 6,
     "description": "Subscription-based independent testing of health and nutrition products.",
     "is_verified": True},
    {"name": "Examine.com", "slug": "examine", "website_url": "https://examine.com",
     "rating_scale": "Evidence-based", "sort_order": 6,
     "description": "Independent, evidence-based analysis of supplements and nutrition.",
     "is_verified": True},
    {"name": "Trustpilot", "slug": "trustpilot", "website_url": "https://www.trustpilot.com",
     "rating_scale": "0-5", "sort_order": 6,
     "description": "Consumer reviews and ratings.",
     "is_verified": False},
]


def upsert(model, lookup_field: str, rows: list[dict]) -> tuple[int, int]:
    """Insert new rows or update existing ones by lookup_field. Returns (new, updated)."""
    new = updated = 0
    for row in rows:
        existing = model.query.filter_by(**{lookup_field: row[lookup_field]}).first()
        if existing:
            for k, v in row.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.session.add(model(**row))
            new += 1
    db.session.commit()
    return new, updated


def seed():
    app = create_app()
    with app.app_context():
        cn, cu = upsert(Category, "slug", CATEGORIES)
        sn, su = upsert(Source, "slug", SOURCES)
        print(f"✓ Categories: {cn} new, {cu} updated  (total {len(CATEGORIES)})")
        print(f"✓ Sources:    {sn} new, {su} updated  (total {len(SOURCES)})")


if __name__ == "__main__":
    seed()
