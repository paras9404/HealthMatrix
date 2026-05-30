"""Temporary admin tool: validate product images against Amazon listings.

Workflow:
  Option 3 (manual-assist):
    Admin pastes an Amazon URL. Server scrapes it (curl_cffi + BS4) and
    returns the gallery + product info; admin reviews and imports.
  Option 4 (auto-search):
    Server searches amazon.in and amazon.com for the product's brand+name,
    scores candidates by title similarity, and returns top matches with
    thumbnails. Admin clicks one → existing scrape flow runs on its URL.
    If neither marketplace yields a confident match, candidates is empty
    and the admin handles that product manually.

This blueprint owns only the read-only listing + scrape + search endpoints.
"""
import difflib
import json
import re
import threading
import time
from datetime import datetime
from urllib.parse import quote_plus, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, abort, jsonify, request
from sqlalchemy import and_, func, or_, select, text

from ...admin_auth import login_required, require_editor
from ...extensions import db, limiter
from ...models import Brand, Category, Rating, Source, Supplement, SupplementImage

# curl_cffi mimics Chrome's TLS+H2 fingerprint so Amazon's bot filter (which
# rejects raw `requests` traffic with 202/404 even on real product pages)
# treats us as a real browser. Optional — fall back to requests if missing.
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    cffi_requests = None
    _HAS_CURL_CFFI = False


admin_image_validation_bp = Blueprint("admin_image_validation", __name__)


# Realistic browser fingerprint — Amazon serves a sparse robot page to defaults.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}


def _is_amazon_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return "amazon." in host.lower()


def _extract_asin(url: str, html: str) -> str | None:
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    if m:
        return m.group(1)
    m = re.search(r'"ASIN"\s*:\s*"([A-Z0-9]{10})"', html)
    if m:
        return m.group(1)
    return None


def _canonicalize_amazon_url(url: str, asin: str | None) -> str:
    """Strip tracking params; if we know the ASIN, use the canonical /dp/ form."""
    parts = urlparse(url)
    if asin and parts.hostname:
        return f"{parts.scheme}://{parts.hostname}/dp/{asin}"
    return urlunparse(parts._replace(query="", fragment=""))


def _normalize_thumb_to_large(src: str) -> str:
    """Amazon image URLs encode size in a `._SL40_.` style segment.
    Replace it with the largest known size to fetch the hi-res variant."""
    return re.sub(r"\._[A-Z0-9_,]+_\.", "._SL1500_.", src)


def _slice_balanced_array(text: str, start: int) -> str | None:
    """Starting at text[start] (which must be '['), walk forward respecting
    nested brackets/braces and string literals until the matching ']'. Returns
    the JSON-parseable substring including both brackets, or None if unbalanced.

    Needed because Amazon's gallery `[ {…}, {…} ]` contains nested objects
    with their own brackets — a non-greedy regex would stop at the first `]`."""
    if start >= len(text) or text[start] != "[":
        return None
    depth = 0
    i = start
    in_str = False
    str_ch = ""
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == str_ch:
                in_str = False
        else:
            if c in ('"', "'"):
                in_str = True
                str_ch = c
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1
    return None


def _extract_images(html: str, soup: BeautifulSoup) -> list[dict]:
    """Pull the gallery out of Amazon's product HTML.

    Strategy: Amazon embeds the gallery as a JS literal `'colorImages': {'initial': [...]}`
    with hiRes/large/thumb URLs. That's the most reliable source. If it's missing
    (variant pages, alternate templates), fall back to scraping the DOM."""
    images: list[dict] = []
    seen: set[str] = set()

    def add(url: str, thumb: str | None = None):
        if not url or url in seen:
            return
        seen.add(url)
        images.append({"url": url, "thumb": thumb or url})

    # Primary path: parse the embedded gallery blob. The blob is JSON-shaped
    # with double-quoted strings, so we just need to slice balanced brackets.
    anchor = re.search(r"['\"]colorImages['\"]\s*:\s*\{\s*['\"]initial['\"]\s*:\s*", html)
    if anchor:
        arr_start = anchor.end()
        if arr_start < len(html) and html[arr_start] == "[":
            blob = _slice_balanced_array(html, arr_start)
            if blob:
                try:
                    entries = json.loads(blob)
                    for e in entries:
                        hi = e.get("hiRes") or e.get("large") or e.get("mainUrl")
                        add(hi, e.get("thumb") or e.get("lowRes") or hi)
                except (ValueError, TypeError):
                    pass

    # Fallback 1: #landingImage carries a JSON map of {url: [w, h]} variants.
    if not images:
        landing = soup.select_one("#landingImage, #imgBlkFront")
        if landing:
            data = landing.get("data-a-dynamic-image")
            if data:
                try:
                    parsed = json.loads(data)
                    # Pick the largest variant per URL key.
                    for url in parsed.keys():
                        add(url)
                except (ValueError, TypeError):
                    pass
            elif landing.get("src"):
                add(_normalize_thumb_to_large(landing["src"]))

    # Fallback 2: thumbnail strip below the main image.
    if not images:
        for img in soup.select("#altImages img, li.imageThumbnail img"):
            src = img.get("src") or img.get("data-src")
            if src:
                add(_normalize_thumb_to_large(src), src)

    return images


def _looks_like_captcha(html: str) -> bool:
    h = html.lower()
    return ("type the characters you see in this image" in h
            or "/errors/validatecaptcha" in h
            or "to discuss automated access to amazon data" in h
            or "robot check" in h)


_IMPERSONATE = "chrome131"
_SESSION_LOCK = threading.Lock()
# Keyed by (host, thread_id). curl_cffi Sessions hold a cookie jar and a libcurl
# handle that we don't want concurrent threads racing on — so each worker thread
# owns its own warmed-up session per host. Within a single thread the session is
# reused across calls, preserving the cookie-warmth that defeats Amazon's robot
# filter.
_SESSIONS: dict[tuple[str, int], object] = {}


def _get_amazon_session(host: str):
    """Per-host, per-thread curl_cffi Session that holds cookies. Warm up by
    hitting the homepage on first use — Amazon's robot filter responds far more
    leniently once session-id / ubid-acbin cookies are set, since naked /dp/
    requests look like a fresh-from-zero scraper."""
    key = (host, threading.get_ident())
    with _SESSION_LOCK:
        s = _SESSIONS.get(key)
        if s is not None:
            return s
    # Build & warm outside the lock so a slow homepage fetch doesn't block other
    # threads warming sessions for different hosts.
    s = cffi_requests.Session(impersonate=_IMPERSONATE)
    try:
        s.get(f"https://{host}/", timeout=12, allow_redirects=True)
    except Exception:
        pass
    with _SESSION_LOCK:
        # If two callers raced into the warm-up path, keep the first stored one
        # so we don't leak a session that callers never see again.
        existing = _SESSIONS.get(key)
        if existing is not None:
            return existing
        _SESSIONS[key] = s
        return s


def _drop_amazon_session(host: str) -> None:
    """Drop the calling thread's session for this host. Other threads keep
    their own sessions — they aren't affected by this thread's transient hiccup."""
    key = (host, threading.get_ident())
    with _SESSION_LOCK:
        _SESSIONS.pop(key, None)


def _fetch(url: str, *, retries: int = 1):
    """Fetch a URL through curl_cffi (Chrome TLS impersonation) if available,
    falling back to plain requests. Amazon's edge layer blocks libraries with
    Python's default TLS fingerprint, so curl_cffi is strongly preferred.

    Uses a per-host session warmed up on first use; retries once on CAPTCHA
    with a fresh session + jitter, which defeats most one-off robot pages."""
    if _HAS_CURL_CFFI:
        host = urlparse(url).hostname or "www.amazon.com"
        for attempt in range(retries + 1):
            session = _get_amazon_session(host)
            try:
                resp = session.get(url, timeout=15, allow_redirects=True)
            except Exception:
                _drop_amazon_session(host)
                if attempt >= retries:
                    raise
                time.sleep(1.5)
                continue
            if resp.status_code == 200 and not _looks_like_captcha(resp.text):
                return resp
            _drop_amazon_session(host)
            if attempt >= retries:
                return resp
            time.sleep(1.5 + attempt * 0.7)
    return requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)


def _clean(text: str) -> str:
    """Collapse whitespace and strip Amazon's invisible direction markers."""
    if not text:
        return ""
    # ‎ and ‏ are LTR/RTL marks Amazon sprinkles into spec values.
    text = text.replace("‎", " ").replace("‏", " ")
    return " ".join(text.split())


_SPEC_KEY_BLOCKLIST = {
    # Customer Reviews / Best Sellers Rank / Date First Available are scraped
    # as spec rows by Amazon's `table.a-keyvalue` template but the values are
    # noisy (duplicated star text, ranks that change daily) and not useful
    # alongside the structured product info.
    "customer reviews",
    "best sellers rank",
}


