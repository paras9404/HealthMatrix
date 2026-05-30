"""Admin tool: paste a URL from one of our rating sources (Trustified / Labdoor /
Unbox Health) and the server scrapes it, lets the admin review, then upserts the
Supplement + Rating + Brand in one click. Mirrors the manual-paste flow of
image_validation.py but for product+rating ingestion instead of Amazon images.

Endpoints
  POST /scrape   → detect source by hostname, run the matching scraper, return a
                   unified preview payload + a category suggestion + whether the
                   product already exists in our catalog.
  POST /import   → upsert Brand, Supplement, Rating from the same URL plus any
                   admin overrides (name, brand, category_id, score, verdict, …).
                   Downloads the product image to /static when missing.

Bulk-sync endpoints (per-source listing-page → diff → background import):
  POST /discover           → fetch every live product URL for one source, diff
                             against our DB by Rating.report_url + slug fallback,
                             return what's new + (for visibility) what's retired.
  POST /bulk-import        → kick off a background worker that scrapes each
                             missing URL and runs the same per-product upsert
                             the CLI scripts use (import_unboxhealth.import_product,
                             import_trustified.import_product, …).
  GET  /bulk-import/status → in-memory progress (single-replica only).
  POST /bulk-import/stop   → cooperative cancel after the current item.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime
from urllib.parse import urlparse

import requests
from flask import Blueprint, abort, current_app, jsonify, request

from ...admin_auth import login_required, log_action, require_editor
from ...extensions import db
from ...models import Brand, Category, Rating, Source, Supplement
from ...services.data_fetcher import download_image, generate_svg_fallback
from ...services.labdoor_scraper import (
    LabdoorProduct,
    fetch_product as fetch_labdoor,
    fetch_product_urls as fetch_labdoor_urls,
    map_category as map_labdoor_category,
)
from ...services.trustified_scraper import (
    TrustifiedProduct,
    fetch_product as fetch_trustified,
    fetch_product_urls as fetch_trustified_urls,
)
from ...services.unbox_scraper import (
    UnboxProduct,
    fetch_product as fetch_unbox,
    fetch_product_urls as fetch_unbox_urls,
    map_category as map_unbox_category,
)
from ...utils import slugify, unique_slug


admin_source_import_bp = Blueprint("admin_source_import", __name__)


# Reuse the canonical keyword→category map from import_trustified.py so the
# admin "Discover Trustified" preview agrees with the CLI bulk importer. The
# import path for trustified is sys.path-aware (run.py adds backend/ to the
# path), so this absolute import resolves at request time.
from import_trustified import map_category as _map_trustified_category  # noqa: E402


def _detect_source(url: str) -> str | None:
    """Return our Source.slug for a known scrape-target URL, or None."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    if "trustified" in host:
        return "trustified"
    if "labdoor.com" in host:
        return "labdoor"
    if "unboxhealth" in host:
        return "unbox-health"
    return None


# -------------------- Scrape adapters --------------------
#
# Each adapter calls the existing service-layer scraper and converts the
# dataclass it returns into our unified preview payload. Keep them tiny — any
# heavy logic belongs back in services/.

def _trustified_to_preview(p: TrustifiedProduct) -> dict:
    is_pass = "pass" in (p.verdict or "").lower()
    cat_slug = _map_trustified_category(p.category, p.product_name or "", p.slug)
    pname = p.product_name or p.title or p.slug
    full_name = (
        f"{p.brand} {pname}".strip()
        if p.brand and (pname or "").lower().find((p.brand or "").lower()) == -1
        else pname
    )
    if full_name and len(full_name) > 180:
        full_name = full_name[:180].rsplit(" ", 1)[0] + "…"

    return {
        "source": {"slug": "trustified", "name": "Trustified"},
        "url": p.url,
        "name": full_name,
        "brand": p.brand,
        "image_url": p.image_url,
        "score": 100.0 if is_pass else (0.0 if p.verdict else None),
        "max_score": 100.0,
        "grade": None,
        "verdict": p.verdict,
        "summary": _trustified_summary(p),
        "report_url": p.url,
        "buy_url": p.buy_url if is_pass else None,
        "tested_at": _parse_iso_date(p.date_published).isoformat() if _parse_iso_date(p.date_published) else None,
        "batch_no": p.batch_no,
        "manufacturing_date": p.manufacturing_date,
        "expiration_date": p.expiration_date,
        "tested_by": p.tested_by,
        "raw_category": p.category,
        "category_slug_suggestion": cat_slug,
    }


