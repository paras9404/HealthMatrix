"""Fetch additional product images (clean main + ingredients/back panels) from Bing image search.

For each supplement:
1. Search Bing Images for "<brand> <name>" → main product images
2. Search Bing Images for "<brand> <name> ingredients" → ingredient panel
3. Search Bing Images for "<brand> <name> nutrition facts" → nutrition panel
4. Download top-N candidate URLs that look like product photos (not stock photos / logos)
5. Save to backend/static/images/supplements/ and insert into supplement_images table

Run with:
    python fetch_product_images.py --limit 5                # test on 5
    python fetch_product_images.py --source trustified       # only Trustified-watermarked
    python fetch_product_images.py --ids 405,162             # specific products
    python fetch_product_images.py                           # all 603
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Supplement, SupplementImage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static" / "images" / "supplements"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

REQUEST_TIMEOUT = 12
RATE_LIMIT_SEC = 1.0       # between Bing requests
DOWNLOAD_DELAY_SEC = 0.4   # between image downloads

# Hosts we trust (cleaner images, no watermarks)
PREFERRED_HOSTS = (
    "m.media-amazon.com", "images-na.ssl-images-amazon.com",
    "cdn.shopify.com", "shopify.com",
    "i5.walmartimages.com", "i.ebayimg.com",
    "rukminim", "rukminim1.flixcart.com", "rukminim2.flixcart.com",
    "5.imimg.com", "encrypted-tbn0.gstatic.com",
    "www.bigbasket.com", "media.istockphoto.com",
    "cdn-yotpoimages.com",
    "images.heb.com", "cdn.cdnparenting.com",
    "media-amazon.com", "ssl-images-amazon.com",
)
# Hosts to avoid (watermarked test/review sites)
BLOCKED_HOST_KEYWORDS = (
    "trustified.in", "labdoor.com",  # watermarked sources
    "youtube.", "ytimg.com",          # video thumbnails
    "facebook.", "fbcdn",
    "twitter.", "twimg.",
    "wikipedia.", "wikimedia.",
    "linkedin.",
)


def looks_blocked(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(b in host for b in BLOCKED_HOST_KEYWORDS)


def host_priority(url: str) -> int:
    """Lower = better priority for downloading."""
    host = urlparse(url).netloc.lower()
    for i, h in enumerate(PREFERRED_HOSTS):
        if h in host:
            return i
    return 100


def bing_image_search(query: str, max_results: int = 12) -> list[str]:
    """Return ordered list of image URLs from a Bing image search."""
    url = f"https://www.bing.com/images/search?q={quote_plus(query)}&form=HDRSC2&first=1"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"  bing search failed: {e}")
        return []

    matches = re.findall(
        r'murl&quot;:&quot;(https?://[^&]+?\.(?:jpg|jpeg|png|webp))',
        r.text,
        flags=re.IGNORECASE,
    )
    seen: set[str] = set()
    cleaned: list[str] = []
    for m in matches:
        u = m.replace("\\u002f", "/")
        if u in seen or looks_blocked(u):
            continue
        seen.add(u)
        cleaned.append(u)
        if len(cleaned) >= max_results:
            break
    cleaned.sort(key=host_priority)
    return cleaned


MIN_IMAGE_SIZE_BYTES = 25_000   # ~25KB — anything smaller is a thumbnail
MAX_IMAGE_SIZE_BYTES = 5_000_000  # 5MB cap


def _content_hash(path: Path) -> str:
    """First-MB MD5 — fast dedupe by content."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read(1024 * 1024))
    return h.hexdigest()


def download(url: str, slug: str, suffix: str, seen_hashes: set[str]) -> Optional[tuple[str, int]]:
    """Download image to static/. Returns (filename, size_bytes) or None.

    seen_hashes is mutated: content-hash of accepted images is added so callers
    can dedupe across multiple candidate URLs returning the same image bytes.
    """
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return None
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    ext = "jpg"
    for e in ("jpeg", "jpg", "png", "webp"):
        if parsed.path.lower().endswith("." + e):
            ext = "jpeg" if e == "jpg" else e
            break
    fname = f"{slug}-{suffix}-{h}.{ext}"
    target = STATIC_DIR / fname

    if target.exists() and target.stat().st_size >= MIN_IMAGE_SIZE_BYTES:
        chash = _content_hash(target)
        if chash in seen_hashes:
            return None
        seen_hashes.add(chash)
        return fname, target.stat().st_size

    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "").lower()
        if not (ct.startswith("image/") or ct in ("application/octet-stream", "binary/octet-stream")):
            return None
        size = 0
        with open(target, "wb") as f:
            for chunk in r.iter_content(chunk_size=16384):
                f.write(chunk)
                size += len(chunk)
                if size > MAX_IMAGE_SIZE_BYTES:
                    target.unlink(missing_ok=True)
                    return None
        if size < MIN_IMAGE_SIZE_BYTES:
            target.unlink(missing_ok=True)
            return None
        chash = _content_hash(target)
        if chash in seen_hashes:
            target.unlink(missing_ok=True)
            return None
        seen_hashes.add(chash)
        return fname, size
    except requests.RequestException:
        return None


