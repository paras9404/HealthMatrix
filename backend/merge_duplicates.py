"""Merge supplement rows that represent the same product across different scraping sources.

Each scraper (Trustified, Labdoor, Unbox Health) creates its own Supplement row even when
the same physical product is reviewed by multiple platforms. This script collapses those
duplicates so the product gets multiple ratings (= multi-source = stronger trust signal).

Matching strategy
-----------------
For each brand, we compare every pair of its supplements using token-set Jaccard similarity
on a NORMALIZED-and-NOISE-STRIPPED token set:

1. Lowercase + remove brand prefix + drop non-alphanumerics.
2. Tokenize and remove noise tokens (pack sizes, flavor descriptors, common brand sub-line
   names like "atom", "gold-standard", "biozyme", "raw", "premium", etc.).
3. Compute Jaccard = |A ∩ B| / |A ∪ B|.

Two safety guards prevent over-merging:

- **Mutually-exclusive token check**: pairs that disagree on any of these tokens are NEVER
  merged because they identify a different product (e.g., "whey isolate" vs "whey concentrate").
  Examples: isolate vs concentrate, vegan vs fish, men vs women, kids vs adult, d3 vs k2,
  preworkout vs postworkout.
- **Defining-token requirement**: at least one product-defining token must appear in BOTH
  (whey, omega, creatine, multivitamin, magnesium, zinc, etc.). Random short matches don't merge.

Threshold: Jaccard ≥ 0.5 AND the two safety guards pass → merge.

Survivor + losers
-----------------
Survivor is the row with the most ratings (oldest as tie-breaker). Losers' ratings are
reassigned to the survivor (preserving uniqueness on supplement_id+source_id), images and
external IDs are merged onto the survivor, then losers are deleted.

Run with:  make merge-duplicates [DRY=1]
"""
from __future__ import annotations

import argparse
import logging
import re
from collections import defaultdict
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Brand, Supplement, SupplementAlias, Rating

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# Tokens that don't change product identity and can be safely dropped before matching.
# We are CONSERVATIVE here — we don't strip brand sub-line markers (Biozyme, Biozorb,
# Atom, Gold, Performance, etc.) because those often distinguish real product variants.
_NOISE_TOKENS = {
    # Pack containers (truly noise)
    "sachet", "sachets", "stick", "sticks", "pack", "packs", "bottle", "bottles",
    "ct", "count", "servings", "serving",
    # NOTE: form words (tablet, capsule, softgel, gummy, powder, liquid, drops, syrup)
    # are NOT in noise — they distinguish SKUs (Liquid Melatonin ≠ Melatonin Capsules).
    # See _DISCRIMINATIVE_TOKENS below.
    # Units
    "g", "gm", "gms", "kg", "mg", "mcg", "iu", "ml", "l", "oz", "lb",
    # NOTE: dosage numbers are KEPT — they distinguish products (D3 1000IU vs D3 5000IU
    # are NOT the same supplement; Magnesium 200mg vs 400mg are different doses).
    # Flavor descriptors
    "flavor", "flavored", "flavour", "flavoured", "unflavored", "unflavoured",
    "chocolate", "vanilla", "strawberry", "mango", "kulfi", "coffee", "cocoa",
    "double", "rich", "dark", "light", "creamy", "natural",
    "choco", "crunch", "berry", "classic",
    # Generic marketing adjectives — same product wording variants across sources
    "raw", "pure", "premium", "ultra", "complete", "extra", "high", "low",
    "wellness", "vitals", "wonder", "boost", "booster", "essential", "essentials",
    # Year stamps Trustified appends (e.g., "[2024]")
    "2023", "2024", "2025", "2026",
    # Stop words
    "and", "with", "for", "the", "of", "in", "by", "from",
}

# Token aliases — treated as the same word during matching. Resolves "omega-3 fish oil"
# vs "fish oil" by giving fish/oil/omega/3 a single canonical form.
_ALIASES = {
    "1": "1", "2": "2", "3": "3",
    "fish": "fish", "oil": "oil",
    "omega": "omega",
    # "antarctic" used by some krill brands but not all
    "antarctic": "krill",  # collapse "antarctic krill" and "krill" to same token
    "deep": "fish", "sea": "fish",  # "deep sea fish oil" same as "fish oil"
    # "professional grade" / "softgels" already in noise via flavor descriptors
}

