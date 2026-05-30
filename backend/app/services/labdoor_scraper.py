"""Scraper for labdoor.com /review product pages and /rankings category pages.

Strategy:
- Discover all product review URLs from labdoor.com/public/product_reviews.xml
- For each product, parse the server-rendered HTML using BeautifulSoup to extract:
  - Product name + brand (from OG title; brand from category breadcrumbs)
  - Overall quality score (0-100) — from <span class="labdoorScoreValue">
  - Grade letter (A/B/C/D/F) — derived from the fcScore<letter> class on the score element
  - Category — first /rankings/<slug> link
  - Status flags: Certified, Expired, Upcoming
  - Main product image — from og:image (cdn.labdoor.io)
  - Buy URL — /review/<slug>/buy/<id> redirect (Amazon affiliate; Labdoor preserves this even
    while keeping their commission disclosure transparent)

Respects:
- robots.txt (Labdoor allows / and disallows only auth/account paths)
- 1-second rate limit between requests
- Cache-friendly (idempotent re-fetches via image-hash filenames)
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "HealthMatrixBot/0.1 (+https://healthmatrix.example "
    "supplement comparison aggregator; respect robots.txt; contact: info@nomosinsights.com)"
)
BASE_URL = "https://labdoor.com"
SITEMAP_URL = "https://labdoor.com/public/product_reviews.xml"
RATE_LIMIT = 1.0
TIMEOUT = 20

# Map Labdoor's category slugs → our internal category slugs.
# Labdoor categories that don't map to a supplement category (energy drinks, milk chocolate,
# coca-cola, vitamin water, etc.) are skipped.
LABDOOR_CATEGORY_MAP: dict[str, str] = {
    "fish-oil": "omega-fish-oil",
    "krill-oil": "omega-fish-oil",
    "vegan-omega-3": "omega-fish-oil",
    "hemp-oil": "omega-fish-oil",
    "cbd-oil": "omega-fish-oil",
    "protein": "protein",
    "protein-bars": "protein",
    "meal-replacements": "protein",
    "creatine": "sports-performance",
    "bcaa": "sports-performance",
    "glutamine": "sports-performance",
    "pre-workout": "sports-performance",
    "energy": "sports-performance",
    "electrolytes": "sports-performance",
    "multivitamins": "vitamins",
    "prenatal-vitamins": "vitamins",
    "hair-vitamins": "vitamins",
    "vitamin-c": "vitamins",
    "vitamin-d": "vitamins",
    "vitamin-b12": "vitamins",
    "vitamin-b6": "vitamins",
    "b-complex": "vitamins",
    "biotin": "vitamins",
    "magnesium": "minerals",
    "calcium": "minerals",
    "zinc": "minerals",
    "probiotics": "probiotics",
    "probiotics-for-children": "probiotics",
    "melatonin": "sleep-stress",
    "ginseng": "herbal",
    "green-tea": "herbal",
    "garcinia-cambogia": "herbal",
    "glucosamine": "herbal",
    "bacopa-monnieri": "herbal",
    "quercetin": "herbal",
    "resveratrol-trans-resveratrol": "herbal",
    "coq10": "herbal",
    "nootropics": "herbal",
    "nmn-nicotinamide-mononucleotide": "herbal",
    "pqq-pyrroloquinoline-quinone-disodium-salt": "herbal",
    "pine-needle-extract": "herbal",
    # Foods/drinks Labdoor reviews — previously skipped, now routed into the
    # food categories the catalog gained when it expanded beyond supplements.
    "milk-chocolate": "chocolate-frozen",
    "vitamin-water-energy": "beverages",
    "coca-cola": "beverages",
    "energy-drinks": "beverages",
}

# No Labdoor categories are skipped now that the catalog includes food + drinks.
# Kept as an empty set so callers don't need to special-case None.
SKIP_CATEGORIES: set[str] = set()


@dataclass
class LabdoorProduct:
    url: str
    slug: str
    title: Optional[str] = None
    brand: Optional[str] = None
    product_name: Optional[str] = None
    image_url: Optional[str] = None
    score: Optional[float] = None             # 0-100
    grade: Optional[str] = None               # A / B / C / D / F
    category_slug: Optional[str] = None       # Labdoor's category slug
    category_name: Optional[str] = None
    is_certified: bool = False
    is_expired: bool = False
    is_upcoming: bool = False
    buy_url: Optional[str] = None             # full https://labdoor.com/review/<slug>/buy/<id>
    notes: list[str] = field(default_factory=list)


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

def fetch_product_urls_from_sitemap() -> list[str]:
    """All review URLs from the sitemap. WARNING: ~50% are stale 404s."""
    parsed = urlparse(SITEMAP_URL)
    _rate.wait(parsed.netloc)
    r = _session().get(SITEMAP_URL, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return [loc.get_text(strip=True) for loc in soup.find_all("loc") if "/review/" in loc.get_text()]


def fetch_ranking_categories() -> list[str]:
    """Return all category slugs from labdoor.com/rankings."""
    _rate.wait("labdoor.com")
    r = _session().get(f"{BASE_URL}/rankings", timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    seen: set[str] = set()
    cats = []
    for a in soup.find_all("a", href=True):
        m = re.match(r"^/rankings/([a-z0-9-]+)/?$", a["href"])
        if m:
            slug = m.group(1)
            if slug in {"upcoming", "vote"} or slug in seen:
                continue
            seen.add(slug)
            cats.append(slug)
    return cats


def fetch_products_in_category(category_slug: str) -> list[str]:
    """Return product review URLs visible on a single rankings page (live, not stale)."""
    url = f"{BASE_URL}/rankings/{category_slug}"
    _rate.wait("labdoor.com")
    try:
        r = _session().get(url, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"  fetch_products_in_category({category_slug}) failed: {e}")
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"^/review/([a-z0-9-]+)/?$", href)
        if m:
            slug = m.group(1)
            if slug not in seen:
                seen.add(slug)
                urls.append(urljoin(BASE_URL, href))
    return urls


def fetch_product_urls() -> list[str]:
    """Discover all currently-listed product review URLs by traversing every category ranking page."""
    cats = fetch_ranking_categories()
    logger.info(f"Discovered {len(cats)} ranking categories.")
    all_urls: list[str] = []
    seen: set[str] = set()
    for i, cat in enumerate(cats, 1):
        urls = fetch_products_in_category(cat)
        new_urls = [u for u in urls if u not in seen]
        all_urls.extend(new_urls)
        seen.update(new_urls)
        logger.info(f"  [{i}/{len(cats)}] {cat}: {len(urls)} products ({len(new_urls)} new)")
    return all_urls


# ---------- Product page parsing ----------

def _meta(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    return tag.get("content") if tag else None


def _grade_from_score(score: float) -> str:
    """Labdoor's standard grade thresholds (A 90+, B 80-89, C 70-79, D 60-69, F <60)."""
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 70: return "C"
    if score >= 60: return "D"
    return "F"


