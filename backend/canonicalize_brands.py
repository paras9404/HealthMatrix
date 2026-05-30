"""Canonicalize polluted brand rows.

Some scraped product titles have no clear "Brand: Product" separator (e.g., Trustified's
"Nutrabay Creatine"), so the brand-extraction heuristic stored the entire phrase as the brand
name. This creates a mess: a single real brand ends up split across multiple Brand rows
(Nutrabay, Nutrabay Creatine, Nutrabay Gold, Nutrabay Pro Fish Oil Omega, ...) and the
deduplicator can't merge supplements that should clearly be the same product.

This script finds Brand rows whose name starts with another Brand's name + a space, then
reassigns all supplements from the longer "polluted" brand to the shorter "canonical" one
and deletes the polluted row. The shortest fully-qualified name is treated as canonical
because it's almost always the actual brand (e.g., "Nutrabay" — not "Nutrabay Creatine").

Run with:  make canonicalize-brands [DRY=1]
"""
from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Brand, Supplement

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def find_polluted_brands() -> list[tuple[Brand, Brand]]:
    """Return (polluted, canonical) pairs.

    Two brands are linked when one's name is a prefix of the other's name (e.g.
    "Nutrabay" and "Nutrabay Creatine"). The canonical is whichever has MORE supplements
    (the established brand entry). Length is used as a tie-breaker: shorter name wins,
    because in the truly ambiguous case it's almost always the actual base brand."""
    brands = Brand.query.filter(Brand.is_active.is_(True)).order_by(Brand.name).all()
    by_lower = {b.name.lower(): b for b in brands}

    pairs: list[tuple[Brand, Brand]] = []
    seen_polluted: set[int] = set()

    for b in brands:
        if b.id in seen_polluted:
            continue
        words = b.name.split()
        # Try every prefix of the brand name (longest match first)
        for i in range(len(words) - 1, 0, -1):
            prefix = " ".join(words[:i])
            cand = by_lower.get(prefix.lower())
            if not cand or cand.id == b.id or cand.id in seen_polluted:
                continue

            # Pick canonical = whichever brand has more supplements; shorter name as tiebreaker
            b_count = b.supplements.count()
            cand_count = cand.supplements.count()
            if cand_count > b_count:
                polluted, canonical = b, cand
            elif b_count > cand_count:
                polluted, canonical = cand, b
            else:
                # Equal counts — fall back to shorter name as canonical
                polluted, canonical = (b, cand) if len(b.name) > len(cand.name) else (cand, b)

            pairs.append((polluted, canonical))
            seen_polluted.add(polluted.id)
            break

    return pairs


def canonicalize(dry_run: bool = False) -> None:
    app = create_app()
    with app.app_context():
        pairs = find_polluted_brands()
        logger.info(f"Found {len(pairs)} polluted brands.\n")

        if dry_run:
            for polluted, canonical in pairs:
                psupp = polluted.supplements.count()
                csupp = canonical.supplements.count()
                logger.info(
                    f"  {polluted.name!r:<45} ({psupp} supps) → "
                    f"{canonical.name!r:<25} ({csupp} supps)"
                )
            return

        for polluted, canonical in pairs:
            psupp = polluted.supplements.count()
            for s in list(polluted.supplements.all()):
                s.brand_id = canonical.id
            db.session.flush()
            db.session.delete(polluted)
            logger.info(f"  ✓ {polluted.name!r} ({psupp} supps) → {canonical.name!r}")

        db.session.commit()
        logger.info(f"\n✓ Canonicalized {len(pairs)} polluted brand rows.")
        logger.info(f"  Brands now: {Brand.query.filter(Brand.is_active.is_(True)).count()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    canonicalize(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
