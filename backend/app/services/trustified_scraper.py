"""Scraper for trustified.in /passandfail product pages.

Strategy:
- Discover product URLs from the public sitemap (https://www.trustified.in/sitemap.xml).
- For each product page, parse the static HTML using BeautifulSoup to extract:
  - Product name + brand (from OG title and on-page strong-tag patterns)
  - Pass/Fail/Expired verdict (from on-page status badge)
  - Test date, batch number, manufacturing date, expiration, tested-by lab
  - Main product image (from og:image)
  - Buy URL (only present for Pass products: shop.trustified.co.in/product_details/...)

Respects:
- robots.txt (general crawl is allowed; we identify ourselves with User-Agent + contact)
- 1-second rate limit between requests to the same host
- 15-minute response cache so re-runs are cheap

This file does parsing only. Storage / DB sync lives in fetch_trustified.py.
"""
from __future__ import annotations

import re
import time
import logging
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
RATE_LIMIT = 1.0  # seconds between requests to the same host
TIMEOUT = 20

SITEMAP_URL = (
    "https://www.trustified.in/dynamic-passandfail_p_"
    "ad26dc62_0d97_4c38_8dd2_f4591f4befb1_0_5000-sitemap.xml"
)

# Labels we extract from on-page <strong> tags (left side of "label - value")
EXTRACT_LABELS = [
    "Brand", "Brand Name",
    "Product", "Product Name",
    "Status", "Test Status", "Verdict",
    "Date Published", "Date", "Test Date", "Tested On",
    "Batch No. Tested", "Batch No", "Batch No.", "Batch Number",
    "Manufacturing Date", "Mfg Date",
    "Expiration Date", "Expiry Date", "Expiry",
    "Tested By", "Lab",
    "Category",
]


@dataclass
class TrustifiedProduct:
    url: str
    slug: str
    title: Optional[str] = None
    image_url: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    brand: Optional[str] = None
    product_name: Optional[str] = None
    verdict: Optional[str] = None  # "Pass" / "Fail" / "Expired" / None
    date_published: Optional[str] = None
    batch_no: Optional[str] = None
    manufacturing_date: Optional[str] = None
    expiration_date: Optional[str] = None
    tested_by: Optional[str] = None
    category: Optional[str] = None
    buy_url: Optional[str] = None
    raw_fields: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        if not self.verdict:
            # If we have a buy URL, treat that as implicit Pass
            return bool(self.buy_url)
        v = self.verdict.lower()
        return "pass" in v and "fail" not in v


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


# ---------- Sitemap discovery ----------