def _extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    """Parse Amazon's overlapping spec containers into a single key→value dict.

    Amazon serves the same spec data through several different DOM templates
    depending on category and locale (.in vs .com). We try each and merge —
    later sources overwrite earlier so the most authoritative wins."""
    specs: dict[str, str] = {}

    # 1) Product Overview "table" — the high-level Brand/Item Form/Material grid
    #    above About this item. It uses .po-* class names per spec row.
    for row in soup.select("#productOverview_feature_div table tr"):
        cells = row.select("td")
        if len(cells) >= 2:
            k = _clean(cells[0].get_text(" "))
            v = _clean(cells[1].get_text(" "))
            if k and v:
                specs[k] = v

    # 2) Tech-spec / detail-bullets / item-details tables. Amazon uses several
    #    near-identical templates depending on category & locale; `table.a-keyvalue`
    #    is the common th/td wrapper across all of them and catches the newer
    #    `voyager-ns-desktop-table-label` and older `prodDetSectionEntry` rows
    #    (e.g. Flavor, Specialty, Unit Count, Part Number on US listings).
    for sel in (
        "#productDetails_techSpec_section_1 tr",
        "#productDetails_techSpec_section_2 tr",
        "#productDetails_detailBullets_sections1 tr",
        "table.a-keyvalue tr",
    ):
        for row in soup.select(sel):
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                k = _clean(th.get_text(" "))
                v = _clean(td.get_text(" "))
                if k and v and k.lower() not in _SPEC_KEY_BLOCKLIST:
                    specs[k] = v

    # 3) Detail bullets list — newer template, shows up on .in product pages.
    for li in soup.select("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        spans = li.select("span.a-list-item > span")
        if len(spans) >= 2:
            k = _clean(spans[0].get_text(" ")).rstrip(":").strip()
            v = _clean(spans[1].get_text(" "))
            if k and v:
                specs[k] = v

    return specs


def _extract_about(soup: BeautifulSoup) -> list[str]:
    """The 'About this item' bullet list shown above product details."""
    bullets: list[str] = []
    for li in soup.select("#feature-bullets ul li:not(.aok-hidden) span.a-list-item"):
        text = _clean(li.get_text(" "))
        if text and text.lower() not in ("see more product details",):
            bullets.append(text)
    return bullets


def _extract_brand(soup: BeautifulSoup, specs: dict[str, str]) -> str | None:
    # bylineInfo is the linked "Visit the X Store" / "Brand: X" snippet under the title.
    by = soup.select_one("#bylineInfo")
    if by:
        text = _clean(by.get_text(" "))
        # Strip leading "Visit the " / "Brand: "
        for prefix in ("Visit the ", "Brand: "):
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):]
        # Strip trailing " Store"
        if text.endswith(" Store"):
            text = text[: -len(" Store")]
        if text:
            return text
    return specs.get("Brand") or specs.get("Manufacturer")


def scrape_amazon(url: str) -> dict:
    """Fetch and parse a single Amazon listing page. Raises on failure."""
    resp = _fetch(url)
    resp.raise_for_status()
    html = resp.text

    if _looks_like_captcha(html):
        raise RuntimeError("Amazon returned a CAPTCHA / robot-check page. "
                           "Try opening the URL in a browser, copying the final URL after the page loads, and pasting that.")

    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("#productTitle") or soup.select_one("title")
    title = _clean(title_el.get_text(" ")) if title_el else None

    images = _extract_images(html, soup)
    asin = _extract_asin(str(resp.url), html)
    specs = _extract_specs(soup)
    about = _extract_about(soup)
    brand = _extract_brand(soup, specs)

    price = None
    price_el = soup.select_one(".a-price .a-offscreen")
    if price_el:
        price = _clean(price_el.get_text(" "))

    return {
        "title": title,
        "asin": asin,
        "url": _canonicalize_amazon_url(str(resp.url), asin),
        "price": price,
        "brand": brand,
        "images": images,
        "specs": specs,
        "about": about,
    }


# -------------------- Bulk auto-search state --------------------
#
# Single-process in-memory state. Adequate for a dev/single-replica deploy
# (which is where this temporary tool runs). For multi-replica we'd need a
# shared store (Redis) or a real job queue.
_BULK_LOCK = threading.Lock()
_BULK_STATE: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "matched": 0,            # had ≥1 candidate above the 0.3 floor
    "skipped_no_match": 0,   # ran but returned []
    "errors": [],            # list of {id, name, error}
    "current": None,         # {id, name} of the supplement being processed
    "started_at": None,
    "finished_at": None,
    "force": False,
    "stop_requested": False,
}


def _reset_bulk_state(force: bool, total: int):
    _BULK_STATE.update({
        "running": True,
        "total": total,
        "done": 0,
        "matched": 0,
        "skipped_no_match": 0,
        "errors": [],
        "current": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": None,
        "force": force,
        "stop_requested": False,
    })


# -------------------- Unbox Health verified Amazon URL --------------------
#
# Unbox Health products carry an Amazon affiliate link on their public product
# page (Rating.buy_url for source 'unbox-health'). When present, that URL is the
# strongest possible candidate — a human curated and verified it — so we always
# surface it ahead of auto-search results.


def _get_unbox_buy_url(supp: Supplement) -> str | None:
    """Return the Amazon buy URL stored on the unbox-health Rating, if any.
    Walks already-loaded ratings to avoid an extra query when the relationship
    has been touched; falls back to a focused query otherwise."""
    for r in supp.ratings:
        if r.source and r.source.slug == "unbox-health" and r.buy_url:
            return r.buy_url
    return None


def _get_unbox_buy_url_map(supp_ids: list[int]) -> dict[int, str]:
    """Batch lookup of unbox-health buy_url per supplement id (for listing pages).
    One query regardless of page size."""
    if not supp_ids:
        return {}
    rows = (db.session.query(Rating.supplement_id, Rating.buy_url)
            .join(Source, Source.id == Rating.source_id)
            .filter(Source.slug == "unbox-health",
                    Rating.buy_url.isnot(None),
                    Rating.supplement_id.in_(supp_ids))
            .all())
    return {sid: url for sid, url in rows}


def _get_source_slugs_map(supp_ids: list[int]) -> dict[int, list[str]]:
    """Batch lookup of every source slug each supplement has a rating from.
    Powers the per-row source pills in the validation queue."""
    if not supp_ids:
        return {}
    rows = (db.session.query(Rating.supplement_id, Source.slug)
            .join(Source, Source.id == Rating.source_id)
            .filter(Rating.supplement_id.in_(supp_ids))
            .distinct()
            .all())
    out: dict[int, list[str]] = {}
    for sid, slug in rows:
        out.setdefault(sid, []).append(slug)
    return out


def _merge_unbox_candidate(auto_candidates: list[dict] | None,
                           unbox_candidate: dict | None) -> list[dict]:
    """Prepend the unbox-health candidate to the auto-search list, deduping by
    ASIN so we don't show the same listing twice when the auto-search also
    surfaced it. Returns a new list — does not mutate the cached column."""
    auto = list(auto_candidates or [])
    if not unbox_candidate:
        return auto
    asin = (unbox_candidate.get("asin") or "").upper()
    deduped = [c for c in auto if (c.get("asin") or "").upper() != asin]
    return [unbox_candidate, *deduped]


def _make_unbox_candidate(supp: Supplement, buy_url: str) -> dict:
    """Build a candidate dict mirroring the auto-search shape so the frontend
    can render the unbox-health Amazon URL alongside auto-search candidates.

    Re-uses the supplement's existing image (which itself came from Unbox
    Health's CDN at import time) so we don't need to fetch Amazon up front;
    when the admin clicks the candidate, the existing scrape flow runs."""
    asin = _extract_asin(buy_url, "")
    parsed = urlparse(buy_url)
    domain = (parsed.hostname or "amazon.in").removeprefix("www.")
    return {
        "asin": asin or f"unbox-{supp.id}",
        "title": supp.name,
        "image": supp.image,
        "url": buy_url,
        "domain": domain,
        "score": 1.0,
        "source": "unbox-health",
    }


# -------------------- Labdoor → Amazon URL cache --------------------
#
# Labdoor reviews link to Amazon via a redirect (`labdoor.com/review/<slug>/buy/<id>`).
# Resolving each redirect costs two HTTP round-trips, so we cache the final
# amazon.com URL on disk per supplement and reuse it across requests.
#
# Disk-backed JSON (rather than DB) so we don't need a migration just to ship
# this temporary tool. The file lives under instance/ alongside the SQLite DB.
import os  # noqa: E402  (stdlib import kept near the cache code that uses it)

_LABDOOR_CACHE_LOCK = threading.Lock()
_LABDOOR_CACHE: dict[str, dict] | None = None  # lazy-loaded singleton