# STRICT discriminators: if one product has a token from the group and the other does
# NOT, the products are different. (Vegan vs non-vegan, isolate vs not-isolate, men vs
# women, D3 vs no-D3 — these always matter.)
_STRICT_DISCRIMINATIVE = [
    # Protein type
    {"isolate"}, {"concentrate"}, {"blend"}, {"hydrolyzed", "hydrolysate"},
    # Animal vs plant
    {"vegan", "plant"},
    # Demographic targeting
    {"men", "male", "mens"},
    {"women", "female", "womens"},
    {"kids", "kid", "child", "children"},
    # Specific vitamin variants
    {"d3"}, {"d2"}, {"k2"},
    {"b12"}, {"b6"}, {"b9"}, {"b1"}, {"b2"}, {"a"}, {"e"},
    # Pre/post workout
    {"pre", "preworkout"}, {"post", "postworkout"},
    # Brand sub-lines (different sub-lines = different SKUs)
    {"biozyme"}, {"biozorb"}, {"atom"}, {"isoboost"}, {"isorich"},
    {"performance"}, {"max"}, {"elite"}, {"advanced"}, {"professional"},
    {"sport", "sports"}, {"gainer", "mass"},
    {"pwr"}, {"plus"}, {"daily"},
]

# SOFT discriminators: if BOTH sides specify a member of the group, the tokens must
# overlap (otherwise different forms). If only one side specifies, the attribute is
# unspecified for the other and a match is still possible.
# Example: "Liquid Melatonin" vs "Melatonin Capsules" — both specify a form, different
# tokens → different SKUs. But "Nutrabay Creatine" (no form) vs "Nutrabay … Powder" (has
# powder) — only one specifies, so they could still be the same product.
_SOFT_DISCRIMINATIVE = [
    {"liquid", "drops", "syrup", "spray"},
    {"tablet", "tablets", "capsule", "capsules", "softgel", "softgels", "caplet", "caplets"},
    {"gummy", "gummies"},
    {"powder", "powders"},
]

# Tokens that DEFINE a product class. At least one of these must appear in BOTH names
# for a merge to be considered. Prevents random short matches.
_DEFINING_TOKENS = {
    "whey", "casein", "protein", "plant", "soy", "pea", "creatine", "monohydrate",
    "omega", "fish", "krill", "algal", "multivitamin", "vitamin", "biotin",
    "magnesium", "zinc", "iron", "calcium", "selenium",
    "ashwagandha", "shilajit", "turmeric", "curcumin", "moringa", "berberine",
    "coq10", "astaxanthin", "collagen", "probiotic", "melatonin", "electrolyte",
    "preworkout", "bcaa", "eaa", "glutamine", "fiber", "biotin", "shatavari",
    "ginseng", "elderberry", "spirulina", "chlorella",
    "bisglycinate", "glycinate", "picolinate", "citrate", "oxide",
}


def _normalize_tokens(name: str, brand: Optional[str]) -> set[str]:
    """Lowercase, strip brand prefix, drop noise, apply aliases, return a token set."""
    if not name:
        return set()
    s = name.lower()
    # Strip brand prefix (and any leading ATOM/PWR/Pro line markers if they precede the brand)
    if brand:
        bl = brand.lower()
        # Try the exact brand and a normalized variant (drop "Inc", "Nutrition")
        for variant in (bl, bl.replace("nutrition", "").strip(),
                        bl.replace("foods", "").strip(),
                        bl.replace("supplements", "").strip()):
            if variant and s.startswith(variant):
                s = s[len(variant):].lstrip(" -|:")
                break
    s = re.sub(r"[^a-z0-9]+", " ", s)
    raw_tokens = [t for t in s.split() if t and t not in _NOISE_TOKENS]
    return {_ALIASES.get(t, t) for t in raw_tokens}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _disagrees_on_discriminative(a: set[str], b: set[str]) -> bool:
    """Return True if the two token sets disagree on any product-defining attribute.

    STRICT groups: if one side has a token from the group and the other doesn't, the
    products are different (e.g., vegan vs not, men vs unspecified, D3 vs not-D3).

    SOFT groups: if BOTH sides have tokens from the group but the tokens are different,
    the products are different. If only one side specifies (e.g., one says "powder" and
    the other says nothing about form), that's NOT a disagreement."""
    for group in _STRICT_DISCRIMINATIVE:
        if bool(a & group) != bool(b & group):
            return True
    for group in _SOFT_DISCRIMINATIVE:
        a_in = a & group
        b_in = b & group
        if a_in and b_in and not (a_in & b_in):
            return True
    return False