def _trustified_summary(p: TrustifiedProduct) -> str:
    bits = []
    if p.tested_by:
        bits.append(f"Tested by {p.tested_by}.")
    if p.batch_no:
        bits.append(f"Batch {p.batch_no}.")
    if p.verdict:
        bits.append(f"Status: {p.verdict}.")
    return " ".join(bits) or "Trustified pass/fail report."


def _labdoor_to_preview(p: LabdoorProduct) -> dict:
    cat_slug = map_labdoor_category(p.category_slug)
    pname = p.product_name or p.title or p.slug
    full_name = (
        pname if (p.brand and (p.brand.lower() in (pname or "").lower()))
        else (f"{p.brand} {pname}".strip() if p.brand else pname)
    )
    if full_name and len(full_name) > 180:
        full_name = full_name[:180].rsplit(" ", 1)[0] + "…"

    if p.is_upcoming:
        verdict = "Upcoming"
    elif p.is_expired:
        verdict = "Expired"
    elif p.is_certified:
        verdict = "Certified"
    elif p.score is not None and p.score >= 60:
        verdict = "Pass"
    elif p.score is not None:
        verdict = "Fail"
    else:
        verdict = None

    bits = []
    if p.score is not None:
        bits.append(f"Quality score: {p.score}/100 (Grade {p.grade}).")
    if p.is_certified:
        bits.append("Labdoor Certified.")
    if p.is_expired:
        bits.append("Test report expired.")
    if p.is_upcoming:
        bits.append("Upcoming review.")
    summary = " ".join(bits) or "Labdoor review."

    return {
        "source": {"slug": "labdoor", "name": "Labdoor"},
        "url": p.url,
        "name": full_name,
        "brand": p.brand,
        "image_url": p.image_url,
        "score": p.score,
        "max_score": 100.0,
        "grade": p.grade,
        "verdict": verdict,
        "summary": summary,
        "report_url": p.url,
        "buy_url": p.buy_url if (p.is_certified or (p.score and p.score >= 60)) else None,
        "tested_at": None,
        "batch_no": None,
        "manufacturing_date": None,
        "expiration_date": None,
        "tested_by": None,
        "raw_category": p.category_name or p.category_slug,
        "category_slug_suggestion": cat_slug,
    }


def _unbox_to_preview(p: UnboxProduct) -> dict:
    cat_slug = map_unbox_category(p.category_slug)
    pname = p.name or p.slug
    full_name = (
        pname if (p.brand and (p.brand.lower() in (pname or "").lower()))
        else (f"{p.brand} {pname}".strip() if p.brand else pname)
    )
    if full_name and len(full_name) > 180:
        full_name = full_name[:180].rsplit(" ", 1)[0] + "…"

    if p.grade in ("A+", "A"):
        verdict = "Excellent"
    elif p.grade in ("B+", "B"):
        verdict = "Good"
    elif p.grade == "C":
        verdict = "Average"
    elif p.grade in ("D", "F"):
        verdict = "Poor"
    else:
        verdict = None

    bits = []
    if p.grade:
        bits.append(f"Grade {p.grade}.")
    if p.label_accuracy is not None:
        bits.append(f"Label Accuracy: {p.label_accuracy}/10.")
    if p.non_toxicity is not None:
        bits.append(f"Non-Toxicity: {p.non_toxicity}/10.")
    if p.is_previous:
        bits.append("(Previously rated.)")
    summary = " ".join(bits) or "Unbox Health lab-tested rating."

    return {
        "source": {"slug": "unbox-health", "name": "Unbox Health"},
        "url": p.url,
        "name": full_name,
        "brand": p.brand,
        "image_url": p.image_url,
        # Convert UnboxHealth's 0-10 native scale → 0-100 to match the others.
        "score": round(p.normalized_score, 2) if p.normalized_score is not None else None,
        "max_score": 100.0,
        "grade": p.grade,
        "verdict": verdict,
        "summary": summary,
        "report_url": p.url,
        "buy_url": p.buy_url if (p.grade or "").upper().startswith(("A", "B")) else None,
        "tested_at": None,
        "batch_no": None,
        "manufacturing_date": None,
        "expiration_date": None,
        "tested_by": None,
        "raw_category": p.category_name or p.category_slug,
        "category_slug_suggestion": cat_slug,
    }


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find_existing_supplement(preview: dict) -> Supplement | None:
    """Try to locate a supplement that already represents this listing.

    Matches:
      1. By Rating.report_url == this URL (most reliable).
      2. By slug derived from the source's URL (covers the common case where
         the import script created the supplement with that slug).
    """
    url = preview["url"]
    rating = Rating.query.filter_by(report_url=url).first()
    if rating:
        return rating.supplement

    # Derive a likely slug the same way the import scripts do.
    parts = url.rstrip("/").split("/")
    src_slug = preview["source"]["slug"]
    if src_slug == "unbox-health" and len(parts) >= 2:
        candidate = parts[-2]
    else:
        candidate = parts[-1] if parts else ""
    if candidate:
        s = Supplement.query.filter_by(slug=slugify(candidate)).first()
        if s:
            return s
    return None