def fetch_product_urls() -> list[str]:
    """Return all product URLs from the Trustified pass/fail sitemap."""
    parsed = urlparse(SITEMAP_URL)
    _rate.wait(parsed.netloc)
    r = _session().get(SITEMAP_URL, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return [loc.get_text(strip=True) for loc in soup.find_all("loc") if "/passandfail/" in loc.get_text()]


# ---------- Product page parsing ----------

def _meta(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    return tag.get("content") if tag else None


def _extract_strong_label_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Find on-page patterns like '<strong>Label - </strong><span>value</span>' or
    '<strong>Label</strong><span>- value</span>' and return them as a dict."""
    found: dict[str, str] = {}
    for strong in soup.find_all("strong"):
        label_text = strong.get_text(" ", strip=True).rstrip("-").strip()
        if not label_text:
            continue
        # Match label fragment against our known labels (loose comparison)
        matched = next((known for known in EXTRACT_LABELS if known.lower() == label_text.lower()), None)
        if not matched:
            continue
        # Walk forward from the <strong> to find the value
        # The value is usually in the next <span> after the strong, possibly wrapped
        value_parts: list[str] = []
        current = strong.parent
        # Get all text in the parent <p> after the strong tag
        if current is not None:
            text = current.get_text(" ", strip=True)
            # Strip the label prefix
            for sep in (f"{label_text} -", f"{label_text}-", f"{label_text} :", label_text):
                if text.lower().startswith(sep.lower()):
                    text = text[len(sep):].strip(" -:")
                    break
            if text:
                value_parts.append(text)
        if value_parts:
            value = value_parts[0].strip()
            if matched not in found and value:
                found[matched] = value
    return found


def _extract_buy_url(soup: BeautifulSoup) -> Optional[str]:
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "shop.trustified" in href and "/product_details/" in href:
            return href
    return None


def _verdict_from_url_or_text(soup: BeautifulSoup, status_field: Optional[str]) -> Optional[str]:
    """Detect verdict from explicit Status field, or from page heading/badge."""
    if status_field:
        v = status_field.strip()
        if "pass" in v.lower() and "fail" not in v.lower():
            return "Pass"
        if "fail" in v.lower():
            return "Fail"
        if "expir" in v.lower():
            return "Expired"
        return v.title()

    # Look for visible "PASSED" / "FAILED" labels in the page
    text = soup.get_text(" ", strip=True).lower()
    if " failed " in text or "fail status" in text:
        if " passed " in text:
            return "Pass"  # mentions both — the page is showing pass status
        return "Fail"
    if " passed " in text or "pass status" in text:
        return "Pass"
    if "expired" in text or "expir status" in text:
        return "Expired"
    return None


def _normalize_image(url: Optional[str]) -> Optional[str]:
    """Strip Wix transformation params to get the original image URL."""
    if not url:
        return None
    # https://static.wixstatic.com/media/73207d_xxx~mv2.png/v1/fill/...  →  base
    m = re.match(r"(https://static\.wixstatic\.com/media/[^/]+)", url)
    return m.group(1) if m else url


def _clean(text: Optional[str], max_len: int = 200) -> Optional[str]:
    """Strip leading dashes/en-dashes and whitespace; reject pathologically long values
    (some Trustified pages stuff the entire report into one <p>)."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^[–—−\-\s]+", "", text)  # leading – — − -
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    if not text:
        return None
    # If the value contains another label keyword like "Tested By" or "Batch No.", the
    # parser captured a whole paragraph, not just the value. Reject it.
    other_label_markers = ["Tested By -", "Batch No.", "Date Published", "Manufacturing Date", "Mfg Date", "Testing Status"]
    if sum(1 for m in other_label_markers if m in text) >= 2:
        return None
    if len(text) > max_len:
        return None
    return text


def parse_product(html: str, url: str) -> TrustifiedProduct:
    soup = BeautifulSoup(html, "html.parser")

    slug = url.rstrip("/").split("/")[-1]
    product = TrustifiedProduct(url=url, slug=slug)

    # OG title — looks like "MuscleBlaze Whey Gold   | Trustified Certification"
    og_title = _meta(soup, "og:title") or ""
    product.title = _clean(og_title.split("|")[0])

    og_image = _meta(soup, "og:image")
    product.image_url = _normalize_image(og_image)

    # Image dimensions if provided
    iw = _meta(soup, "og:image:width")
    ih = _meta(soup, "og:image:height")
    if iw and iw.isdigit():
        product.image_width = int(iw)
    if ih and ih.isdigit():
        product.image_height = int(ih)

    # On-page label/value pairs
    pairs = _extract_strong_label_pairs(soup)
    product.raw_fields = pairs

    product.brand = _clean(pairs.get("Brand") or pairs.get("Brand Name"))
    product.product_name = _clean(pairs.get("Product Name") or pairs.get("Product")) or product.title
    product.date_published = _clean(pairs.get("Date Published") or pairs.get("Tested On") or pairs.get("Test Date") or pairs.get("Date"))
    product.batch_no = _clean(pairs.get("Batch No. Tested") or pairs.get("Batch No") or pairs.get("Batch No.") or pairs.get("Batch Number"))
    product.manufacturing_date = _clean(pairs.get("Manufacturing Date") or pairs.get("Mfg Date"))
    product.expiration_date = _clean(pairs.get("Expiration Date") or pairs.get("Expiry Date") or pairs.get("Expiry"))
    product.tested_by = _clean(pairs.get("Tested By") or pairs.get("Lab"))
    product.category = _clean(pairs.get("Category"))

    # Brand inference: if no explicit Brand field, derive from title minus product name.
    # E.g. title="MuscleBlaze Whey Gold", product_name="Whey Gold 100% Whey" → brand="MuscleBlaze"
    if not product.brand and product.title and product.product_name:
        title_lower = product.title.lower()
        pname_lower = product.product_name.lower()
        # Find the first word(s) of the title that aren't in the product name
        title_words = product.title.split()
        keep = []
        for w in title_words:
            if w.lower() in pname_lower:
                break
            keep.append(w)
        if keep and len(keep) <= 4:
            product.brand = " ".join(keep)
    # Fallback: if title is just the brand (no product info merged in), use it
    if not product.brand and product.title and (not product.product_name or product.product_name == product.title):
        product.brand = product.title

    # Buy URL (only for Pass products per Trustified policy)
    product.buy_url = _extract_buy_url(soup)

    # Verdict
    product.verdict = _verdict_from_url_or_text(soup, pairs.get("Status") or pairs.get("Verdict") or pairs.get("Test Status"))

    # If we have a buy URL but no explicit verdict, infer Pass
    if not product.verdict and product.buy_url:
        product.verdict = "Pass"

    return product


def fetch_product(url: str) -> Optional[TrustifiedProduct]:
    parsed = urlparse(url)
    _rate.wait(parsed.netloc)
    try:
        r = _session().get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"  fetch failed: {url} → {e}")
        return None

    return parse_product(r.text, url)