def _shares_defining_token(a: set[str], b: set[str]) -> bool:
    return bool(a & b & _DEFINING_TOKENS)


def _should_merge(a: set[str], b: set[str], cross_source: bool, threshold: float = 0.6) -> tuple[bool, float]:
    """`cross_source` is True when the two supplements come from different scraping
    sources (e.g. Trustified vs Unbox). The single-defining-token rule only fires when
    `cross_source` is True — within one source, different names mean different SKUs."""
    if not a or not b:
        return False, 0.0
    if _disagrees_on_discriminative(a, b):
        return False, 0.0
    if not _shares_defining_token(a, b):
        return False, 0.0
    sim = _jaccard(a, b)

    # Subset containment — works regardless of source (≥2 tokens shared = strong signal)
    if len(a) >= 2 and a.issubset(b):
        return True, sim
    if len(b) >= 2 and b.issubset(a):
        return True, sim

    # Single-defining-token rule. ONLY when the two products come from different sources.
    # Example: "Nutrabay Creatine" (Trustified, {creatine}) and "Nutrabay Pure Series
    # Micronised Creatine Powder Monohydrate" (Unbox, {series, micronised, creatine,
    # monohydrate}) — same brand, different sources, defining token shared → same product.
    if cross_source:
        smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
        if len(smaller) == 1 and smaller.issubset(larger):
            only_token = next(iter(smaller))
            if only_token in _DEFINING_TOKENS:
                return True, sim

    return sim >= threshold, sim


def _find_groups(supplements: list[Supplement]) -> list[list[Supplement]]:
    """Group supplements by Jaccard-similarity within the same brand. Union-Find."""
    parent = {s.id: s.id for s in supplements}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    by_brand: dict[int, list[Supplement]] = defaultdict(list)
    for s in supplements:
        if s.brand_id:
            by_brand[s.brand_id].append(s)

    for brand_id, items in by_brand.items():
        # Pre-compute token sets and source-id sets for everyone in this brand
        info = {
            s.id: {
                "tokens": _normalize_tokens(s.name, s.brand.name if s.brand else None),
                "sources": {r.source_id for r in s.ratings.all()},
            }
            for s in items
        }
        ids = list(info.keys())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = info[ids[i]], info[ids[j]]
                cross_source = bool(a["sources"] and b["sources"]
                                    and not (a["sources"] & b["sources"]))
                merge_ok, _sim = _should_merge(a["tokens"], b["tokens"], cross_source)
                if merge_ok:
                    union(ids[i], ids[j])

    # Collect connected components
    groups: dict[int, list[Supplement]] = defaultdict(list)
    for s in supplements:
        groups[find(s.id)].append(s)
    return [g for g in groups.values() if len(g) > 1]