# -------------------- Routes --------------------


@admin_source_import_bp.route("/scrape", methods=["POST"])
@login_required
def scrape_source_url():
    """Scrape a product page from one of our supported sources and return a
    preview the admin can review before importing."""
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        abort(400, description="url is required")
    if not (url.startswith("http://") or url.startswith("https://")):
        abort(400, description="url must be a full http(s) URL")

    src_slug = _detect_source(url)
    if not src_slug:
        abort(400, description=(
            "Unsupported URL — paste a link from trustified.in, labdoor.com, or unboxhealth.in."
        ))

    if Source.query.filter_by(slug=src_slug).first() is None:
        abort(500, description=f"Source '{src_slug}' is not seeded in the database.")

    try:
        if src_slug == "trustified":
            scraped = fetch_trustified(url)
            if not scraped:
                abort(502, description="Failed to fetch the Trustified page.")
            preview = _trustified_to_preview(scraped)
        elif src_slug == "labdoor":
            scraped = fetch_labdoor(url)
            if not scraped:
                abort(502, description="Failed to fetch the Labdoor page.")
            preview = _labdoor_to_preview(scraped)
        else:
            scraped = fetch_unbox(url)
            if not scraped:
                abort(502, description="Failed to fetch the Unbox Health page.")
            preview = _unbox_to_preview(scraped)
    except requests.RequestException as e:
        abort(502, description=f"Fetch failed: {e}")

    # Resolve the category suggestion to an actual Category row so the UI can
    # preselect the dropdown without making a second round-trip.
    suggestion = preview.get("category_slug_suggestion")
    cat_obj = None
    if suggestion:
        c = Category.query.filter_by(slug=suggestion).first()
        if c:
            cat_obj = {"id": c.id, "slug": c.slug, "name": c.name}
    preview["category_suggestion"] = cat_obj

    # Detect existing rows so the UI can show "Will update" instead of "Will create".
    existing_supp = _find_existing_supplement(preview)
    existing = None
    if existing_supp:
        rating = Rating.query.filter_by(
            supplement_id=existing_supp.id,
            source_id=Source.query.filter_by(slug=src_slug).first().id,
        ).first()
        existing = {
            "supplement_id": existing_supp.id,
            "supplement_name": existing_supp.name,
            "supplement_slug": existing_supp.slug,
            "image_url": existing_supp.image,
            "rating_id": rating.id if rating else None,
            "rating_score": rating.score if rating else None,
            "rating_verdict": rating.verdict if rating else None,
        }
    preview["existing"] = existing

    return jsonify(preview)


def _get_or_create_brand(name: str, default_country: str | None) -> Brand:
    slug = slugify(name)
    brand = Brand.query.filter_by(slug=slug).first()
    if brand:
        return brand
    brand = Brand(name=name.strip(), slug=slug, country=default_country)
    db.session.add(brand)
    db.session.flush()
    return brand