def _labdoor_cache_path() -> str:
    from flask import current_app
    inst = current_app.instance_path
    os.makedirs(inst, exist_ok=True)
    return os.path.join(inst, "labdoor_amazon_cache.json")


def _load_labdoor_cache() -> dict[str, dict]:
    """Load the on-disk cache once per process; return the in-memory copy on
    subsequent calls. Always-string keys for JSON compatibility."""
    global _LABDOOR_CACHE
    with _LABDOOR_CACHE_LOCK:
        if _LABDOOR_CACHE is not None:
            return _LABDOOR_CACHE
        path = _labdoor_cache_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                _LABDOOR_CACHE = json.load(f) or {}
        except (FileNotFoundError, ValueError):
            _LABDOOR_CACHE = {}
        return _LABDOOR_CACHE


def _save_labdoor_cache() -> None:
    """Atomic write so a crash mid-write doesn't truncate the cache."""
    with _LABDOOR_CACHE_LOCK:
        if _LABDOOR_CACHE is None:
            return
        path = _labdoor_cache_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_LABDOOR_CACHE, f)
        os.replace(tmp, path)


def _set_labdoor_cache_entry(supp_id: int, amazon_url: str | None) -> None:
    cache = _load_labdoor_cache()
    with _LABDOOR_CACHE_LOCK:
        cache[str(supp_id)] = {
            "amazon_url": amazon_url,
            "resolved_at": datetime.utcnow().isoformat() + "Z",
        }
    _save_labdoor_cache()


def _get_labdoor_amazon_url(supp_id: int) -> str | None:
    """Return the cached Amazon URL for a supplement, or None if not yet
    resolved (or resolution previously came back empty)."""
    cache = _load_labdoor_cache()
    entry = cache.get(str(supp_id))
    return entry.get("amazon_url") if entry else None


def _get_labdoor_amazon_url_map(supp_ids: list[int]) -> dict[int, str]:
    """Batch lookup for the listing page — only returns entries with a real
    URL; missing or null entries are omitted so the caller can use truthiness
    to decide whether to render the verified pill."""
    if not supp_ids:
        return {}
    cache = _load_labdoor_cache()
    out: dict[int, str] = {}
    for sid in supp_ids:
        entry = cache.get(str(sid))
        if entry and entry.get("amazon_url"):
            out[sid] = entry["amazon_url"]
    return out


def _get_labdoor_buy_url(supp: Supplement) -> str | None:
    """Return the Labdoor Rating's stored buy_url (the labdoor.com redirect)
    for a supplement, if any."""
    for r in supp.ratings:
        if r.source and r.source.slug == "labdoor" and r.buy_url:
            return r.buy_url
    return None


def _resolve_labdoor_amazon_for_supplement(supp: Supplement) -> str | None:
    """Resolve and cache the Amazon URL for a single supplement's Labdoor
    rating. Returns the resolved URL or None if no Labdoor rating, no buy_url,
    or the redirect didn't land on Amazon."""
    from ...services.labdoor_scraper import resolve_amazon_buy_url, review_url_from_buy_url
    buy_url = _get_labdoor_buy_url(supp)
    if not buy_url:
        return None
    review_url = review_url_from_buy_url(buy_url) or buy_url.rsplit("/buy/", 1)[0]
    amazon_url = resolve_amazon_buy_url(review_url)
    _set_labdoor_cache_entry(supp.id, amazon_url)
    return amazon_url


def _make_labdoor_candidate(supp: Supplement, amazon_url: str) -> dict:
    """Mirror of _make_unbox_candidate but tagged with source='labdoor' so the
    frontend can render a "Verified by Labdoor" panel separate from Unbox."""
    asin = _extract_asin(amazon_url, "")
    parsed = urlparse(amazon_url)
    domain = (parsed.hostname or "amazon.com").removeprefix("www.")
    return {
        "asin": asin or f"labdoor-{supp.id}",
        "title": supp.name,
        "image": supp.image,
        "url": amazon_url,
        "domain": domain,
        "score": 1.0,
        "source": "labdoor",
    }


def _merge_labdoor_candidate(auto_candidates: list[dict],
                             labdoor_candidate: dict | None) -> list[dict]:
    """Prepend the labdoor candidate after the unbox candidate (if any),
    deduping by ASIN. Mirrors `_merge_unbox_candidate`."""
    if not labdoor_candidate:
        return auto_candidates
    asin = (labdoor_candidate.get("asin") or "").upper()
    deduped = [c for c in auto_candidates if (c.get("asin") or "").upper() != asin]
    return [labdoor_candidate, *deduped]


# -------------------- Trustified → Amazon URL cache --------------------
#
# Trustified's flow: the trustified.in pass/fail page links to a
# shop.trustified.co.in product page; that page has an Amazon button (an
# `amzn.to` short link). Resolving the chain costs 2-3 fetches per product, so
# we cache the final amazon.in URL on disk per supplement.

_TRUSTIFIED_CACHE_LOCK = threading.Lock()
_TRUSTIFIED_CACHE: dict[str, dict] | None = None


def _trustified_cache_path() -> str:
    from flask import current_app
    inst = current_app.instance_path
    os.makedirs(inst, exist_ok=True)
    return os.path.join(inst, "trustified_amazon_cache.json")


def _load_trustified_cache() -> dict[str, dict]:
    global _TRUSTIFIED_CACHE
    with _TRUSTIFIED_CACHE_LOCK:
        if _TRUSTIFIED_CACHE is not None:
            return _TRUSTIFIED_CACHE
        path = _trustified_cache_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                _TRUSTIFIED_CACHE = json.load(f) or {}
        except (FileNotFoundError, ValueError):
            _TRUSTIFIED_CACHE = {}
        return _TRUSTIFIED_CACHE


def _save_trustified_cache() -> None:
    with _TRUSTIFIED_CACHE_LOCK:
        if _TRUSTIFIED_CACHE is None:
            return
        path = _trustified_cache_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_TRUSTIFIED_CACHE, f)
        os.replace(tmp, path)


def _set_trustified_cache_entry(supp_id: int, amazon_url: str | None) -> None:
    cache = _load_trustified_cache()
    with _TRUSTIFIED_CACHE_LOCK:
        cache[str(supp_id)] = {
            "amazon_url": amazon_url,
            "resolved_at": datetime.utcnow().isoformat() + "Z",
        }
    _save_trustified_cache()


def _get_trustified_amazon_url(supp_id: int) -> str | None:
    cache = _load_trustified_cache()
    entry = cache.get(str(supp_id))
    return entry.get("amazon_url") if entry else None


def _get_trustified_amazon_url_map(supp_ids: list[int]) -> dict[int, str]:
    if not supp_ids:
        return {}
    cache = _load_trustified_cache()
    out: dict[int, str] = {}
    for sid in supp_ids:
        entry = cache.get(str(sid))
        if entry and entry.get("amazon_url"):
            out[sid] = entry["amazon_url"]
    return out


def _get_trustified_start_url(supp: Supplement) -> str | None:
    """Pick the best URL to start the Trustified → Amazon walk for a supplement.
    Prefers buy_url (shop.trustified.co.in — already 1 hop closer to Amazon)
    and falls back to report_url (trustified.in pass/fail page)."""
    for r in supp.ratings:
        if not (r.source and r.source.slug == "trustified"):
            continue
        if r.buy_url:
            return r.buy_url
        if r.report_url:
            return r.report_url
    return None


def _resolve_trustified_amazon_for_supplement(supp: Supplement) -> str | None:
    from ...services.trustified_scraper import resolve_amazon_buy_url as _trustified_resolve
    start = _get_trustified_start_url(supp)
    if not start:
        return None
    amazon_url = _trustified_resolve(start)
    _set_trustified_cache_entry(supp.id, amazon_url)
    return amazon_url


def _make_trustified_candidate(supp: Supplement, amazon_url: str) -> dict:
    asin = _extract_asin(amazon_url, "")
    parsed = urlparse(amazon_url)
    domain = (parsed.hostname or "amazon.in").removeprefix("www.")
    return {
        "asin": asin or f"trustified-{supp.id}",
        "title": supp.name,
        "image": supp.image,
        "url": amazon_url,
        "domain": domain,
        "score": 1.0,
        "source": "trustified",
    }


def _merge_trustified_candidate(auto_candidates: list[dict],
                                trustified_candidate: dict | None) -> list[dict]:
    if not trustified_candidate:
        return auto_candidates
    asin = (trustified_candidate.get("asin") or "").upper()
    deduped = [c for c in auto_candidates if (c.get("asin") or "").upper() != asin]
    return [trustified_candidate, *deduped]


# -------------------- Auto-search (option 4) --------------------


