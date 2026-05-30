"""Data + image fetching pipeline.

Sources (legitimate, public, well-attributed):
1. **DSLD** — Dietary Supplement Label Database, hosted by NIH/NLM. Public free API.
   https://dsld.od.nih.gov/api-guide
   Returns real product labels, ingredients, brand info, and label images.

2. **Open Food Facts** — open database with CC license.
   https://world.openfoodfacts.org/data

3. **Direct manufacturer URLs** — public product images from brand sites
   (we save locally so we don't hotlink, and respect robots.txt).

What we DON'T do:
- Scrape Labdoor / ConsumerLab scores (proprietary, ToS-protected).
- Bypass paywalls.
- Republish copyrighted reports.

All HTTP requests:
- Identify themselves with a descriptive User-Agent + contact URL.
- Are rate-limited.
- Cache results so we never re-hit the same URL twice.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Where downloaded images live, relative to backend/
STATIC_ROOT = Path(__file__).resolve().parent.parent.parent / "static"
IMAGES_DIR = STATIC_ROOT / "images" / "supplements"

USER_AGENT = (
    "HealthMatrixBot/0.1 (+https://healthmatrix.example "
    "supplement comparison aggregator; respect robots.txt; contact: info@nomosinsights.com)"
)

DSLD_BASE = "https://api.ods.od.nih.gov/dsld/v9"
OFF_BASE = "https://world.openfoodfacts.org"

REQUEST_TIMEOUT = 15
RATE_LIMIT_SECONDS = 0.5  # min wait between calls to the same host


@dataclass
class FetchResult:
    image_path: Optional[str] = None
    image_source: Optional[str] = None
    dsld_id: Optional[str] = None
    upc: Optional[str] = None
    notes: list[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last_called: dict[str, float] = {}

    def wait(self, host: str) -> None:
        elapsed = time.time() - self._last_called.get(host, 0)
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_called[host] = time.time()


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,image/*,*/*"})
    return s


_rate = RateLimiter(RATE_LIMIT_SECONDS)


# ---------- Image download ----------

def download_image(url: str, slug: str, source_label: str = "manufacturer") -> Optional[tuple[str, str]]:
    """Download an image to backend/static/images/supplements/<slug>.<ext>.

    Returns (filename, source_label) on success, None on failure.
    Idempotent: skips if file already exists for this slug+url combo.
    """
    if not url:
        return None

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return None

    # Hash the URL so re-fetching the same URL is a no-op
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    ext = _guess_extension(url)
    filename = f"{slug}-{url_hash}.{ext}"
    target = IMAGES_DIR / filename

    if target.exists() and target.stat().st_size > 1024:
        logger.info(f"  [cache hit] {filename}")
        return filename, source_label

    _rate.wait(parsed.netloc)

    # When the URL has a clear image extension, trust it even if the server returns
    # a generic Content-Type (S3 sometimes serves .webp as binary/octet-stream).
    url_has_image_ext = bool(re.search(r"\.(jpg|jpeg|png|webp|gif)(\?|$)", url, re.IGNORECASE))

    try:
        with _session() as s:
            r = s.get(url, timeout=REQUEST_TIMEOUT, stream=True, allow_redirects=True)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "").lower()
            looks_image = (ct.startswith("image/")
                           or ct in ("application/octet-stream", "binary/octet-stream", "")
                           or url_has_image_ext)
            if not looks_image:
                logger.warning(f"  [skip] not image: {ct} from {url}")
                return None

            # Detect extension from content-type if URL was ambiguous
            if ext == "jpg" and "png" in ct:
                filename = filename.replace(".jpg", ".png")
                target = IMAGES_DIR / filename
            elif ext == "jpg" and "webp" in ct:
                filename = filename.replace(".jpg", ".webp")
                target = IMAGES_DIR / filename

            with open(target, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            size = target.stat().st_size
            if size < 1024:
                logger.warning(f"  [skip] image too small ({size}b) from {url}")
                target.unlink(missing_ok=True)
                return None

            logger.info(f"  ✓ downloaded {filename} ({size//1024}KB) from {parsed.netloc}")
            return filename, source_label
    except requests.RequestException as e:
        logger.warning(f"  [fail] {url} → {e}")
        return None


def _guess_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
        if path.endswith(f".{ext}"):
            return "jpeg" if ext == "jpg" else ext
    return "jpg"  # safe default


# ---------- DSLD (NIH Dietary Supplement Label Database) ----------

def dsld_search(query: str, limit: int = 5) -> list[dict]:
    """Search NIH DSLD for supplement labels matching the query.

    Returns list of hit dicts with keys: id, fullName, brandName, productType, etc.
    """
    _rate.wait("api.ods.od.nih.gov")
    try:
        with _session() as s:
            r = s.get(
                f"{DSLD_BASE}/search-filter",
                params={"q": query, "size": limit, "from": 0},
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            # DSLD v9 returns {"hits": [{"_id": ..., "_source": {...}}, ...]}
            hits = data.get("hits", []) if isinstance(data, dict) else []
            results = []
            for h in hits:
                if not isinstance(h, dict):
                    continue
                src = h.get("_source", {}) or {}
                results.append({**src, "id": h.get("_id")})
            return results
    except requests.RequestException as e:
        logger.warning(f"DSLD search failed for '{query}': {e}")
        return []
    except (ValueError, TypeError, KeyError) as e:
        logger.warning(f"DSLD response parse error for '{query}': {e}")
        return []


def dsld_label(dsld_id: str) -> Optional[dict]:
    """Fetch full label data for a DSLD product ID."""
    _rate.wait("api.ods.od.nih.gov")
    try:
        with _session() as s:
            r = s.get(f"{DSLD_BASE}/label/{dsld_id}", timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
    except requests.RequestException as e:
        logger.warning(f"DSLD label fetch failed for {dsld_id}: {e}")
        return None


# ---------- Open Food Facts (fallback for barcoded products) ----------

def off_lookup_by_upc(upc: str) -> Optional[dict]:
    """Look up a product by UPC/barcode from Open Food Facts (CC-licensed)."""
    _rate.wait("world.openfoodfacts.org")
    try:
        with _session() as s:
            r = s.get(f"{OFF_BASE}/api/v2/product/{upc}.json", timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == 1:
                return data.get("product")
    except requests.RequestException as e:
        logger.warning(f"OFF lookup failed for {upc}: {e}")
    return None


# ---------- SVG fallback generator ----------

# Category icon → brand-tinted color palette (matches frontend design tokens)
CATEGORY_PALETTE = {
    "vitamin": ("#F59E0B", "#FEF3C7"),       # amber
    "mineral": ("#0EA5E9", "#E0F2FE"),       # sky
    "protein": ("#8B5CF6", "#EDE9FE"),       # violet
    "fish": ("#06B6D4", "#CFFAFE"),          # cyan
    "probiotic": ("#10B981", "#D1FAE5"),     # emerald
    "leaf": ("#22C55E", "#DCFCE7"),          # green
    "dumbbell": ("#EF4444", "#FEE2E2"),      # red
    "moon": ("#6366F1", "#E0E7FF"),          # indigo
}

# Category icon → simple SVG iconography
CATEGORY_GLYPH = {
    "vitamin":   '<ellipse cx="200" cy="200" rx="60" ry="100" fill="#fff" opacity="0.95"/><rect x="170" y="140" width="60" height="60" fill="rgba(0,0,0,0.06)"/>',
    "mineral":   '<polygon points="200,100 260,180 230,300 170,300 140,180" fill="#fff" opacity="0.95"/>',
    "protein":   '<rect x="140" y="120" width="120" height="160" rx="12" fill="#fff" opacity="0.95"/><rect x="160" y="100" width="80" height="30" rx="6" fill="#fff" opacity="0.95"/>',
    "fish":      '<path d="M120,200 Q200,120 280,200 Q200,280 120,200 Z" fill="#fff" opacity="0.95"/><circle cx="240" cy="190" r="6" fill="rgba(0,0,0,0.4)"/>',
    "probiotic": '<circle cx="200" cy="200" r="80" fill="#fff" opacity="0.95"/><circle cx="180" cy="190" r="10" fill="rgba(0,0,0,0.15)"/><circle cx="220" cy="210" r="8" fill="rgba(0,0,0,0.15)"/><circle cx="200" cy="220" r="6" fill="rgba(0,0,0,0.15)"/>',
    "leaf":      '<path d="M120,280 Q120,160 200,120 Q280,160 280,280 Q200,260 120,280 Z" fill="#fff" opacity="0.95"/>',
    "dumbbell":  '<rect x="100" y="180" width="40" height="40" fill="#fff" opacity="0.95"/><rect x="260" y="180" width="40" height="40" fill="#fff" opacity="0.95"/><rect x="140" y="195" width="120" height="10" fill="#fff" opacity="0.95"/>',
    "moon":      '<path d="M260,200 A80,80 0 1,1 200,120 A60,60 0 0,0 260,200 Z" fill="#fff" opacity="0.95"/>',
}


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def _wrap_text(text: str, max_chars: int = 22) -> list[str]:
    words, lines, current = text.split(), [], ""
    for w in words:
        if len(current) + len(w) + 1 <= max_chars:
            current = (current + " " + w).strip()
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines[:3]


def generate_svg_fallback(slug: str, brand: str, name: str, category_icon: str = "vitamin") -> str:
    """Create a branded SVG product card and save to disk. Returns the filename."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    accent, soft = CATEGORY_PALETTE.get(category_icon, ("#0F766E", "#CCFBF1"))
    glyph = CATEGORY_GLYPH.get(category_icon, "")

    name_lines = _wrap_text(name, 22)
    name_text = "".join(
        f'<tspan x="200" dy="{0 if i == 0 else 28}">{_xml_escape(line)}</tspan>'
        for i, line in enumerate(name_lines)
    )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" role="img" aria-label="{_xml_escape(brand)} {_xml_escape(name)}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{soft}"/>
      <stop offset="100%" stop-color="#FFFFFF"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.85"/>
      <stop offset="100%" stop-color="{accent}" stop-opacity="0.55"/>
    </linearGradient>
  </defs>
  <rect width="400" height="400" fill="url(#bg)"/>
  <circle cx="200" cy="200" r="130" fill="url(#accent)" opacity="0.12"/>
  <g transform="translate(0,-10)">{glyph}</g>
  <rect x="0" y="320" width="400" height="80" fill="rgba(15,23,42,0.92)"/>
  <text x="200" y="346" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="13" font-weight="700" letter-spacing="0.12em" fill="{accent}" text-transform="uppercase">{_xml_escape(brand.upper())}</text>
  <text x="200" y="372" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="16" font-weight="600" fill="#fff">{name_text}</text>
</svg>'''

    filename = f"{slug}.svg"
    target = IMAGES_DIR / filename
    target.write_text(svg, encoding="utf-8")
    logger.info(f"  ✓ generated SVG fallback {filename} ({target.stat().st_size} bytes)")
    return filename