def merge(dry_run: bool = False) -> None:
    app = create_app()
    with app.app_context():
        all_supps = Supplement.query.all()
        groups = _find_groups(all_supps)
        logger.info(f"Inspected {len(all_supps)} supplements.")
        logger.info(f"Found {len(groups)} duplicate groups covering {sum(len(g) for g in groups)} rows.\n")

        if dry_run:
            logger.info("Dry run — preview of merges:")
            for grp in groups[:30]:
                brand_name = grp[0].brand.name if grp[0].brand else "?"
                logger.info(f"  [{brand_name}]")
                for r in grp:
                    rcount = r.ratings.count()
                    logger.info(f"    - id={r.id:<5} ratings={rcount} {r.name[:80]}")
            if len(groups) > 30:
                logger.info(f"  ... and {len(groups) - 30} more groups")
            return

        merged = deleted = skipped_conflict = 0
        for grp in groups:
            # Pick survivor: most ratings, then oldest
            grp_with_count = [(s, s.ratings.count()) for s in grp]
            grp_with_count.sort(key=lambda x: (-x[1], x[0].created_at))
            survivor, _ = grp_with_count[0]
            losers = [r for r, _ in grp_with_count[1:]]

            existing_source_ids = {rt.source_id for rt in survivor.ratings.all()}

            for loser in losers:
                for rating in list(loser.ratings.all()):
                    if rating.source_id in existing_source_ids:
                        # Same source already on survivor — pick the NEWER rating's data and
                        # drop the older one. This handles cases like Trustified retesting a
                        # product in a new year (e.g., nutrabay-pro-fish-oil-omega-main from
                        # 2023 vs nutrabay-pro-fish-oil-omega-3 from 2024).
                        existing = next(rt for rt in survivor.ratings.all() if rt.source_id == rating.source_id)
                        rating_when = rating.tested_at or rating.created_at.date() if rating.created_at else None
                        existing_when = existing.tested_at or existing.created_at.date() if existing.created_at else None
                        if rating_when and existing_when and rating_when > existing_when:
                            # Loser's rating is newer — copy its data onto the existing rating
                            for field in ("score", "max_score", "verdict", "summary", "report_url",
                                          "tested_at", "batch_no", "manufacturing_date",
                                          "expiration_date", "tested_by"):
                                setattr(existing, field, getattr(rating, field))
                            # Preserve a buy_url if the newer one is missing it
                            if rating.buy_url:
                                existing.buy_url = rating.buy_url
                        else:
                            # Existing is newer (or same) — only fill in buy_url if missing
                            if rating.buy_url and not existing.buy_url:
                                existing.buy_url = rating.buy_url
                        skipped_conflict += 1
                        db.session.delete(rating)
                    else:
                        rating.supplement_id = survivor.id
                        existing_source_ids.add(rating.source_id)

                if not survivor.image_path and loser.image_path:
                    survivor.image_path = loser.image_path
                    survivor.image_source = loser.image_source
                if not survivor.image_url and loser.image_url:
                    survivor.image_url = loser.image_url
                if not survivor.dsld_id and loser.dsld_id:
                    survivor.dsld_id = loser.dsld_id

                # Use the most descriptive name (longer often = more detail)
                if loser.name and len(loser.name) > len(survivor.name or ''):
                    survivor.name = loser.name

                # Record the loser's slug as an alias so old URLs still resolve
                # (handles the case of `/supplement/nutrabay-pro-fish-oil-omega-3`
                # being merged into `/supplement/nutrabay-pro-fish-oil-omega-main`).
                if loser.slug and loser.slug != survivor.slug:
                    existing_alias = SupplementAlias.query.filter_by(slug=loser.slug).first()
                    if not existing_alias:
                        db.session.add(SupplementAlias(slug=loser.slug, supplement_id=survivor.id))
                    else:
                        existing_alias.supplement_id = survivor.id

                db.session.delete(loser)
                deleted += 1

            merged += 1

        db.session.commit()
        logger.info(f"\n✓ Merged {merged} groups → {deleted} duplicate rows removed.")
        logger.info(f"  {skipped_conflict} same-source ratings dropped during merge.")
        logger.info(f"\nRecount:")
        logger.info(f"  supplements: {Supplement.query.count()}")
        logger.info(f"  ratings:     {Rating.query.count()}")

        from sqlalchemy import func
        multi = (
            db.session.query(Supplement, func.count(Rating.id).label("c"))
            .join(Rating, Rating.supplement_id == Supplement.id)
            .group_by(Supplement.id)
            .having(func.count(Rating.id) > 1)
            .order_by(func.count(Rating.id).desc())
            .limit(15)
            .all()
        )
        logger.info(f"\nMulti-source products after merge ({len(multi)} shown):")
        for s, c in multi:
            sources = ", ".join(sorted({r.source.name for r in s.ratings.all() if r.source}))
            logger.info(f"  ×{c}  {s.name[:60]:<60}  [{sources}]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    merge(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