# Words too generic to count as a real match. Stripped before scoring so two
# unrelated multivitamins don't both score high just because they share "tablet".
_STOPWORDS = {
    "the", "and", "with", "for", "of", "a", "an", "in", "to", "by",
    "tablet", "tablets", "capsule", "capsules", "softgel", "softgels",
    "powder", "drops", "liquid", "gummy", "gummies", "supplement", "supplements",
    "ct", "count", "pack", "size", "g", "gm", "mg", "mcg", "kg", "ml",
    "natural", "organic", "premium",
}


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    # Split on non-alphanumeric, lowercase, drop pure-numeric and stopwords.
    raw = re.split(r"[^a-z0-9]+", text.lower())
    return {t for t in raw if t and t not in _STOPWORDS and not t.isdigit()}


def _score(query: str, title: str) -> float:
    """Hybrid name-match score in [0, 1].

    Combines two signals:
      - Token overlap (fraction of the query's meaningful tokens that appear
        in the title) — robust for product names where word order is fluid.
      - SequenceMatcher ratio — catches near-spelling matches and substring
        runs that token overlap misses.
    Take the max so either signal alone can vouch for a candidate."""
    qt = _tokens(query)
    tt = _tokens(title)
    if not qt:
        return 0.0
    overlap = len(qt & tt) / len(qt) if qt else 0.0
    seq = difflib.SequenceMatcher(None, (query or "").lower(), (title or "").lower()).ratio()
    return round(max(overlap, seq), 3)


def _parse_search_results(html: str, domain: str) -> list[dict]:
    """Pull search-result tiles out of an Amazon SERP.

    Title extraction is intentionally redundant: Amazon's modern SERP puts the
    brand in the first h2 span and the full descriptive title in the second
    span (or only in the image alt-text on some tiles). We prefer the longest
    candidate so the scorer has something to work with."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()
    for tile in soup.select('div[data-asin][data-component-type="s-search-result"]'):
        asin = (tile.get("data-asin") or "").strip()
        if not asin or asin in seen:
            continue

        # Drop sponsored ads. Amazon marks them with class="AdHolder" on the
        # tile and an inner ".puis-sponsored-label-text" / "Sponsored Ad - "
        # prefix on the image alt. Same ASIN often shows up twice (sponsored
        # then organic) so skipping the sponsored copy lets the organic one
        # through on the next iteration.
        tile_classes = tile.get("class") or []
        if "AdHolder" in tile_classes:
            continue
        if tile.select_one(".puis-sponsored-label-text"):
            continue

        candidates: list[str] = []
        for span in tile.select("h2 span"):
            candidates.append(_clean(span.get_text(" ")))
        a = tile.select_one("h2 a")
        if a:
            aria = a.get("aria-label")
            if aria:
                candidates.append(_clean(aria))
            candidates.append(_clean(a.get_text(" ")))
        img_el = tile.select_one("img.s-image")
        if img_el and img_el.get("alt"):
            candidates.append(_clean(img_el["alt"]))

        candidates = [c for c in candidates if c]
        if not candidates:
            continue
        # Use the longest candidate — typically the full descriptive title.
        title = max(candidates, key=len)

        image = img_el.get("src") if img_el else None
        link_el = a or tile.select_one("a.a-link-normal[href*='/dp/']")
        href = link_el.get("href") if link_el else None
        url = (f"https://www.{domain}{href}"
               if href and href.startswith("/")
               else f"https://www.{domain}/dp/{asin}")
        seen.add(asin)
        results.append({
            "asin": asin,
            "title": title,
            "image": image,
            "url": url,
            "domain": domain,
        })
    return results


def _search_amazon(domain: str, query: str, attempts: int = 2) -> list[dict]:
    """Fetch and parse one Amazon search results page.

    Retries up to `attempts` times on empty results — Amazon occasionally
    serves a 200 with a near-empty body (HTTP/2 rate-limit signal) or a
    CAPTCHA/robot page. A short backoff usually lets the next request through,
    which is critical for the bulk worker so .com candidates aren't silently
    missing from cached entries."""
    url = f"https://www.{domain}/s?k={quote_plus(query)}"
    last_results: list[dict] = []
    for attempt in range(max(attempts, 1)):
        try:
            resp = _fetch(url)
            if resp.status_code != 200:
                # Hard error — back off and retry.
                last_results = []
            elif _looks_like_captcha(resp.text):
                last_results = []
            else:
                last_results = _parse_search_results(resp.text, domain)
                if last_results:
                    return last_results
        except Exception:
            # One marketplace failing shouldn't poison results from the other.
            last_results = []
        if attempt + 1 < attempts:
            time.sleep(1.5)
    return last_results


# -------------------- Routes --------------------


@admin_image_validation_bp.route("/sources", methods=["GET"])
@login_required
def list_sources_with_counts():
    """List sources that actually have rated supplements, with the supplement
    count per source — used to populate the source filter dropdown so the admin
    only sees sources that yield results."""
    rows = (db.session.query(Source.slug, Source.name,
                             func.count(func.distinct(Rating.supplement_id)))
            .join(Rating, Rating.source_id == Source.id)
            .group_by(Source.id, Source.slug, Source.name)
            .order_by(Source.sort_order.asc(), Source.name.asc())
            .all())
    return jsonify({
        "sources": [{"slug": slug, "name": name, "count": count}
                    for slug, name, count in rows],
    })


@admin_image_validation_bp.route("/products", methods=["GET"])
@login_required
def list_products():
    """Paginated list of supplements with current image state, for the validation queue."""
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    filt = (request.args.get("filter") or "all").strip()
    search = (request.args.get("q") or "").strip()
    source_slug = (request.args.get("source") or "").strip()
    hide_done = (request.args.get("hide_done") or "").lower() in ("1", "true", "yes")

    img_count_sq = (select(func.count(SupplementImage.id))
                    .where(SupplementImage.supplement_id == Supplement.id)
                    .scalar_subquery())

    query = (Supplement.query
             .outerjoin(Brand, Brand.id == Supplement.brand_id)
             .outerjoin(Category, Category.id == Supplement.category_id))

    if search:
        like = f"%{search}%"
        query = query.filter(or_(Supplement.name.ilike(like),
                                    Brand.name.ilike(like)))

    # Source filter — show only supplements with a rating from the given source
    # slug (trustified, unbox-health, labdoor, …). EXISTS avoids row-multiplication
    # for products with multiple ratings.
    if source_slug:
        rating_exists = (select(Rating.id)
                         .join(Source, Source.id == Rating.source_id)
                         .where(Rating.supplement_id == Supplement.id,
                                Source.slug == source_slug)
                         .exists())
        query = query.filter(rating_exists)

    # "Hide done" filter — exclude products the admin already finished with.
    # Mirrors the frontend's auto-validation heuristic: linked Amazon URL +
    # at least 2 gallery images means the product has been imported. Doing
    # this server-side keeps pages dense (no sparse "8 done items hidden"
    # placeholders) and keeps `total` accurate for pagination.
    if hide_done:
        query = query.filter(
            or_(
                Supplement.amazon_url.is_(None),
                img_count_sq < 2,
            )
        )

    if filt == "no_images":
        query = query.filter(img_count_sq == 0,
                             Supplement.image_url.is_(None),
                             Supplement.image_path.is_(None))
    elif filt == "single_image":
        query = query.filter(
            or_(
                # Only legacy single image, no gallery rows.
                and_(img_count_sq == 0,
                        or_(Supplement.image_url.isnot(None),
                               Supplement.image_path.isnot(None))),
                img_count_sq == 1,
            )
        )
    elif filt == "needs_review":
        # Anything that's either imageless or has a single image — i.e. likely incomplete.
        query = query.filter(img_count_sq <= 1)

    # Sort by best-candidate match % desc so high-confidence matches surface first.
    # Products without cached candidates fall back to -1 and land at the bottom,
    # name asc breaks ties deterministically.
    max_score_order = text(
        "COALESCE((SELECT MAX((c->>'score')::float) "
        "FROM jsonb_array_elements(supplements.amazon_candidates) c), -1) DESC"
    )
    query = query.order_by(max_score_order, Supplement.name.asc())

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    supp_ids = [s.id for s in items]
    unbox_urls = _get_unbox_buy_url_map(supp_ids)
    labdoor_urls = _get_labdoor_amazon_url_map(supp_ids)
    trustified_urls = _get_trustified_amazon_url_map(supp_ids)
    source_slugs_by_supp = _get_source_slugs_map(supp_ids)

    out = []
    for s in items:
        gallery_count = len(s.images) if s.images else 0
        legacy_only = gallery_count == 0 and (s.image_url or s.image_path)
        cand_count = len(s.amazon_candidates) if s.amazon_candidates is not None else None
        max_score = None
        if s.amazon_candidates:
            scores = [c.get("score") for c in s.amazon_candidates if isinstance(c, dict) and c.get("score") is not None]
            if scores:
                max_score = max(scores)
        unbox_url = unbox_urls.get(s.id)
        labdoor_amazon_url = labdoor_urls.get(s.id)
        trustified_amazon_url = trustified_urls.get(s.id)
        out.append({
            "id": s.id,
            "name": s.name,
            "slug": s.slug,
            "brand": s.brand.name if s.brand else None,
            "category": s.category.name if s.category else None,
            "first_image_url": s.image,
            "image_count": gallery_count + (1 if legacy_only else 0),
            "legacy_only": bool(legacy_only),
            "amazon_url": s.amazon_url,
            "amazon_asin": s.amazon_asin,
            "amazon_candidates_count": cand_count,
            "amazon_candidates_max_score": max_score,
            "amazon_searched_at": s.amazon_searched_at.isoformat() if s.amazon_searched_at else None,
            "unbox_amazon_url": unbox_url,
            "labdoor_amazon_url": labdoor_amazon_url,
            "trustified_amazon_url": trustified_amazon_url,
            "source_slugs": source_slugs_by_supp.get(s.id, []),
        })
    return jsonify({
        "items": out,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


def _build_queries(s: Supplement) -> tuple[list[str], str]:
    """Return (queries_to_try, score_target) for a supplement."""
    brand = (s.brand.name if s.brand else "").strip()
    name = (s.name or "").strip()
    # Avoid duplicate brand when name already starts with it.
    if brand and not name.lower().startswith(brand.lower()):
        primary = _clean(f"{brand} {name}")
    else:
        primary = _clean(name)

    queries: list[str] = []
    if s.upc:
        queries.append(s.upc)
    if primary:
        queries.append(primary)
    name_first_words = " ".join(name.split()[:5])
    if name_first_words and name_first_words not in queries:
        queries.append(name_first_words)
    return queries, primary


def _run_auto_search(s: Supplement) -> tuple[list[dict], list[str]]:
    """Live-search Amazon for a supplement. Returns (top_candidates, queries_tried).
    Pure: doesn't touch the DB. Caller decides whether to persist."""
    queries, score_target = _build_queries(s)

    raw: list[dict] = []
    queries_tried: list[str] = []
    for q in queries:
        if not q:
            continue
        queries_tried.append(q)
        for domain in ("amazon.in", "amazon.com"):
            raw.extend(_search_amazon(domain, q))
        if len(raw) >= 20:
            break

    by_asin: dict[str, dict] = {}
    for r in raw:
        r["score"] = _score(score_target, r["title"])
        existing = by_asin.get(r["asin"])
        if not existing or r["score"] > existing["score"]:
            by_asin[r["asin"]] = r

    # 0.3 floor — below that, results are usually unrelated suggestions.
    scored = [r for r in by_asin.values() if r["score"] >= 0.3]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:8], queries_tried