def already_have_url(supp: Supplement, image_path: str) -> bool:
    return any(img.image_path == image_path for img in supp.images)


def add_image(supp: Supplement, image_path: str, image_type: str, order: int, source_url: str) -> None:
    img = SupplementImage(
        supplement_id=supp.id,
        image_path=image_path,
        image_url=source_url,
        image_source="bing-search",
        image_type=image_type,
        display_order=order,
        alt_text=f"{supp.name} ({image_type})",
    )
    db.session.add(img)


def _existing_content_hashes(supp: Supplement) -> set[str]:
    """Hash of the on-disk content of every image already attached to this supplement,
    so we don't re-download the same bytes a second time across image types."""
    hashes: set[str] = set()
    for img in supp.images:
        if img.image_path:
            p = STATIC_DIR / img.image_path
            if p.exists() and p.stat().st_size >= 4096:
                try:
                    hashes.add(_content_hash(p))
                except OSError:
                    pass
    return hashes


def fetch_for_supplement(supp: Supplement, max_per_type: int = 2) -> dict:
    """Fetch main + ingredients + nutrition images for one supplement.

    Existing images are preserved at their current display_order; new images
    append to the end. Cross-type and cross-product dedupe by content hash.
    """
    brand_name = supp.brand.name if supp.brand else ""
    prod_name = supp.name
    base_query = f"{brand_name} {prod_name}".strip()

    stats = {"main": 0, "ingredients": 0, "nutrition_facts": 0, "skipped": 0}

    next_order = max([img.display_order for img in supp.images], default=-1) + 1
    seen_hashes = _existing_content_hashes(supp)

    queries = [
        ("main", f"{base_query} package product"),
        ("ingredients", f"{base_query} ingredients label back"),
        ("nutrition_facts", f"{base_query} nutrition facts panel"),
    ]

    for image_type, q in queries:
        time.sleep(RATE_LIMIT_SEC)
        urls = bing_image_search(q, max_results=12)
        if not urls:
            continue

        added = 0
        for u in urls:
            if added >= max_per_type:
                break
            time.sleep(DOWNLOAD_DELAY_SEC)
            result = download(u, supp.slug, image_type, seen_hashes)
            if not result:
                stats["skipped"] += 1
                continue
            fname, size = result
            if already_have_url(supp, fname):
                continue
            add_image(supp, fname, image_type, next_order, u)
            next_order += 1
            added += 1
            stats[image_type] += 1
            logger.info(f"    + {image_type:<16} {fname} ({size//1024}KB)")

    return stats


def get_targets(args) -> list[Supplement]:
    q = Supplement.query
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
        q = q.filter(Supplement.id.in_(ids))
    elif args.source:
        q = q.filter(Supplement.image_source == args.source)
    elif args.missing_extra:
        # Only supplements with just 1 image (only the legacy main)
        from sqlalchemy import func
        q = q.outerjoin(SupplementImage).group_by(Supplement.id).having(
            func.count(SupplementImage.id) <= 1
        )
    q = q.order_by(Supplement.id)
    if args.limit:
        q = q.limit(args.limit)
    return q.all()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source", help="Only fetch for products with this image_source (e.g., 'trustified')")
    parser.add_argument("--ids", help="Comma-separated supplement IDs")
    parser.add_argument("--missing-extra", action="store_true",
                        help="Only fetch for supplements that only have 1 image so far")
    parser.add_argument("--max-per-type", type=int, default=2,
                        help="Max images per image_type (main/ingredients/nutrition)")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        supps = get_targets(args)
        logger.info(f"Processing {len(supps)} supplements")
        totals = {"main": 0, "ingredients": 0, "nutrition_facts": 0, "skipped": 0}
        for i, supp in enumerate(supps, 1):
            logger.info(f"[{i}/{len(supps)}] #{supp.id} {supp.name[:60]}")
            try:
                stats = fetch_for_supplement(supp, max_per_type=args.max_per_type)
                for k, v in stats.items():
                    totals[k] = totals.get(k, 0) + v
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"  [error] {e}")

        logger.info("=" * 60)
        logger.info(f"Done. Totals: {totals}")


if __name__ == "__main__":
    main()