def _parse_score_grade(soup: BeautifulSoup) -> tuple[Optional[float], Optional[str]]:
    el = soup.find(class_="labdoorScoreValue")
    if not el:
        return None, None
    score_text = el.get_text(" ", strip=True)
    score = None
    try:
        if score_text.replace(".", "").isdigit():
            score = float(score_text)
    except ValueError:
        pass

    # Prefer the explicit class signal (Labdoor renders fcScoreA / fcScoreB / etc.)
    grade = None
    for c in el.get("class", []):
        m = re.match(r"fcScore([A-FX])$", c)
        if m:
            grade = m.group(1)
            break

    # Fallback: derive from score
    if not grade and score is not None:
        grade = _grade_from_score(score)

    return score, grade


def _parse_category(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    """The category breadcrumb on a Labdoor review page is the all-caps
    `<a>FISH OIL RANKING</a>` link. Header navigation also has /rankings/ links
    which are NOT this product's category, so we filter for the all-caps pattern."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"^/rankings/([a-z0-9-]+)/?$", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in ("upcoming",):
            continue
        text = a.get_text(" ", strip=True)
        # All-caps pattern: any upper case, no lower case, ends with "RANKING"
        if text and " RANKING" in text and not any(c.islower() for c in text):
            return slug, text.replace("RANKING", "").strip().title()
    return None, None


def _parse_buy_url(soup: BeautifulSoup, slug: str) -> Optional[str]:
    pattern = re.compile(rf"^/review/{re.escape(slug)}/buy/\d+/?$")
    for a in soup.find_all("a", href=True):
        if pattern.match(a["href"]):
            return urljoin(BASE_URL, a["href"])
    # Fallback: regex over raw HTML in case the link is rendered without an <a>
    return None


def _parse_amazon_buy_anchor(soup: BeautifulSoup, slug: str) -> Optional[str]:
    """Find the labdoor buy redirect that points specifically to Amazon.

    A Labdoor review page can list multiple sellers (iHerb, Amazon, …), each as
    a `/review/<slug>/buy/<N>` anchor. We pick the one whose visible text says
    "Amazon" so we don't accidentally resolve to iHerb."""
    pattern = re.compile(rf"^/review/{re.escape(slug)}/buy/\d+/?$")
    fallback = None
    for a in soup.find_all("a", href=True):
        if not pattern.match(a["href"]):
            continue
        text = a.get_text(" ", strip=True).lower()
        if "amazon" in text:
            return urljoin(BASE_URL, a["href"])
        # Remember the first buy/* anchor so single-seller pages still work even
        # if the visible text isn't "Amazon" (some Labdoor templates render a
        # generic "Buy Now" button when only one retailer is configured).
        if fallback is None:
            fallback = urljoin(BASE_URL, a["href"])
    return fallback


def resolve_amazon_buy_url(review_url: str) -> Optional[str]:
    """Fetch a Labdoor review page, locate its Amazon buy redirect, and follow
    that redirect to return the final amazon.com URL (with affiliate params).

    Returns None when the page has no Amazon retailer link, when the page can't
    be fetched, or when the redirect lands somewhere other than Amazon."""
    parsed = urlparse(review_url)
    _rate.wait(parsed.netloc)
    try:
        r = _session().get(review_url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"  resolve_amazon_buy_url fetch failed: {review_url} → {e}")
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    slug = review_url.rstrip("/").split("/")[-1]
    buy_redirect = _parse_amazon_buy_anchor(soup, slug)
    if not buy_redirect:
        return None
    _rate.wait(parsed.netloc)
    try:
        rr = _session().get(buy_redirect, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        logger.warning(f"  resolve_amazon_buy_url redirect failed: {buy_redirect} → {e}")
        return None
    final = str(rr.url)
    if "amazon." not in (urlparse(final).hostname or ""):
        # Probably an iHerb / other-seller redirect — caller asked for Amazon.
        return None
    return final


def review_url_from_buy_url(labdoor_buy_url: str) -> Optional[str]:
    """Strip the trailing `/buy/<id>` segment off a stored Labdoor buy_url so we
    can re-fetch the review page. e.g.
      https://labdoor.com/review/<slug>/buy/12579 -> https://labdoor.com/review/<slug>
    Returns None if the URL doesn't match the expected shape."""
    m = re.match(r"^(https://labdoor\.com/review/[^/]+)/buy/\d+/?$", labdoor_buy_url or "")
    return m.group(1) if m else None


_HTML_ENTITIES = {
    "&amp;": "&", "&#x27;": "'", "&quot;": '"',
    "&lt;": "<", "&gt;": ">", "&nbsp;": " ",
}


def _decode_entities(s: str) -> str:
    for k, v in _HTML_ENTITIES.items():
        s = s.replace(k, v)
    return s


def _split_brand_product(title: str) -> tuple[Optional[str], Optional[str]]:
    """OG title is 'Brand Product Name - Labdoor'. Trim ' Review' suffix and split brand/product."""
    if not title:
        return None, None
    title = _decode_entities(title)
    title = re.sub(r"\s+-\s+Labdoor.*$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s+Review\s*$", "", title, flags=re.IGNORECASE).strip()
    if not title:
        return None, None
    # Heuristic: brand is the first word(s) up to a "size" / dose marker. Without a definitive
    # separator, we treat the first 1-2 words as the brand. Common brand patterns:
    #   "Viva Naturals Triple Strength..."  → brand="Viva Naturals"
    #   "NOW Foods Vitamin D-3"             → brand="NOW Foods"
    #   "Optimum Nutrition Gold Standard"   → brand="Optimum Nutrition"
    parts = title.split()
    if len(parts) <= 2:
        return title, title
    # Try to detect 2-word brand if first word is < 5 chars OR title-cased pair
    if len(parts) >= 3 and parts[1][:1].isupper() and len(parts[0]) <= 8:
        return f"{parts[0]} {parts[1]}", " ".join(parts[2:])
    return parts[0], " ".join(parts[1:])


def parse_product(html: str, url: str) -> LabdoorProduct:
    soup = BeautifulSoup(html, "html.parser")
    slug = url.rstrip("/").split("/")[-1]
    p = LabdoorProduct(url=url, slug=slug)

    og_title = _meta(soup, "og:title")
    p.title = og_title
    p.brand, p.product_name = _split_brand_product(og_title or "")

    og_image = _meta(soup, "og:image")
    if og_image:
        p.image_url = og_image.strip().strip('"')  # Labdoor sometimes ships unquoted attrs

    p.score, p.grade = _parse_score_grade(soup)
    p.category_slug, p.category_name = _parse_category(soup)

    # Status flags (visible badges in the page)
    text = soup.get_text(" ", strip=True)
    p.is_certified = "Certified" in text and "labdoor" in text.lower()
    p.is_upcoming = "Upcoming" in text and (p.grade in ("X", None))
    p.is_expired = "Expired" in text and not p.is_upcoming

    p.buy_url = _parse_buy_url(soup, slug)

    return p


def fetch_product(url: str) -> Optional[LabdoorProduct]:
    parsed = urlparse(url)
    _rate.wait(parsed.netloc)
    try:
        r = _session().get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"  fetch failed: {url} → {e}")
        return None
    return parse_product(r.text, url)


def map_category(labdoor_slug: Optional[str]) -> Optional[str]:
    """Map Labdoor's category slug to our internal category slug. None = skip."""
    if not labdoor_slug:
        return None
    if labdoor_slug in SKIP_CATEGORIES:
        return None
    return LABDOOR_CATEGORY_MAP.get(labdoor_slug)