@admin_image_validation_bp.route("/auto-search", methods=["POST"])
@login_required
def auto_search():
    """Return scored candidates for a supplement, preferring the cached set.

    The cache (supplement.amazon_candidates) is populated by the bulk worker
    OR by a previous live call here. Empty list means 'no confident match —
    handle manually'. Pass `force: true` to bypass the cache."""
    data = request.get_json(silent=True) or {}
    supp_id = data.get("supplement_id")
    force = bool(data.get("force"))
    if not supp_id:
        abort(400, description="supplement_id is required")
    s = Supplement.query.get(supp_id)
    if not s:
        abort(404, description="supplement not found")

    unbox_url = _get_unbox_buy_url(s)
    unbox_candidate = _make_unbox_candidate(s, unbox_url) if unbox_url else None
    labdoor_url = _get_labdoor_amazon_url(s.id)
    labdoor_candidate = _make_labdoor_candidate(s, labdoor_url) if labdoor_url else None
    trustified_url = _get_trustified_amazon_url(s.id)
    trustified_candidate = _make_trustified_candidate(s, trustified_url) if trustified_url else None

    def _assemble(auto: list[dict]) -> list[dict]:
        merged = _merge_unbox_candidate(auto, unbox_candidate)
        merged = _merge_labdoor_candidate(merged, labdoor_candidate)
        return _merge_trustified_candidate(merged, trustified_candidate)

    if not force and s.amazon_candidates is not None:
        return jsonify({
            "supplement_id": s.id,
            "candidates": _assemble(s.amazon_candidates),
            "unbox_candidate": unbox_candidate,
            "labdoor_candidate": labdoor_candidate,
            "trustified_candidate": trustified_candidate,
            "searched_at": s.amazon_searched_at.isoformat() if s.amazon_searched_at else None,
            "from_cache": True,
        })

    auto_candidates, queries_tried = _run_auto_search(s)
    s.amazon_candidates = auto_candidates
    s.amazon_searched_at = datetime.utcnow()
    db.session.commit()
    return jsonify({
        "supplement_id": s.id,
        "queries_tried": queries_tried,
        "candidates": _assemble(auto_candidates),
        "unbox_candidate": unbox_candidate,
        "labdoor_candidate": labdoor_candidate,
        "trustified_candidate": trustified_candidate,
        "searched_at": s.amazon_searched_at.isoformat() if s.amazon_searched_at else None,
        "from_cache": False,
    })


def _bulk_worker(app, supp_ids: list[int], force: bool, throttle: float):
    """Background worker. Iterates supplement IDs, runs the live search,
    persists candidates, and updates the in-memory progress state."""
    with app.app_context():
        for sid in supp_ids:
            with _BULK_LOCK:
                if _BULK_STATE["stop_requested"]:
                    break
            s = Supplement.query.get(sid)
            if not s:
                with _BULK_LOCK:
                    _BULK_STATE["errors"].append({"id": sid, "name": None, "error": "supplement not found"})
                    _BULK_STATE["done"] += 1
                continue
            with _BULK_LOCK:
                _BULK_STATE["current"] = {"id": s.id, "name": s.name}
            try:
                candidates, _ = _run_auto_search(s)
                s.amazon_candidates = candidates
                s.amazon_searched_at = datetime.utcnow()
                db.session.commit()
                with _BULK_LOCK:
                    if candidates:
                        _BULK_STATE["matched"] += 1
                    else:
                        _BULK_STATE["skipped_no_match"] += 1
            except Exception as e:
                db.session.rollback()
                with _BULK_LOCK:
                    _BULK_STATE["errors"].append({"id": s.id, "name": s.name, "error": str(e)[:200]})
            finally:
                with _BULK_LOCK:
                    _BULK_STATE["done"] += 1
            # Throttle so we don't hammer Amazon. Each iteration already costs
            # ~2 SERP fetches at ~1s each, so a small extra sleep is enough.
            time.sleep(throttle)
        with _BULK_LOCK:
            _BULK_STATE["running"] = False
            _BULK_STATE["current"] = None
            _BULK_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"


@admin_image_validation_bp.route("/bulk-search", methods=["POST"])
@require_editor
def bulk_search_start():
    """Kick off background auto-search across the catalog.

    Body params:
      - force (bool, default false): re-search products that already have a
        cached candidate list.
      - limit (int, optional): cap how many supplements to process this run.
      - filter (str, optional): same values as /products listing — defaults
        to "all" so we cache for the whole catalog.
    """
    with _BULK_LOCK:
        if _BULK_STATE["running"]:
            return jsonify({
                "started": False,
                "message": "A bulk search is already running.",
                "state": _BULK_STATE,
            }), 409

    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))
    limit = data.get("limit")
    filt = (data.get("filter") or "all").strip()
    source_slug = (data.get("source") or "").strip()

    query = Supplement.query
    if filt == "needs_review":
        # Only products with ≤1 image — the audience that benefits most.
        img_count_sq = (select(func.count(SupplementImage.id))
                        .where(SupplementImage.supplement_id == Supplement.id)
                        .scalar_subquery())
        query = query.filter(img_count_sq <= 1)
    if source_slug:
        rating_exists = (select(Rating.id)
                         .join(Source, Source.id == Rating.source_id)
                         .where(Rating.supplement_id == Supplement.id,
                                Source.slug == source_slug)
                         .exists())
        query = query.filter(rating_exists)
    if not force:
        query = query.filter(Supplement.amazon_candidates.is_(None))
    query = query.order_by(Supplement.id)
    if limit:
        query = query.limit(int(limit))

    supp_ids = [row.id for row in query.with_entities(Supplement.id).all()]
    if not supp_ids:
        return jsonify({
            "started": False,
            "message": "Nothing to do — every product matching the filter already has cached candidates. Pass force=true to re-run.",
            "state": _BULK_STATE,
        })

    _reset_bulk_state(force=force, total=len(supp_ids))
    # Capture the Flask app object so the worker can push an app context.
    from flask import current_app
    app = current_app._get_current_object()
    threading.Thread(
        target=_bulk_worker,
        args=(app, supp_ids, force, 0.5),
        daemon=True,
    ).start()
    return jsonify({"started": True, "total": len(supp_ids), "state": _BULK_STATE})