@admin_source_import_bp.route("/import", methods=["POST"])
@require_editor
def import_source_url():
    """Upsert Brand, Supplement, and Rating from a previously-scraped source URL.

    Body:
      url, source_slug, name, brand_name, category_id, image_url,
      score, max_score, verdict, summary, report_url, buy_url,
      tested_at (YYYY-MM-DD), batch_no, manufacturing_date, expiration_date, tested_by
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    source_slug = (data.get("source_slug") or "").strip()
    name = (data.get("name") or "").strip()
    brand_name = (data.get("brand_name") or "").strip()
    category_id = data.get("category_id")
    if not url or not source_slug or not name or not brand_name or not category_id:
        abort(400, description="url, source_slug, name, brand_name, and category_id are required")

    source = Source.query.filter_by(slug=source_slug).first()
    if not source:
        abort(400, description=f"Unknown source '{source_slug}'")

    category = Category.query.get(category_id)
    if not category:
        abort(400, description=f"Unknown category_id {category_id}")

    # Default country for auto-created brands — matches what the bulk importers do.
    default_country = {"trustified": "India", "labdoor": "USA", "unbox-health": "India"}.get(source_slug)
    brand = _get_or_create_brand(brand_name, default_country)

    # Resolve target supplement: pre-existing row from rating.report_url, or a new one
    # whose slug is derived from the source's URL slug (matches the bulk importers'
    # behavior so we don't create a parallel row).
    parts = url.rstrip("/").split("/")
    if source_slug == "unbox-health" and len(parts) >= 2:
        url_slug_seed = parts[-2]
    else:
        url_slug_seed = parts[-1] if parts else name
    desired_slug = slugify(url_slug_seed or name)

    supp = (
        Rating.query.filter_by(report_url=url).first().supplement
        if Rating.query.filter_by(report_url=url).first()
        else Supplement.query.filter_by(slug=desired_slug).first()
    )
    is_new = supp is None
    if is_new:
        supp = Supplement(
            slug=unique_slug(Supplement, desired_slug),
            name=name,
            brand=brand,
            category=category,
            description=name,
            is_published=True,
        )
        db.session.add(supp)
    else:
        supp.name = name
        supp.brand = brand
        supp.category = category
    db.session.flush()

    # Image — only download when we don't already have one. Keeping admin-curated
    # gallery images intact is more important than getting the latest source image.
    image_url = (data.get("image_url") or "").strip()
    if image_url and not supp.image_path and not supp.images:
        result = download_image(image_url, supp.slug, source_label=source_slug)
        if result:
            supp.image_path, supp.image_source = result
        else:
            supp.image_path = generate_svg_fallback(
                slug=supp.slug, brand=brand.name, name=name,
                category_icon=category.icon or "vitamin",
            )
            supp.image_source = "generated"
    elif not supp.image_path and not supp.images:
        supp.image_path = generate_svg_fallback(
            slug=supp.slug, brand=brand.name, name=name,
            category_icon=category.icon or "vitamin",
        )
        supp.image_source = "generated"

    # Rating upsert.
    rating = Rating.query.filter_by(supplement_id=supp.id, source_id=source.id).first()
    rating_is_new = rating is None

    tested_at_raw = data.get("tested_at")
    tested_at: date | None = None
    if tested_at_raw:
        try:
            tested_at = date.fromisoformat(tested_at_raw)
        except (TypeError, ValueError):
            tested_at = _parse_iso_date(str(tested_at_raw))

    rating_data = {
        "score": data.get("score"),
        "max_score": data.get("max_score") or 100.0,
        "verdict": data.get("verdict") or None,
        "summary": data.get("summary") or None,
        "report_url": (data.get("report_url") or url).strip(),
        "buy_url": (data.get("buy_url") or None) or None,
        "tested_at": tested_at,
        "batch_no": data.get("batch_no") or None,
        "manufacturing_date": data.get("manufacturing_date") or None,
        "expiration_date": data.get("expiration_date") or None,
        "tested_by": data.get("tested_by") or None,
    }

    if rating:
        for k, v in rating_data.items():
            setattr(rating, k, v)
    else:
        rating = Rating(supplement=supp, source=source, **rating_data)
        db.session.add(rating)

    db.session.commit()

    log_action(
        "CREATE" if is_new else "UPDATE",
        entity_type="supplement",
        entity_id=supp.id,
        summary=f"{'Created' if is_new else 'Updated'} '{supp.name}' from {source.name}",
        changes={"source": source.slug, "url": url, "rating_new": rating_is_new},
    )

    return jsonify({
        "ok": True,
        "supplement_created": is_new,
        "rating_created": rating_is_new,
        "supplement": {
            "id": supp.id,
            "name": supp.name,
            "slug": supp.slug,
            "image": supp.image,
            "brand": supp.brand.name if supp.brand else None,
            "category": supp.category.name if supp.category else None,
        },
        "rating": {
            "id": rating.id,
            "score": rating.score,
            "verdict": rating.verdict,
            "report_url": rating.report_url,
            "buy_url": rating.buy_url,
        },
    })


# -------------------- Bulk discover + sync --------------------
#
# Per-source pipeline:
#   1. /discover  → list every live product URL on the source's catalog page,
#                   diff against ratings.report_url, return missing + retired.
#   2. /bulk-import → kick off a background thread that scrapes each missing
#                     URL and runs the same per-product upsert the CLI importers
#                     use (so behavior — category mapping, food filters, image
#                     downloads — stays identical to running `make import-*`).
#   3. /bulk-import/status → poll progress.
#   4. /bulk-import/stop   → cooperative cancel after the current item.
#
# State is single-process, in-memory, single-concurrency — adequate for this
# admin tool. For multi-replica deployments this would need a real job queue.

_SOURCES_META = {
    # source_slug → (display name, listing URL the admin sees, per-URL slug
    # extractor for retired/match logic).
    "unbox-health": {
        "name": "Unbox Health",
        "listing": "https://www.unboxhealth.in/explore/products-list",
        "discover": fetch_unbox_urls,
        # Unbox URLs end with /<slug>/<uuid> — the slug is the second-to-last segment.
        "slug_from_url": lambda url: (
            slugify(url.rstrip("/").split("/")[-2])
            if len(url.rstrip("/").split("/")) >= 2 else None
        ),
    },
    "trustified": {
        "name": "Trustified",
        "listing": "https://www.trustified.in/passandfail",
        "discover": fetch_trustified_urls,
        "slug_from_url": lambda url: slugify(url.rstrip("/").split("/")[-1]),
    },
    "labdoor": {
        "name": "Labdoor",
        "listing": "https://labdoor.com/rankings",
        "discover": fetch_labdoor_urls,
        "slug_from_url": lambda url: slugify(url.rstrip("/").split("/")[-1]),
    },
}


def _diff_against_db(source_slug: str, live_urls: list[str]) -> dict:
    """Match live URLs against existing ratings. Two-pass: exact report_url
    first, then a slug fallback for cases where the rating row was written
    with a slightly different canonical URL."""
    source = Source.query.filter_by(slug=source_slug).first()
    if not source:
        abort(500, description=f"Source '{source_slug}' is not seeded.")

    meta = _SOURCES_META[source_slug]
    slug_of = meta["slug_from_url"]

    ratings = Rating.query.filter_by(source_id=source.id).all()
    db_urls = {r.report_url for r in ratings if r.report_url}
    db_slug_to_rating = {}
    for r in ratings:
        if not r.report_url:
            continue
        s = slug_of(r.report_url)
        if s:
            db_slug_to_rating.setdefault(s, r)

    missing: list[dict] = []
    matched_url = 0
    matched_slug = 0
    for url in live_urls:
        if url in db_urls:
            matched_url += 1
            continue
        s = slug_of(url)
        if s and s in db_slug_to_rating:
            matched_slug += 1
            continue
        missing.append({"url": url, "slug": s})

    # Reverse direction: which DB ratings no longer appear on the live list?
    live_url_set = set(live_urls)
    live_slug_set = {slug_of(u) for u in live_urls if slug_of(u)}
    retired: list[dict] = []
    for r in ratings:
        if not r.report_url:
            continue
        if r.report_url in live_url_set:
            continue
        s = slug_of(r.report_url)
        if s and s in live_slug_set:
            continue
        retired.append({
            "rating_id": r.id,
            "supplement_id": r.supplement_id,
            "supplement_name": r.supplement.name if r.supplement else None,
            "report_url": r.report_url,
        })

    return {
        "source": source_slug,
        "source_name": meta["name"],
        "listing_url": meta["listing"],
        "total_live": len(live_urls),
        "matched_in_db": matched_url + matched_slug,
        "matched_by_url": matched_url,
        "matched_by_slug_only": matched_slug,
        "missing_count": len(missing),
        "missing": missing,
        "retired_count": len(retired),
        "retired": retired[:50],   # cap for payload size; report_count carries truth
    }


@admin_source_import_bp.route("/discover", methods=["POST"])
@login_required
def discover_source():
    """Fetch the live product catalog for one source and diff against our DB."""
    data = request.get_json(silent=True) or {}
    source_slug = (data.get("source") or "").strip()
    if source_slug not in _SOURCES_META:
        abort(400, description=f"Unknown source '{source_slug}'. Expected one of: {list(_SOURCES_META)}.")

    meta = _SOURCES_META[source_slug]
    try:
        # Discovery for Labdoor walks ~40 ranking pages and is slow (~30-60s).
        # Trustified + Unbox hit a single sitemap/listing page and finish in <5s.
        live_urls = meta["discover"]()
    except requests.RequestException as e:
        abort(502, description=f"Failed to load {meta['name']} catalog: {e}")

    return jsonify(_diff_against_db(source_slug, live_urls))


# -------- Bulk worker --------

_BULK_LOCK = threading.Lock()
_BULK_STATE: dict = {
    "running": False,
    "source": None,
    "total": 0,
    "done": 0,
    "new": 0,
    "updated": 0,
    "skipped": 0,        # pipeline filter (food / non-supplement / no-brand / no-score)
    "skipped_items": [], # [{slug, name, url, reason, …}] up to 500 entries
    "fetch_fail": 0,
    "errors": [],         # [{url, slug, error}]
    "current": None,      # {url, slug}
    "started_at": None,
    "finished_at": None,
    "stop_requested": False,
}


def _reset_bulk_state(source_slug: str, total: int) -> None:
    _BULK_STATE.update({
        "running": True,
        "source": source_slug,
        "total": total,
        "done": 0,
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_items": [],
        "fetch_fail": 0,
        "errors": [],
        "current": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": None,
        "stop_requested": False,
    })


def _bulk_worker(app, source_slug: str, urls: list[str]) -> None:
    """Background worker. Lazy-imports the CLI script's `import_product` so
    behavior matches `make import-<source>` exactly — same category mapping,
    food filter, brand auto-create, image download, slug strategy."""
    # Lazy import so the route module loads cleanly even when these CLI scripts
    # aren't on PYTHONPATH (e.g. unit tests).
    if source_slug == "unbox-health":
        from import_unboxhealth import import_product as cli_import
        fetcher = fetch_unbox
    elif source_slug == "trustified":
        from import_trustified import import_product as cli_import
        fetcher = fetch_trustified
    elif source_slug == "labdoor":
        from import_labdoor import import_product as cli_import
        fetcher = fetch_labdoor
    else:
        # Worker should never be started with an invalid slug; guard anyway.
        with _BULK_LOCK:
            _BULK_STATE["running"] = False
            _BULK_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"
            _BULK_STATE["errors"].append({"url": None, "error": f"unknown source {source_slug}"})
        return

    with app.app_context():
        source = Source.query.filter_by(slug=source_slug).first()
        if not source:
            with _BULK_LOCK:
                _BULK_STATE["running"] = False
                _BULK_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"
                _BULK_STATE["errors"].append({"url": None, "error": f"source {source_slug} not seeded"})
            return

        # Mirror the per-CLI stats keys but collapse all skip reasons into one
        # `skipped` counter for the UI — admins don't need the breakdown live.
        for i, url in enumerate(urls, 1):
            with _BULK_LOCK:
                if _BULK_STATE["stop_requested"]:
                    break
                _BULK_STATE["current"] = {
                    "url": url,
                    "slug": _SOURCES_META[source_slug]["slug_from_url"](url),
                }
            try:
                prod = fetcher(url)
                if not prod:
                    with _BULK_LOCK:
                        _BULK_STATE["fetch_fail"] += 1
                else:
                    # Per-product stats dict. `skipped_items` lets the
                    # importer record details (slug, name, url, reason) for
                    # any product it had to skip, so the admin UI can list
                    # them for manual processing.
                    stats = {
                        "new": 0, "updated": 0,
                        "skipped_non_supplement": 0,
                        "skipped_no_brand": 0,
                        "skipped_empty": 0,
                        "skipped_food": 0,            # only used by trustified
                        "error": 0, "fetch_fail": 0,
                        "skipped_items": [],
                    }
                    cli_import(prod, source, stats)
                    with _BULK_LOCK:
                        _BULK_STATE["new"] += stats.get("new", 0)
                        _BULK_STATE["updated"] += stats.get("updated", 0)
                        _BULK_STATE["skipped"] += (
                            stats.get("skipped_non_supplement", 0)
                            + stats.get("skipped_no_brand", 0)
                            + stats.get("skipped_empty", 0)
                            + stats.get("skipped_food", 0)
                        )
                        # Cap to 500 so the response payload stays bounded.
                        for item in stats.get("skipped_items", []) or []:
                            if len(_BULK_STATE["skipped_items"]) >= 500:
                                break
                            _BULK_STATE["skipped_items"].append(item)
                        if stats.get("error", 0):
                            _BULK_STATE["errors"].append({"url": url, "error": "import_product reported error"})
                # Commit periodically to keep transaction small + flush progress.
                if i % 10 == 0:
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                with _BULK_LOCK:
                    _BULK_STATE["errors"].append({"url": url, "error": str(e)[:200]})
            finally:
                with _BULK_LOCK:
                    _BULK_STATE["done"] += 1
            # Modest pacing — the per-source scrapers already sleep 1s between
            # same-host requests, so this is mostly defense-in-depth.
            time.sleep(0.1)

        # Final commit + finalize state.
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        with _BULK_LOCK:
            _BULK_STATE["running"] = False
            _BULK_STATE["current"] = None
            _BULK_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"


@admin_source_import_bp.route("/bulk-import", methods=["POST"])
@require_editor
def bulk_import_start():
    """Kick off the background sync worker for one source.

    Body: {source: "unbox-health"|"trustified"|"labdoor", urls?: [...]}
    If `urls` is omitted, the server re-runs discovery and imports every
    URL not already matched in our DB.
    """
    with _BULK_LOCK:
        if _BULK_STATE["running"]:
            return jsonify({
                "started": False,
                "message": "A bulk sync is already running.",
                "state": _BULK_STATE,
            }), 409

    data = request.get_json(silent=True) or {}
    source_slug = (data.get("source") or "").strip()
    if source_slug not in _SOURCES_META:
        abort(400, description=f"Unknown source '{source_slug}'.")

    urls: list[str] = data.get("urls") or []
    if not urls:
        # Re-run discovery so we never import URLs the admin didn't intend
        # (e.g., racing with another admin who imported some between discover
        # and confirm).
        try:
            live_urls = _SOURCES_META[source_slug]["discover"]()
        except requests.RequestException as e:
            abort(502, description=f"Failed to refresh catalog: {e}")
        diff = _diff_against_db(source_slug, live_urls)
        urls = [m["url"] for m in diff["missing"]]

    if not urls:
        return jsonify({
            "started": False,
            "message": "Nothing to import — every live URL is already in the DB.",
            "state": _BULK_STATE,
        })

    _reset_bulk_state(source_slug, len(urls))
    app = current_app._get_current_object()
    threading.Thread(
        target=_bulk_worker,
        args=(app, source_slug, urls),
        daemon=True,
    ).start()
    log_action(
        "BULK_IMPORT_START",
        entity_type="source",
        entity_id=source_slug,
        summary=f"Started bulk sync from {_SOURCES_META[source_slug]['name']} ({len(urls)} URLs)",
    )
    return jsonify({"started": True, "total": len(urls), "state": _BULK_STATE})


@admin_source_import_bp.route("/bulk-import/status", methods=["GET"])
@login_required
def bulk_import_status():
    with _BULK_LOCK:
        return jsonify(dict(_BULK_STATE))


@admin_source_import_bp.route("/bulk-import/stop", methods=["POST"])
@require_editor
def bulk_import_stop():
    with _BULK_LOCK:
        if not _BULK_STATE["running"]:
            return jsonify({"running": False, "message": "Not running."})
        _BULK_STATE["stop_requested"] = True
    return jsonify({"running": True, "message": "Stop requested — worker will halt after the current item."})
