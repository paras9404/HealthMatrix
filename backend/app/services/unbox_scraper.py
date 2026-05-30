"""Scraper for unboxhealth.in /explore/product/<slug>/<uuid> pages.

Strategy:
- Discover product URLs from the public products-list page (which mirrors the sitemap).
- For each product, parse JSON-LD blocks for Product + BreadcrumbList:
  - Product name, brand, image (cdn S3-hosted)
  - aggregateRating.ratingValue (0-10) — converted to 0-100 normalized score
  - reviewBody contains the letter grade ("Rated A+ ...") and sub-scores ("Label Accuracy Score: ...")
- Buy URL is an Amazon.in affiliate link (uhamz tag) embedded in the page DOM.

What we DON'T do:
- Bypass any auth — these are public review pages.
- Republish UnboxHealth's review text verbatim (we link out to the full review).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "HealthMatrixBot/0.1 (+https://healthmatrix.example "
    "supplement comparison aggregator; respect robots.txt; contact: info@nomosinsights.com)"
)
BASE_URL = "https://www.unboxhealth.in"
PRODUCTS_LIST_URL = f"{BASE_URL}/explore/products-list"
RATE_LIMIT = 1.0
TIMEOUT = 20


# Map UnboxHealth category slug → our internal category. None = skip (food/non-supplement).
UNBOX_CATEGORY_MAP: dict[str, str] = {
    # Vitamins
    "multivitamins": "vitamins",
    "biotin-supplements": "vitamins",
    "vitamin-a-supplements": "vitamins",
    "vitamin-b9-supplements": "vitamins",
    "vitamin-b12-supplements": "vitamins",
    "vitamin-c-supplements": "vitamins",
    "vitamin-d-supplements": "vitamins",
    "vitamin-e-supplements": "vitamins",
    "vitamin-k2-supplements": "vitamins",
    # Minerals
    "magnesium-supplements": "minerals",
    "zinc-supplements": "minerals",
    "iron-supplements": "minerals",
    "calcium-supplements": "minerals",
    # Protein
    "protein-powders": "protein",
    "plant-protein-powders": "protein",
    "protein-milkshakes": "protein",
    "collagen-supplements": "protein",
    # Omega
    "omega-3-supplements": "omega-fish-oil",
    "veg-omega-3-supplements": "omega-fish-oil",
    # Sports & Performance
    "creatine-supplements": "sports-performance",
    "electrolytes": "sports-performance",
    # Sleep & Stress
    "melatonin-supplements": "sleep-stress",
    "ashwagandha-supplements": "herbal",
    # Herbal
    "curcumin-supplements": "herbal",
    "moringa-supplements": "herbal",
    "shilajit-supplements": "herbal",
    "berberine-supplements": "herbal",
    "coq10-supplements": "herbal",
    "astaxanthin": "herbal",
    "sea-buckthorn-oil": "herbal",
    "apple-cider-vinegar": "herbal",
    # Probiotics / fiber
    "prebiotics-fiber": "probiotics",
    # Food categories — added when the catalog expanded beyond supplements.
    # Each maps to a new internal category whose row is created by
    # backend/expand_food_categories.py.
    "paneer": "dairy",
    "ghee": "dairy",
    "cooking-oils": "cooking-oils",
    "extra-virgin-olive-oil": "cooking-oils",
    "peanut-butters": "spreads",
    "honey": "spreads",
    "snack-bars": "snacks-bars",
    "chips-puffs": "snacks-bars",
    "cookies-biscuits": "snacks-bars",
    "dark-chocolates": "chocolate-frozen",
    "ice-cream": "chocolate-frozen",
    "breakfast-cereals": "cereals-bread",
    "bread": "cereals-bread",
    "instant-noodles": "ready-to-eat",
    "idli-dosa-batters": "ready-to-eat",
    "coffee-powder": "beverages",
}

# Categories we explicitly skip — meta listing pages, not real categories.
UNBOX_SKIP = {
    "the-great-indian-product-hunt-most-voted-products",
}


@dataclass
class UnboxProduct:
    url: str
    slug: str
    uuid: Optional[str] = None
    name: Optional[str] = None
    brand: Optional[str] = None
    image_url: Optional[str] = None
    score: Optional[float] = None        # 0-10 (UnboxHealth's native scale)
    grade: Optional[str] = None          # A+, A, B+, B, C, D, F
    is_previous: bool = False            # True if "Previously Rated" badge shown
    label_accuracy: Optional[float] = None
    non_toxicity: Optional[float] = None
    review_body: Optional[str] = None
    category_slug: Optional[str] = None
    category_name: Optional[str] = None
    buy_url: Optional[str] = None
    sku: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    @property
    def normalized_score(self) -> Optional[float]:
        """Convert 0-10 → 0-100 for our shared score scale."""
        if self.score is None:
            return None
        return self.score * 10.0


class _RateLimiter:
    def __init__(self, interval: float):
        self.interval = interval
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        elapsed = time.time() - self._last.get(host, 0)
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last[host] = time.time()


_rate = _RateLimiter(RATE_LIMIT)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


# ---------- Discovery ----------

def fetch_product_urls() -> list[str]:
    """Return all product URLs from the public products-list page (mirrors the sitemap)."""
    parsed = urlparse(PRODUCTS_LIST_URL)
    _rate.wait(parsed.netloc)
    r = _session().get(PRODUCTS_LIST_URL, timeout=TIMEOUT)
    r.raise_for_status()
    seen, out = set(), []
    for path in re.findall(r'/explore/product/[a-z0-9-]+/[a-f0-9-]+', r.text):
        if path not in seen:
            seen.add(path)
            out.append(f"{BASE_URL}{path}")
    return out


# ---------- Product page parsing ----------

_GRADE_PATTERN = re.compile(r"\b(?:Rated|Currently Rated|Previously Rated)\s*:?\s*([A-FX][+\-]?)\b", re.IGNORECASE)
_SUB_SCORE_PATTERN = re.compile(r"([A-Z][A-Za-z\- ]+)\s+Score:\s*([\d.]+)", re.IGNORECASE)


def _all_jsonld(soup: BeautifulSoup) -> list[dict]:
    """Flatten every JSON-LD block on the page into a list of dicts."""
    out: list[dict] = []
    for s in soup.find_all("script", type="application/ld+json"):
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def _decode_html_entities(text: str) -> str:
    return (text.replace("&amp;", "&").replace("&#x27;", "'")
                .replace("&quot;", '"').replace("&lt;", "<")
                .replace("&gt;", ">").replace("&nbsp;", " "))


def _parse_breadcrumb_category(blocks: list[dict]) -> tuple[Optional[str], Optional[str]]:
    """Find the BreadcrumbList JSON-LD and return (category_slug, category_name)."""
    for b in blocks:
        if b.get("@type") != "BreadcrumbList":
            continue
        items = b.get("itemListElement", []) or []
        # Position 3 is the product category (1=Explore, 2=All Categories, 3=Category, 4=Product)
        for item in items:
            if not isinstance(item, dict) or item.get("position") != 3:
                continue
            url = item.get("item") or ""
            name = item.get("name") or ""
            m = re.match(r".*/explore/category-list/([a-z0-9-]+)/", url)
            if m:
                return m.group(1), name
    return None, None


def _parse_buy_url(soup: BeautifulSoup) -> Optional[str]:
    """Find the Amazon.in affiliate link on the page (uhamz tag)."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "amazon.in" in href and ("uhamz" in href or "/dp/" in href):
            return href
    return None