@admin_image_validation_bp.route("/bulk-search/status", methods=["GET"])
@login_required
@limiter.exempt
def bulk_search_status():
    # Polled every 2s by the admin UI while a job runs — exempt from the
    # global 200/hour cap so a long-running job doesn't lock the admin out.
    with _BULK_LOCK:
        # Return a copy so the dict can't change underneath JSON serialization.
        return jsonify(dict(_BULK_STATE))


@admin_image_validation_bp.route("/bulk-search/stop", methods=["POST"])
@require_editor
def bulk_search_stop():
    with _BULK_LOCK:
        if not _BULK_STATE["running"]:
            return jsonify({"running": False, "message": "Not running."})
        _BULK_STATE["stop_requested"] = True
    return jsonify({"running": True, "message": "Stop requested — worker will halt after the current product."})


# -------------------- Labdoor → Amazon resolve --------------------
#
# Mirrors the bulk-search worker pattern but resolves Labdoor's `/buy/<id>`
# redirect into a final amazon.com URL and persists the result to disk via the
# labdoor cache helpers above.

_LABDOOR_BULK_LOCK = threading.Lock()
_LABDOOR_BULK_STATE: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "matched": 0,            # resolved to a real amazon URL
    "skipped_no_match": 0,   # ran but no amazon redirect (iHerb-only / dead link)
    "errors": [],
    "current": None,
    "started_at": None,
    "finished_at": None,
    "force": False,
    "stop_requested": False,
}


def _reset_labdoor_bulk_state(force: bool, total: int):
    _LABDOOR_BULK_STATE.update({
        "running": True, "total": total, "done": 0, "matched": 0,
        "skipped_no_match": 0, "errors": [], "current": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": None, "force": force, "stop_requested": False,
    })


@admin_image_validation_bp.route("/resolve-labdoor-amazon", methods=["POST"])
@require_editor
def resolve_labdoor_amazon():
    """Resolve and cache a single supplement's Labdoor → Amazon URL.

    Body params: { supplement_id: int, force?: bool }
    Response: { supplement_id, amazon_url | null, from_cache, resolved_at }
    """
    data = request.get_json(silent=True) or {}
    supp_id = data.get("supplement_id")
    force = bool(data.get("force"))
    if not supp_id:
        abort(400, description="supplement_id is required")
    s = Supplement.query.get(supp_id)
    if not s:
        abort(404, description="supplement not found")

    cache = _load_labdoor_cache()
    cached = cache.get(str(supp_id))
    if cached and not force:
        return jsonify({
            "supplement_id": s.id,
            "amazon_url": cached.get("amazon_url"),
            "resolved_at": cached.get("resolved_at"),
            "from_cache": True,
        })

    amazon_url = _resolve_labdoor_amazon_for_supplement(s)
    new_cache_entry = _load_labdoor_cache().get(str(supp_id), {})
    return jsonify({
        "supplement_id": s.id,
        "amazon_url": amazon_url,
        "resolved_at": new_cache_entry.get("resolved_at"),
        "from_cache": False,
    })


def _labdoor_bulk_worker(app, supp_ids: list[int], force: bool, throttle: float):
    """Walk a list of Labdoor-rated supplement IDs, resolving each one's Amazon
    URL and updating progress. Mirrors `_bulk_worker` for auto-search."""
    with app.app_context():
        for sid in supp_ids:
            with _LABDOOR_BULK_LOCK:
                if _LABDOOR_BULK_STATE["stop_requested"]:
                    break
            s = Supplement.query.get(sid)
            if not s:
                with _LABDOOR_BULK_LOCK:
                    _LABDOOR_BULK_STATE["errors"].append({"id": sid, "name": None, "error": "supplement not found"})
                    _LABDOOR_BULK_STATE["done"] += 1
                continue
            with _LABDOOR_BULK_LOCK:
                _LABDOOR_BULK_STATE["current"] = {"id": s.id, "name": s.name}
            try:
                amazon_url = _resolve_labdoor_amazon_for_supplement(s)
                with _LABDOOR_BULK_LOCK:
                    if amazon_url:
                        _LABDOOR_BULK_STATE["matched"] += 1
                    else:
                        _LABDOOR_BULK_STATE["skipped_no_match"] += 1
            except Exception as e:
                with _LABDOOR_BULK_LOCK:
                    _LABDOOR_BULK_STATE["errors"].append({"id": s.id, "name": s.name, "error": str(e)[:200]})
            finally:
                with _LABDOOR_BULK_LOCK:
                    _LABDOOR_BULK_STATE["done"] += 1
            time.sleep(throttle)
        with _LABDOOR_BULK_LOCK:
            _LABDOOR_BULK_STATE["running"] = False
            _LABDOOR_BULK_STATE["current"] = None
            _LABDOOR_BULK_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"


@admin_image_validation_bp.route("/bulk-resolve-labdoor", methods=["POST"])
@require_editor
def bulk_resolve_labdoor_start():
    """Kick off background resolution of every Labdoor rating's Amazon URL.

    Body: { force?: bool, limit?: int }
    `force=true` re-resolves entries already in the cache."""
    with _LABDOOR_BULK_LOCK:
        if _LABDOOR_BULK_STATE["running"]:
            return jsonify({
                "started": False,
                "message": "A Labdoor resolution job is already running.",
                "state": _LABDOOR_BULK_STATE,
            }), 409

    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))
    limit = data.get("limit")

    # All supplements that have at least one Labdoor rating with a buy_url.
    rows = (db.session.query(Rating.supplement_id)
            .join(Source, Source.id == Rating.source_id)
            .filter(Source.slug == "labdoor",
                    Rating.buy_url.isnot(None))
            .distinct()
            .all())
    supp_ids = [r[0] for r in rows]

    if not force:
        cache = _load_labdoor_cache()
        supp_ids = [sid for sid in supp_ids if str(sid) not in cache]
    if limit:
        supp_ids = supp_ids[:int(limit)]

    if not supp_ids:
        return jsonify({
            "started": False,
            "message": "Nothing to do — every Labdoor rating already has a cached Amazon URL. Pass force=true to re-resolve.",
            "state": _LABDOOR_BULK_STATE,
        })

    _reset_labdoor_bulk_state(force=force, total=len(supp_ids))
    from flask import current_app
    app = current_app._get_current_object()
    threading.Thread(
        target=_labdoor_bulk_worker,
        args=(app, supp_ids, force, 1.0),  # 1s throttle — labdoor's rate-limiter is also ~1s
        daemon=True,
    ).start()
    return jsonify({"started": True, "total": len(supp_ids), "state": _LABDOOR_BULK_STATE})


@admin_image_validation_bp.route("/bulk-resolve-labdoor/status", methods=["GET"])
@login_required
@limiter.exempt
def bulk_resolve_labdoor_status():
    with _LABDOOR_BULK_LOCK:
        return jsonify(dict(_LABDOOR_BULK_STATE))


@admin_image_validation_bp.route("/bulk-resolve-labdoor/stop", methods=["POST"])
@require_editor
def bulk_resolve_labdoor_stop():
    with _LABDOOR_BULK_LOCK:
        if not _LABDOOR_BULK_STATE["running"]:
            return jsonify({"running": False, "message": "Not running."})
        _LABDOOR_BULK_STATE["stop_requested"] = True
    return jsonify({"running": True, "message": "Stop requested — worker will halt after the current product."})


# -------------------- Trustified → Amazon resolve --------------------

_TRUSTIFIED_BULK_LOCK = threading.Lock()
_TRUSTIFIED_BULK_STATE: dict = {
    "running": False, "total": 0, "done": 0, "matched": 0,
    "skipped_no_match": 0, "errors": [], "current": None,
    "started_at": None, "finished_at": None,
    "force": False, "stop_requested": False,
}


def _reset_trustified_bulk_state(force: bool, total: int):
    _TRUSTIFIED_BULK_STATE.update({
        "running": True, "total": total, "done": 0, "matched": 0,
        "skipped_no_match": 0, "errors": [], "current": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": None, "force": force, "stop_requested": False,
    })