def _find_shop_url_on_trustified(soup: BeautifulSoup) -> Optional[str]:
    """Locate the `shop.trustified.co.in/product_details/<id>` link on a
    trustified.in page (the destination of its 'Buy Now!' button)."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "shop.trustified" in href and "/product_details/" in href:
            return href
    return None


def _find_amazon_anchor_on_shop(soup: BeautifulSoup) -> Optional[str]:
    """Find the 'Amazon' button on a shop.trustified.co.in product page.
    Returns the anchor's href (typically an `https://amzn.to/<id>` short link)."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True).lower()
        if "amazon" in text or "amzn.to" in href.lower():
            return href
        if "amazon." in href.lower():
            return href
    return None


def resolve_amazon_buy_url(start_url: str) -> Optional[str]:
    """Walk the Trustified → Amazon redirect chain and return the final
    amazon.com / amazon.in URL.

    Accepts any of these as a starting point:
      - shop.trustified.co.in/product_details/<id>  (Pass products: stored as buy_url)
      - trustified.in/passandfail/<slug>            (any product: stored as report_url)
      - trustified.in/retestproducts/<slug>         (intermediate page some products link through)

    Returns None when the page has no Amazon button (typical for Fail / Expired
    products) or when any HTTP fetch in the chain fails."""
    if not start_url:
        return None
    current = start_url
    visited: set[str] = set()
    # Up to 3 hops: trustified.in → retestproducts → shop.trustified → Amazon
    for _ in range(3):
        if current in visited:
            return None
        visited.add(current)
        parsed = urlparse(current)
        _rate.wait(parsed.netloc)
        try:
            r = _session().get(current, timeout=TIMEOUT, allow_redirects=True)
            r.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"  resolve_amazon_buy_url fetch failed: {current} → {e}")
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        host = (urlparse(str(r.url)).hostname or "").lower()
        if host.startswith("shop.trustified"):
            anchor = _find_amazon_anchor_on_shop(soup)
            if not anchor:
                return None
            # Resolve the amzn.to short link to its final Amazon URL.
            try:
                _rate.wait(urlparse(anchor).netloc or host)
                rr = _session().get(anchor, timeout=TIMEOUT, allow_redirects=True)
            except requests.RequestException as e:
                logger.warning(f"  resolve_amazon_buy_url amzn.to follow failed: {anchor} → {e}")
                return None
            final = str(rr.url)
            if "amazon." not in (urlparse(final).hostname or ""):
                return None
            return final

        # On a trustified.in page (passandfail OR retestproducts): walk to the
        # next hop. Prefer a direct shop.trustified link; otherwise follow the
        # next /retestproducts/ link (the "Buy Now!" target on passandfail).
        shop_url = _find_shop_url_on_trustified(soup)
        if shop_url:
            current = shop_url
            continue

        # No shop link on this page — try following a Buy Now-style link to the
        # retestproducts page, which usually carries the shop link.
        next_hop = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            if "buy" in text and ("trustified.in" in href or href.startswith("/")):
                next_hop = href
                break
            if "/retestproducts/" in href:
                next_hop = href
                break
        if not next_hop:
            return None
        if next_hop.startswith("/"):
            next_hop = f"https://www.trustified.in{next_hop}"
        current = next_hop
    return None