def parse_product(html: str, url: str) -> UnboxProduct:
    soup = BeautifulSoup(html, "html.parser")

    parts = url.rstrip("/").split("/")
    uuid = parts[-1] if len(parts) >= 2 else None
    slug = parts[-2] if len(parts) >= 2 else url.rsplit("/", 1)[-1]
    p = UnboxProduct(url=url, slug=slug, uuid=uuid)

    blocks = _all_jsonld(soup)

    # Product block
    product_block = next((b for b in blocks if b.get("@type") == "Product"), None)
    if product_block:
        p.name = _decode_html_entities(product_block.get("name", "") or "").strip() or None
        brand_obj = product_block.get("brand")
        if isinstance(brand_obj, dict):
            p.brand = (brand_obj.get("name") or "").strip() or None
        elif isinstance(brand_obj, str):
            p.brand = brand_obj.strip() or None

        images = product_block.get("image") or []
        if isinstance(images, list) and images:
            p.image_url = images[0]
        elif isinstance(images, str):
            p.image_url = images

        p.sku = product_block.get("sku") or None

        agg = product_block.get("aggregateRating") or {}
        if isinstance(agg, dict):
            score = agg.get("ratingValue")
            if isinstance(score, (int, float)):
                p.score = float(score)

        # reviewBody often contains the letter grade + sub-scores ("Rated A+", "Label Accuracy: 9.92")
        review = product_block.get("review") or {}
        body = review.get("reviewBody") if isinstance(review, dict) else None
        if body:
            p.review_body = body
            grade_match = _GRADE_PATTERN.search(body)
            if grade_match:
                p.grade = grade_match.group(1).upper()
            for label, value in _SUB_SCORE_PATTERN.findall(body):
                key = label.strip().lower()
                try:
                    val = float(value)
                except ValueError:
                    continue
                if "label accuracy" in key:
                    p.label_accuracy = val
                elif "non-toxic" in key or "non toxic" in key:
                    p.non_toxicity = val

    # Fall back to whole-page text scan for the grade (handles "Previously Rated" header on some pages)
    if not p.grade:
        text = soup.get_text(" ", strip=True)
        m = _GRADE_PATTERN.search(text)
        if m:
            p.grade = m.group(1).upper()
        if "Previously Rated" in text:
            p.is_previous = True

    # Category from breadcrumbs JSON-LD
    p.category_slug, p.category_name = _parse_breadcrumb_category(blocks)

    # Buy URL
    p.buy_url = _parse_buy_url(soup)

    return p


def fetch_product(url: str) -> Optional[UnboxProduct]:
    parsed = urlparse(url)
    _rate.wait(parsed.netloc)
    try:
        r = _session().get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"  fetch failed: {url} → {e}")
        return None
    return parse_product(r.text, url)


def map_category(unbox_slug: Optional[str]) -> Optional[str]:
    if not unbox_slug or unbox_slug in UNBOX_SKIP:
        return None
    return UNBOX_CATEGORY_MAP.get(unbox_slug)
