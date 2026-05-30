"""Add categories for Trustified/Labdoor products that previously got skipped:
spices/condiments, grains/pulses, and meat/eggs/seafood.

Idempotent — upsert by slug. Sort order continues after expand_food_categories.py
(which ended at 16).

Run with: backend/venv/bin/python expand_more_categories.py
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


NEW_CATEGORIES = [
    {"slug": "spices-condiments", "name": "Spices & Condiments", "icon": "leaf",     "sort_order": 17},
    {"slug": "grains-pulses",     "name": "Grains & Pulses",     "icon": "vitamin",  "sort_order": 18},
    {"slug": "meat-eggs",         "name": "Meat & Eggs",         "icon": "dumbbell", "sort_order": 19},
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
                description=f"Products in the {spec['name'].lower()} category.",
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