@admin_image_validation_bp.route("/resolve-trustified-amazon", methods=["POST"])
@require_editor
def resolve_trustified_amazon():
    """Resolve and cache a single supplement's Trustified → Amazon URL."""
    data = request.get_json(silent=True) or {}
    supp_id = data.get("supplement_id")
    force = bool(data.get("force"))
    if not supp_id:
        abort(400, description="supplement_id is required")
    s = Supplement.query.get(supp_id)
    if not s:
        abort(404, description="supplement not found")

    cache = _load_trustified_cache()
    cached = cache.get(str(supp_id))
    if cached and not force:
        return jsonify({
            "supplement_id": s.id,
            "amazon_url": cached.get("amazon_url"),
            "resolved_at": cached.get("resolved_at"),
            "from_cache": True,
        })

    amazon_url = _resolve_trustified_amazon_for_supplement(s)
    new_entry = _load_trustified_cache().get(str(supp_id), {})
    return jsonify({
        "supplement_id": s.id,
        "amazon_url": amazon_url,
        "resolved_at": new_entry.get("resolved_at"),
        "from_cache": False,
    })


def _trustified_bulk_worker(app, supp_ids: list[int], force: bool, throttle: float):
    with app.app_context():
        for sid in supp_ids:
            with _TRUSTIFIED_BULK_LOCK:
                if _TRUSTIFIED_BULK_STATE["stop_requested"]:
                    break
            s = Supplement.query.get(sid)
            if not s:
                with _TRUSTIFIED_BULK_LOCK:
                    _TRUSTIFIED_BULK_STATE["errors"].append({"id": sid, "name": None, "error": "supplement not found"})
                    _TRUSTIFIED_BULK_STATE["done"] += 1
                continue
            with _TRUSTIFIED_BULK_LOCK:
                _TRUSTIFIED_BULK_STATE["current"] = {"id": s.id, "name": s.name}
            try:
                amazon_url = _resolve_trustified_amazon_for_supplement(s)
                with _TRUSTIFIED_BULK_LOCK:
                    if amazon_url:
                        _TRUSTIFIED_BULK_STATE["matched"] += 1
                    else:
                        _TRUSTIFIED_BULK_STATE["skipped_no_match"] += 1
            except Exception as e:
                with _TRUSTIFIED_BULK_LOCK:
                    _TRUSTIFIED_BULK_STATE["errors"].append({"id": s.id, "name": s.name, "error": str(e)[:200]})
            finally:
                with _TRUSTIFIED_BULK_LOCK:
                    _TRUSTIFIED_BULK_STATE["done"] += 1
            time.sleep(throttle)
        with _TRUSTIFIED_BULK_LOCK:
            _TRUSTIFIED_BULK_STATE["running"] = False
            _TRUSTIFIED_BULK_STATE["current"] = None
            _TRUSTIFIED_BULK_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"


@admin_image_validation_bp.route("/bulk-resolve-trustified", methods=["POST"])
@require_editor
def bulk_resolve_trustified_start():
    """Walk every Trustified-rated supplement and resolve its Amazon URL.
    Includes products without buy_url — we'll try report_url too, since some
    Fail/Expired products still have a Buy Now link the original scraper missed."""
    with _TRUSTIFIED_BULK_LOCK:
        if _TRUSTIFIED_BULK_STATE["running"]:
            return jsonify({
                "started": False,
                "message": "A Trustified resolution job is already running.",
                "state": _TRUSTIFIED_BULK_STATE,
            }), 409

    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))
    limit = data.get("limit")

    rows = (db.session.query(Rating.supplement_id)
            .join(Source, Source.id == Rating.source_id)
            .filter(Source.slug == "trustified",
                    or_(Rating.buy_url.isnot(None),
                        Rating.report_url.isnot(None)))
            .distinct()
            .all())
    supp_ids = [r[0] for r in rows]

    if not force:
        cache = _load_trustified_cache()
        supp_ids = [sid for sid in supp_ids if str(sid) not in cache]
    if limit:
        supp_ids = supp_ids[:int(limit)]

    if not supp_ids:
        return jsonify({
            "started": False,
            "message": "Nothing to do — every Trustified rating already has a cached entry. Pass force=true to re-resolve.",
            "state": _TRUSTIFIED_BULK_STATE,
        })

    _reset_trustified_bulk_state(force=force, total=len(supp_ids))
    from flask import current_app
    app = current_app._get_current_object()
    threading.Thread(
        target=_trustified_bulk_worker,
        args=(app, supp_ids, force, 1.0),  # respects 1s rate-limiter inside the scraper
        daemon=True,
    ).start()
    return jsonify({"started": True, "total": len(supp_ids), "state": _TRUSTIFIED_BULK_STATE})


@admin_image_validation_bp.route("/bulk-resolve-trustified/status", methods=["GET"])
@login_required
@limiter.exempt
def bulk_resolve_trustified_status():
    with _TRUSTIFIED_BULK_LOCK:
        return jsonify(dict(_TRUSTIFIED_BULK_STATE))


@admin_image_validation_bp.route("/bulk-resolve-trustified/stop", methods=["POST"])
@require_editor
def bulk_resolve_trustified_stop():
    with _TRUSTIFIED_BULK_LOCK:
        if not _TRUSTIFIED_BULK_STATE["running"]:
            return jsonify({"running": False, "message": "Not running."})
        _TRUSTIFIED_BULK_STATE["stop_requested"] = True
    return jsonify({"running": True, "message": "Stop requested — worker will halt after the current product."})


@admin_image_validation_bp.route("/scrape-amazon", methods=["POST"])
@require_editor
def scrape_amazon_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        abort(400, description="url is required")
    if not (url.startswith("http://") or url.startswith("https://")):
        abort(400, description="url must be a full http(s) URL")
    if not _is_amazon_url(url):
        abort(400, description="Only Amazon URLs are supported")

    try:
        result = scrape_amazon(url)
    except requests.Timeout:
        abort(504, description="Amazon took too long to respond. Try again.")
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 502
        abort(502, description=f"Amazon returned HTTP {status}.")
    except requests.RequestException as e:
        abort(502, description=f"Failed to fetch Amazon page: {e}")
    except RuntimeError as e:
        abort(422, description=str(e))
    except Exception as e:
        # curl_cffi raises errors outside `requests`'s hierarchy (TLS hiccups,
        # H2 stream resets, etc.), and BS4 can throw on malformed pages.
        # Without this catch we'd return a bare 500 with no detail. Drop the
        # cached per-host curl_cffi session so the next attempt warms a fresh
        # one — many of these failures are transient session-state issues.
        try:
            host = urlparse(url).hostname
            if host:
                _drop_amazon_session(host)
        except Exception:
            pass
        abort(502, description=f"Amazon scrape failed: {type(e).__name__}: {e}")

    if not result["images"]:
        abort(404, description="No images found on this page. It may not be a product listing.")

    return jsonify(result)


# -------------------- Bulk auto-import from verified URLs --------------------
#
# For products that already have a Verified-by-X Amazon URL cached
# (Trustified / Unbox Health / Labdoor), there's no admin decision left to
# make — the URL was hand-curated upstream. This worker walks them all,
# scrapes Amazon, and replaces the gallery + saves Amazon info using the
# same two-phase logic as the manual single-product flow.

_AUTO_IMPORT_LOCK = threading.Lock()
_AUTO_IMPORT_STATE: dict = {
    "running": False, "total": 0, "done": 0,
    "imported": 0,            # gallery successfully replaced
    "imported_ids": [],         # ids the worker just finished — frontend uses
                                # this to auto-mark them validated.
    "skipped_already_done": 0,  # had ≥2 images and amazon_url already set; force=false skipped
    "skipped_no_url": 0,        # no verified URL available
    "errors": [],
    "current": None,
    "started_at": None, "finished_at": None,
    "force": False, "stop_requested": False,
}

# Default priority — Trustified and Unbox are amazon.in (the primary market for
# this catalog), so they win over Labdoor's amazon.com. Override per request.
_DEFAULT_VERIFIED_SOURCE_ORDER = ("trustified", "unbox", "labdoor")


def _reset_auto_import_state(force: bool, total: int):
    _AUTO_IMPORT_STATE.update({
        "running": True, "total": total, "done": 0,
        "imported": 0, "imported_ids": [],
        "skipped_already_done": 0, "skipped_no_url": 0,
        "errors": [], "current": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": None, "force": force, "stop_requested": False,
    })


