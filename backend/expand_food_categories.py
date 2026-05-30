"""Add the 8 new food categories that absorb Unbox Health's non-supplement reviews.

Idempotent: each category is upserted by slug, so reruns are safe.

Run with: backend/venv/bin/python expand_food_categories.py
"""
from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Category

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# Sort order picks up after the 8 supplement categories (1..8). Icons reuse
# the existing palette keys when there's a sensible fit and otherwise fall back
# to the generic teal in data_fetcher's CATEGORY_PALETTE.get default.
NEW_CATEGORIES = [
    {"slug": "dairy",            "name": "Dairy",                       "icon": "probiotic", "sort_order": 9},
    {"slug": "cooking-oils",     "name": "Cooking Oils",                "icon": "fish",      "sort_order": 10},
    {"slug": "spreads",          "name": "Spreads & Honey",             "icon": "leaf",      "sort_order": 11},
    {"slug": "snacks-bars",      "name": "Snacks & Bars",               "icon": "dumbbell",  "sort_order": 12},
    {"slug": "chocolate-frozen", "name": "Chocolate & Frozen Desserts", "icon": "moon",      "sort_order": 13},
    {"slug": "cereals-bread",    "name": "Breakfast Cereals & Bread",   "icon": "vitamin",   "sort_order": 14},
    {"slug": "ready-to-eat",     "name": "Ready-to-Eat",                "icon": "mineral",   "sort_order": 15},
    {"slug": "beverages",        "name": "Coffee & Beverages",          "icon": "leaf",      "sort_order": 16},
]


def main():
    app = create_app()
    with app.app_context():
        created = 0
        existed = 0
        for spec in NEW_CATEGORIES:
            existing = Category.query.filter_by(slug=spec["slug"]).first()
            if existing:
                logger.info(f"  [exists] {spec['slug']} (id={existing.id})")
                existed += 1
                continue
            cat = Category(
                slug=spec["slug"],
                name=spec["name"],
                icon=spec["icon"],
                sort_order=spec["sort_order"],
                is_active=True,
                description=f"Products in the {spec['name'].lower()} category — added to support Unbox Health's broader catalog.",
            )
            db.session.add(cat)
            db.session.flush()
            logger.info(f"  ✓ created {spec['slug']:20s} id={cat.id}")
            created += 1
        db.session.commit()
        logger.info(f"\nDone. Created {created}, already existed {existed}.")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
