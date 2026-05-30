"""For Trustified products (which have watermarked main images), demote the
watermarked original to the end of the gallery and promote the first clean
fetched image to primary (display_order = 0).

Also updates supplements.image_path so the browse-card thumbnail uses the
clean image too.

Run:  python promote_clean_images.py [--source trustified] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Supplement, SupplementImage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def promote_for(supp: Supplement, dry_run: bool = False) -> bool:
    """Reorder so a clean ('bing-search') image comes first. Returns True if changed."""
    images = list(supp.images)
    if len(images) < 2:
        return False

    watermarked = [i for i in images if i.image_source != "bing-search"]
    clean = [i for i in images if i.image_source == "bing-search"]

    if not clean or not watermarked:
        return False

    # Prefer a 'main' type clean image first; fall back to any clean image
    clean_main = next((i for i in clean if i.image_type == "main"), clean[0])

    # New order: clean_main, then other clean images (preserving relative order),
    # then watermarked at the end
    other_clean = [i for i in clean if i is not clean_main]
    new_order = [clean_main] + other_clean + watermarked

    changed = False
    for new_idx, img in enumerate(new_order):
        if img.display_order != new_idx:
            changed = True
            if not dry_run:
                img.display_order = new_idx

    # Also point the legacy supplements.image_path at the new primary so
    # browse-card thumbnails (which read supplement.image) get the clean image
    if clean_main.image_path and supp.image_path != clean_main.image_path:
        changed = True
        if not dry_run:
            supp.image_path = clean_main.image_path
            supp.image_source = "bing-search"

    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="trustified",
                        help="Original image_source to promote-over (default: trustified)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        # Find supplements where the legacy main was from this source AND we now
        # have at least one bing-search image
        supps = (Supplement.query
                 .filter(Supplement.image_source == args.source)
                 .all())

        promoted = 0
        for supp in supps:
            if promote_for(supp, dry_run=args.dry_run):
                promoted += 1
                logger.info(f"  promoted #{supp.id} {supp.slug}")

        if not args.dry_run:
            db.session.commit()
        logger.info(f"\nDone. Promoted {promoted}/{len(supps)} {args.source} supplements"
                    f"{' (dry-run, nothing saved)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