def _pick_verified_url(supp: Supplement, source_order: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Return (url, source_label) for the first available verified URL on a
    supplement, walking `source_order`. Source labels match the cache keys."""
    for source in source_order:
        if source == "unbox":
            url = _get_unbox_buy_url(supp)
        elif source == "labdoor":
            url = _get_labdoor_amazon_url(supp.id)
        elif source == "trustified":
            url = _get_trustified_amazon_url(supp.id)
        else:
            continue
        if url:
            return url, source
    return None, None


def _import_amazon_listing(supp: Supplement, amazon_url: str) -> dict:
    """Two-phase import mirroring the frontend `importSelected` flow.

    Phase 1: scrape the Amazon page, persist the new SupplementImage rows
    AND patch the supplement (name + amazon_data + clear legacy single image).
    Phase 2: only if phase 1 succeeded, delete the previous gallery rows so
    a partial-create failure can never leave a product image-less.

    Returns a dict with one of these shapes:
      {"ok": True,  "created": int, "deleted": int, "title": str|None}
      {"ok": False, "error": str}
    """
    try:
        result = scrape_amazon(amazon_url)
    except Exception as e:
        return {"ok": False, "error": f"scrape failed: {type(e).__name__}: {str(e)[:140]}"}

    images = result.get("images") or []
    if not images:
        return {"ok": False, "error": "no images on Amazon page"}

    title = result.get("title")
    fetched_iso = datetime.utcnow().isoformat() + "Z"
    existing_image_ids = [img.id for img in supp.images]

    # Phase 1: stage everything in one transaction so we don't leave the
    # supplement half-patched if the image inserts fail.
    try:
        supp.amazon_url = result.get("url") or amazon_url
        supp.amazon_asin = result.get("asin")
        supp.amazon_data = {
            "title": title,
            "brand": result.get("brand"),
            "price": result.get("price"),
            "specs": result.get("specs") or {},
            "about": result.get("about") or [],
            "fetched_at": fetched_iso,
        }
        if title:
            # Supplement.name is varchar(500) — Amazon's marketing titles can
            # exceed that, so clamp defensively.
            supp.name = title[:500]
        supp.image_url = None
        supp.image_path = None

        for idx, img in enumerate(images):
            row = SupplementImage(
                supplement_id=supp.id,
                image_url=img["url"],
                image_type="main" if idx == 0 else "other",
                alt_text=(title or supp.name or "")[:200] or None,
                display_order=idx,
                image_source="amazon",
            )
            db.session.add(row)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"ok": False, "error": f"phase 1 commit failed: {type(e).__name__}: {str(e)[:140]}"}

    # Phase 2: delete the now-stale old gallery rows. If this fails, the new
    # gallery is still in place — leaving stragglers visible until cleaned up.
    deleted = 0
    if existing_image_ids:
        try:
            (SupplementImage.query
             .filter(SupplementImage.id.in_(existing_image_ids))
             .delete(synchronize_session=False))
            db.session.commit()
            deleted = len(existing_image_ids)
        except Exception:
            db.session.rollback()
            # Non-fatal — caller treats this as "imported" with a note.

    return {"ok": True, "created": len(images), "deleted": deleted, "title": title}


def _auto_import_worker(app, supp_ids: list[int], source_order: tuple[str, ...],
                        force: bool, throttle: float):
    with app.app_context():
        for sid in supp_ids:
            with _AUTO_IMPORT_LOCK:
                if _AUTO_IMPORT_STATE["stop_requested"]:
                    break
            s = Supplement.query.get(sid)
            if not s:
                with _AUTO_IMPORT_LOCK:
                    _AUTO_IMPORT_STATE["errors"].append({"id": sid, "name": None, "error": "supplement not found"})
                    _AUTO_IMPORT_STATE["done"] += 1
                continue
            with _AUTO_IMPORT_LOCK:
                _AUTO_IMPORT_STATE["current"] = {"id": s.id, "name": s.name}

            url, _src = _pick_verified_url(s, source_order)
            if not url:
                with _AUTO_IMPORT_LOCK:
                    _AUTO_IMPORT_STATE["skipped_no_url"] += 1
                    _AUTO_IMPORT_STATE["done"] += 1
                continue

            # Skip products already in good shape (≥2 images + Amazon linked)
            # unless the caller asked to force re-import everyone.
            if not force and s.amazon_url and len(s.images or []) >= 2:
                with _AUTO_IMPORT_LOCK:
                    _AUTO_IMPORT_STATE["skipped_already_done"] += 1
                    _AUTO_IMPORT_STATE["done"] += 1
                continue

            try:
                outcome = _import_amazon_listing(s, url)
                if outcome.get("ok"):
                    with _AUTO_IMPORT_LOCK:
                        _AUTO_IMPORT_STATE["imported"] += 1
                        # Cap to 5000 to keep the polling response payload
                        # bounded — the frontend only needs IDs to auto-mark
                        # them validated, so dropping a stray entry past that
                        # ceiling is acceptable.
                        if len(_AUTO_IMPORT_STATE["imported_ids"]) < 5000:
                            _AUTO_IMPORT_STATE["imported_ids"].append(s.id)
                else:
                    with _AUTO_IMPORT_LOCK:
                        _AUTO_IMPORT_STATE["errors"].append({
                            "id": s.id, "name": s.name,
                            "error": outcome.get("error", "unknown"),
                        })
            except Exception as e:
                db.session.rollback()
                with _AUTO_IMPORT_LOCK:
                    _AUTO_IMPORT_STATE["errors"].append({"id": s.id, "name": s.name, "error": str(e)[:200]})
            finally:
                with _AUTO_IMPORT_LOCK:
                    _AUTO_IMPORT_STATE["done"] += 1
            time.sleep(throttle)
        with _AUTO_IMPORT_LOCK:
            _AUTO_IMPORT_STATE["running"] = False
            _AUTO_IMPORT_STATE["current"] = None
            _AUTO_IMPORT_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"


@admin_image_validation_bp.route("/bulk-auto-import", methods=["POST"])
@require_editor
def bulk_auto_import_start():
    """Start the bulk auto-import worker.

    Body:
      - force (bool, default false): re-import even if the product already has
        ≥2 gallery images + an amazon_url linked.
      - source_order (list[str], optional): override the priority list.
        Defaults to ['trustified', 'unbox', 'labdoor'].
      - limit (int, optional): cap how many products to process this run.
    """
    with _AUTO_IMPORT_LOCK:
        if _AUTO_IMPORT_STATE["running"]:
            return jsonify({
                "started": False,
                "message": "An auto-import job is already running.",
                "state": _AUTO_IMPORT_STATE,
            }), 409

    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))
    source_order = tuple(data.get("source_order") or _DEFAULT_VERIFIED_SOURCE_ORDER)
    limit = data.get("limit")

    # Build the candidate set: every supplement with at least one verified URL.
    # Unbox URLs come from Rating.buy_url; Labdoor & Trustified come from disk
    # caches. Union the three sets.
    unbox_supp_ids = {sid for sid, _ in db.session.query(Rating.supplement_id, Rating.buy_url)
                                                .join(Source, Source.id == Rating.source_id)
                                                .filter(Source.slug == "unbox-health",
                                                        Rating.buy_url.isnot(None))
                                                .all()}
    labdoor_cache = _load_labdoor_cache()
    trustified_cache = _load_trustified_cache()
    cached_ids = {int(k) for k, v in labdoor_cache.items() if v.get("amazon_url")}
    cached_ids |= {int(k) for k, v in trustified_cache.items() if v.get("amazon_url")}
    candidate_ids = sorted(unbox_supp_ids | cached_ids)

    if not force:
        # Skip rows that already have ≥2 images AND an amazon_url linked.
        # Done in SQL so we don't load every supplement just to filter.
        if candidate_ids:
            img_count_sq = (select(func.count(SupplementImage.id))
                            .where(SupplementImage.supplement_id == Supplement.id)
                            .scalar_subquery())
            keep_rows = (db.session.query(Supplement.id)
                         .filter(Supplement.id.in_(candidate_ids))
                         .filter(or_(Supplement.amazon_url.is_(None), img_count_sq < 2))
                         .all())
            candidate_ids = [r[0] for r in keep_rows]

    if limit:
        candidate_ids = candidate_ids[:int(limit)]

    if not candidate_ids:
        return jsonify({
            "started": False,
            "message": "Nothing to do — every product with a verified URL already has ≥2 images and a linked Amazon listing. Pass force=true to re-import.",
            "state": _AUTO_IMPORT_STATE,
        })

    _reset_auto_import_state(force=force, total=len(candidate_ids))
    from flask import current_app
    app = current_app._get_current_object()
    threading.Thread(
        target=_auto_import_worker,
        args=(app, candidate_ids, source_order, force, 0.5),
        daemon=True,
    ).start()
    return jsonify({"started": True, "total": len(candidate_ids), "state": _AUTO_IMPORT_STATE})


@admin_image_validation_bp.route("/bulk-auto-import/status", methods=["GET"])
@login_required
@limiter.exempt
def bulk_auto_import_status():
    with _AUTO_IMPORT_LOCK:
        return jsonify(dict(_AUTO_IMPORT_STATE))


@admin_image_validation_bp.route("/bulk-auto-import/stop", methods=["POST"])
@require_editor
def bulk_auto_import_stop():
    with _AUTO_IMPORT_LOCK:
        if not _AUTO_IMPORT_STATE["running"]:
            return jsonify({"running": False, "message": "Not running."})
        _AUTO_IMPORT_STATE["stop_requested"] = True
    return jsonify({"running": True, "message": "Stop requested — worker will halt after the current product."})
