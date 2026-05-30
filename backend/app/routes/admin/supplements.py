import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from flask import Blueprint, request, jsonify, abort
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import or_, desc, asc, func, select, nullslast

from ...extensions import db
from ...extensions import limiter
from ...models import Supplement, Brand, Category, Rating, Source, SupplementAlias
from ...admin_auth import login_required, require_editor, require_superadmin, log_action, diff_changes
from ...utils import slugify, unique_slug
from ...services import search_index
from .image_validation import scrape_amazon, _is_amazon_url, _drop_amazon_session


admin_supplements_bp = Blueprint("admin_supplements", __name__)


WRITABLE_FIELDS = (
    "name", "description", "image_url", "image_path", "image_source",
    "ingredients", "serving_size", "form", "price_range", "dsld_id", "upc",
    "brand_id", "category_id", "is_featured", "is_published",
    "amazon_url", "amazon_asin", "amazon_data",
    "product_group_id", "variant_label",
)


def _admin_dict(s: Supplement) -> dict:
    """Like Supplement.to_dict, but includes admin-only fields (is_published, raw FKs, slug)."""
    base = s.to_dict(include_ratings=False)
    base.update({
        "is_published": s.is_published,
        "brand_id": s.brand_id,
        "category_id": s.category_id,
        "product_group_id": s.product_group_id,
        "variant_label": s.variant_label,
        "image_url": s.image_url,
        "image_path": s.image_path,
        "amazon_url": s.amazon_url,
        "amazon_asin": s.amazon_asin,
        "amazon_data": s.amazon_data,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    })
    return base


@admin_supplements_bp.route("", methods=["GET"])
@login_required
def list_supplements():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 25)), 1), 200)
    search = (request.args.get("q") or "").strip()
    brand_id = request.args.get("brand_id")
    category_id = request.args.get("category_id")
    is_published = request.args.get("is_published")
    is_featured = request.args.get("is_featured")
    sort = request.args.get("sort", "newest")

    query = Supplement.query.join(Brand, Brand.id == Supplement.brand_id).join(
        Category, Category.id == Supplement.category_id
    )
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Supplement.name.ilike(like),
            Supplement.slug.ilike(like),
            Brand.name.ilike(like),
            Supplement.upc.ilike(like) if Supplement.upc is not None else False,
        ))
    if brand_id:
        query = query.filter(Supplement.brand_id == int(brand_id))
    if category_id:
        query = query.filter(Supplement.category_id == int(category_id))
    if is_published in ("true", "false"):
        query = query.filter(Supplement.is_published.is_(is_published == "true"))
    if is_featured in ("true", "false"):
        query = query.filter(Supplement.is_featured.is_(is_featured == "true"))

    direction = request.args.get("dir", "").lower()
    # Active-source rating aggregates (subqueries — keep the main query JOIN-free for them).
    score_subq = (select(func.avg(Rating.score / Rating.max_score * 100.0))
                  .join(Source, Source.id == Rating.source_id)
                  .where(Rating.supplement_id == Supplement.id,
                         Source.is_active.is_(True),
                         Rating.score.isnot(None))
                  .scalar_subquery())
    review_subq = (select(func.count(Rating.id))
                   .join(Source, Source.id == Rating.source_id)
                   .where(Rating.supplement_id == Supplement.id,
                          Source.is_active.is_(True))
                   .scalar_subquery())

    sortable = {
        "name": Supplement.name,
        "slug": Supplement.slug,
        "brand": Brand.name,
        "category": Category.name,
        "is_published": Supplement.is_published,
        "is_featured": Supplement.is_featured,
        "score": score_subq,
        "review_count": review_subq,
        "created_at": Supplement.created_at,
        "updated_at": Supplement.updated_at,
    }

    if sort in sortable:
        col = sortable[sort]
        order = nullslast(desc(col) if direction == "desc" else asc(col))
        query = query.order_by(order, Supplement.id)
    elif sort == "oldest":
        query = query.order_by(asc(Supplement.created_at), Supplement.id)
    elif sort == "updated":
        query = query.order_by(desc(Supplement.updated_at), Supplement.id)
    elif sort == "newest" or not sort:
        query = query.order_by(desc(Supplement.created_at), Supplement.id)
    else:
        query = query.order_by(desc(Supplement.created_at), Supplement.id)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "items": [_admin_dict(s) for s in items],
        "page": page, "per_page": per_page, "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


@admin_supplements_bp.route("/<int:supp_id>", methods=["GET"])
@login_required
def get_supplement(supp_id):
    s = Supplement.query.get_or_404(supp_id)
    data = _admin_dict(s)
    data["ratings"] = [r.to_dict() for r in s.ratings.all()]
    return jsonify(data)


@admin_supplements_bp.route("", methods=["POST"])
@require_editor
def create_supplement():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, description="name is required")

    brand_id = data.get("brand_id")
    category_id = data.get("category_id")
    if not brand_id or not Brand.query.get(brand_id):
        abort(400, description="brand_id is required and must reference an existing brand")
    if not category_id or not Category.query.get(category_id):
        abort(400, description="category_id is required and must reference an existing category")

    base_slug = slugify((data.get("slug") or "").strip() or name)
    s = Supplement(name=name, slug=unique_slug(Supplement, base_slug),
                   brand_id=brand_id, category_id=category_id)
    for field in WRITABLE_FIELDS:
        if field in ("name", "brand_id", "category_id"):
            continue
        if field in data:
            setattr(s, field, data[field])
    db.session.add(s)
    db.session.commit()
    search_index.upsert_supplement(s.id)
    log_action("CREATE", entity_type="supplement", entity_id=s.id,
               summary=f"Created supplement '{s.name}'",
               changes={"name": s.name, "slug": s.slug, "brand_id": s.brand_id, "category_id": s.category_id})
    return jsonify(_admin_dict(s)), 201


@admin_supplements_bp.route("/<int:supp_id>", methods=["PATCH", "PUT"])
@require_editor
def update_supplement(supp_id):
    s = Supplement.query.get_or_404(supp_id)
    data = request.get_json(silent=True) or {}
    before = {k: getattr(s, k) for k in WRITABLE_FIELDS + ("slug",)}

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            abort(400, description="name cannot be empty")
        s.name = new_name
    if "slug" in data and data["slug"]:
        new_slug = unique_slug(Supplement, slugify(data["slug"]), exclude_id=s.id)
        if new_slug != s.slug:
            # Preserve the old slug as an alias so existing URLs keep resolving.
            existing_alias = SupplementAlias.query.filter_by(slug=s.slug).first()
            if not existing_alias:
                db.session.add(SupplementAlias(slug=s.slug, supplement_id=s.id))
            s.slug = new_slug
    if "brand_id" in data:
        if not Brand.query.get(data["brand_id"]):
            abort(400, description="brand_id does not reference an existing brand")
        s.brand_id = data["brand_id"]
    if "category_id" in data:
        if not Category.query.get(data["category_id"]):
            abort(400, description="category_id does not reference an existing category")
        s.category_id = data["category_id"]
    for field in ("description", "image_url", "image_path", "image_source",
                  "ingredients", "serving_size", "form", "price_range",
                  "dsld_id", "upc", "is_featured", "is_published",
                  "amazon_url", "amazon_asin", "amazon_data",
                  "variant_label"):
        if field in data:
            setattr(s, field, data[field])

    db.session.commit()
    search_index.upsert_supplement(s.id)
    after = {k: getattr(s, k) for k in WRITABLE_FIELDS + ("slug",)}
    log_action("UPDATE", entity_type="supplement", entity_id=s.id,
               summary=f"Updated supplement '{s.name}'", changes=diff_changes(before, after))
    return jsonify(_admin_dict(s))


@admin_supplements_bp.route("/<int:supp_id>", methods=["DELETE"])
@require_superadmin
def delete_supplement(supp_id):
    s = Supplement.query.get_or_404(supp_id)
    name = s.name
    db.session.delete(s)
    db.session.commit()
    search_index.delete_supplement(supp_id)
    log_action("DELETE", entity_type="supplement", entity_id=supp_id,
               summary=f"Deleted supplement '{name}'")
    return jsonify({"ok": True})


@admin_supplements_bp.route("/<int:supp_id>/refresh-price", methods=["POST"])
@require_editor
def refresh_price(supp_id):
    """Re-scrape the supplement's Amazon listing and update just the price.

    Other amazon_data fields (specs, about, brand, etc.) are left alone so this
    cheap operation doesn't disturb image/title work an admin has already vetted.
    Returns the previous and current price so the UI can show what changed."""
    s = Supplement.query.get_or_404(supp_id)
    url = (s.amazon_url or "").strip()
    if not url:
        abort(400, description="This supplement has no amazon_url set.")
    if not _is_amazon_url(url):
        abort(400, description="Stored amazon_url is not an Amazon URL.")

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
    except Exception as e:  # noqa: BLE001
        abort(502, description=f"Amazon scrape failed: {type(e).__name__}: {e}")

    new_price = result.get("price")
    if not new_price:
        abort(422, description="Amazon page didn't expose a price (item may be unavailable).")

    data = dict(s.amazon_data or {})
    old_price = data.get("price")
    data["price"] = new_price
    data["price_fetched_at"] = datetime.utcnow().isoformat() + "Z"
    s.amazon_data = data
    # JSONB / JSON dict-mutations don't always bubble up to SQLAlchemy's dirty
    # tracker — flag it explicitly so the UPDATE actually fires.
    flag_modified(s, "amazon_data")
    db.session.commit()
    search_index.upsert_supplement(s.id)
    log_action("UPDATE", entity_type="supplement", entity_id=s.id,
               summary=f"Refreshed Amazon price for '{s.name}'",
               changes={"price": {"before": old_price, "after": new_price}})
    return jsonify({
        "ok": True,
        "supplement_id": s.id,
        "previous_price": old_price,
        "price": new_price,
        "fetched_at": data["price_fetched_at"],
    })


# -------------------- Bulk Amazon price refresh --------------------
#
# Re-scrapes every supplement that has an `amazon_url` and updates only
# `amazon_data.price` (+ `price_fetched_at`). Mirrors the bulk-worker pattern
# used in image_validation.py: single-process in-memory state + polling.

_BULK_PRICE_LOCK = threading.Lock()
_BULK_PRICE_STATE: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "updated": 0,          # price changed vs. previous value
    "unchanged": 0,        # scrape succeeded but price matched what we already had
    "skipped_no_price": 0, # Amazon page returned no price (item unavailable)
    "errors": [],          # [{id, name, error}]
    "current": None,       # {id, name}
    "started_at": None,
    "finished_at": None,
    "stop_requested": False,
    "concurrency": 1,      # active parallelism for the in-flight run (for the UI)
}


def _reset_bulk_price_state(total: int, concurrency: int) -> None:
    _BULK_PRICE_STATE.update({
        "running": True, "total": total, "done": 0,
        "updated": 0, "unchanged": 0, "skipped_no_price": 0,
        "errors": [], "current": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "finished_at": None, "stop_requested": False,
        "concurrency": concurrency,
    })


def _process_one_price(sid: int, throttle: float) -> None:
    """Scrape one supplement's Amazon listing and update only its price.
    Runs inside a thread that's already inside the app context. Each thread
    has its own thread-local SQLAlchemy session, so commits don't interfere.

    Mutates `_BULK_PRICE_STATE` under the shared lock for every outcome bucket.
    Sleeps `throttle` seconds at the end so each worker self-paces — combined
    with N concurrent workers this gives an effective rate of N/throttle req/s."""
    s = Supplement.query.get(sid)
    if not s:
        with _BULK_PRICE_LOCK:
            _BULK_PRICE_STATE["errors"].append({"id": sid, "name": None, "error": "supplement not found"})
            _BULK_PRICE_STATE["done"] += 1
        return

    with _BULK_PRICE_LOCK:
        # Show the most recently started product as "current". Multiple
        # threads are running, so this naturally cycles — that's OK; the
        # value is just a "what is the worker doing" hint for the UI.
        _BULK_PRICE_STATE["current"] = {"id": s.id, "name": s.name}

    try:
        result = scrape_amazon(s.amazon_url)
        new_price = result.get("price")
        if not new_price:
            with _BULK_PRICE_LOCK:
                _BULK_PRICE_STATE["skipped_no_price"] += 1
        else:
            data = dict(s.amazon_data or {})
            old_price = data.get("price")
            data["price"] = new_price
            data["price_fetched_at"] = datetime.utcnow().isoformat() + "Z"
            s.amazon_data = data
            flag_modified(s, "amazon_data")
            db.session.commit()
            search_index.upsert_supplement(s.id)
            with _BULK_PRICE_LOCK:
                if old_price == new_price:
                    _BULK_PRICE_STATE["unchanged"] += 1
                else:
                    _BULK_PRICE_STATE["updated"] += 1
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        # Drop *this thread's* per-host session so the next attempt gets a
        # fresh one — cookie/TLS state often gets wedged after a single 503.
        # Other threads keep their own warm sessions.
        try:
            from urllib.parse import urlparse
            host = urlparse(s.amazon_url or "").hostname
            if host:
                _drop_amazon_session(host)
        except Exception:
            pass
        with _BULK_PRICE_LOCK:
            _BULK_PRICE_STATE["errors"].append({
                "id": s.id, "name": s.name,
                "error": f"{type(e).__name__}: {str(e)[:160]}",
            })
    finally:
        # Always free the SQLAlchemy session for this thread so the worker
        # doesn't accumulate stale identity-map state across iterations.
        db.session.remove()
        with _BULK_PRICE_LOCK:
            _BULK_PRICE_STATE["done"] += 1
    if throttle > 0:
        time.sleep(throttle)


def _bulk_price_worker(app, supp_ids: list[int], throttle: float, concurrency: int):
    """Orchestrate parallel price refreshes. Each task fans out to a thread in
    the pool; threads share `_BULK_PRICE_STATE` under a lock.

    `concurrency` caps how many Amazon fetches happen in parallel. Real-world
    safe values: 2–4 for amazon.in (which is sensitive to bot traffic). Higher
    values shorten the run but raise CAPTCHA risk."""
    def _runner(sid: int):
        # Each worker thread pushes its own app context so db.session and
        # current_app work. The ThreadPoolExecutor reuses threads, so the
        # context push is cheap after the first task per thread.
        with app.app_context():
            with _BULK_PRICE_LOCK:
                if _BULK_PRICE_STATE["stop_requested"]:
                    # Still count this as "done" so the progress total adds up;
                    # the row simply wasn't attempted.
                    _BULK_PRICE_STATE["done"] += 1
                    return
            _process_one_price(sid, throttle)

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="bulk-price") as pool:
        # Submit them all; the pool caps real concurrency to max_workers.
        # `list(...)` forces evaluation so we wait for completion below.
        futures = [pool.submit(_runner, sid) for sid in supp_ids]
        for f in futures:
            try:
                f.result()
            except Exception:
                # Per-task errors are already captured in state. A future
                # raising here means the wrapper itself broke — surface it
                # under the generic errors bucket so the run can complete.
                with _BULK_PRICE_LOCK:
                    _BULK_PRICE_STATE["errors"].append({"id": None, "name": None, "error": "worker crashed"})

    with _BULK_PRICE_LOCK:
        _BULK_PRICE_STATE["running"] = False
        _BULK_PRICE_STATE["current"] = None
        _BULK_PRICE_STATE["finished_at"] = datetime.utcnow().isoformat() + "Z"


@admin_supplements_bp.route("/bulk-refresh-price", methods=["POST"])
@require_editor
def bulk_refresh_price_start():
    """Kick off background price refresh across the catalog.

    Body params (all optional):
      - brand_id (int): limit to one brand.
      - category_id (int): limit to one category.
      - limit (int): hard cap on supplements processed this run.
      - stale_only (bool, default false): skip supplements whose price was
        refreshed within the last 24h. Lets the admin re-run safely without
        re-hitting fresh rows.
      - throttle (float, default 1.0): seconds to sleep between rows. Lower
        only when you know the catalog is small enough that Amazon won't
        rate-limit.
    """
    with _BULK_PRICE_LOCK:
        if _BULK_PRICE_STATE["running"]:
            return jsonify({
                "started": False,
                "message": "A bulk price refresh is already running.",
                "state": dict(_BULK_PRICE_STATE),
            }), 409

    data = request.get_json(silent=True) or {}
    brand_id = data.get("brand_id")
    category_id = data.get("category_id")
    limit = data.get("limit")
    stale_only = bool(data.get("stale_only"))
    try:
        throttle = float(data.get("throttle") or 1.0)
    except (TypeError, ValueError):
        throttle = 1.0
    throttle = max(0.2, min(throttle, 10.0))
    try:
        concurrency = int(data.get("concurrency") or 4)
    except (TypeError, ValueError):
        concurrency = 4
    # Cap at 8 — beyond that, amazon.in starts CAPTCHA-ing aggressively from
    # a single IP regardless of session warming.
    concurrency = max(1, min(concurrency, 8))

    query = Supplement.query.filter(
        Supplement.amazon_url.isnot(None),
        Supplement.amazon_url != "",
    )
    if brand_id:
        query = query.filter(Supplement.brand_id == int(brand_id))
    if category_id:
        query = query.filter(Supplement.category_id == int(category_id))
    query = query.order_by(Supplement.id)
    if limit:
        query = query.limit(int(limit))

    supp_ids = [row.id for row in query.with_entities(Supplement.id).all()]

    if stale_only and supp_ids:
        # Cheap, in-Python filter — the freshness timestamp lives in the JSON
        # blob, which is awkward to filter SQL-side across SQLite + Postgres.
        cutoff = datetime.utcnow().timestamp() - 24 * 3600
        kept: list[int] = []
        for sid in supp_ids:
            s = Supplement.query.get(sid)
            ts_raw = (s.amazon_data or {}).get("price_fetched_at") if s and s.amazon_data else None
            if not ts_raw:
                kept.append(sid)
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.rstrip("Z")).timestamp()
            except ValueError:
                kept.append(sid)
                continue
            if ts < cutoff:
                kept.append(sid)
        supp_ids = kept

    if not supp_ids:
        return jsonify({
            "started": False,
            "message": "No supplements match — nothing to refresh.",
            "state": dict(_BULK_PRICE_STATE),
        })

    # Concurrency can't exceed the workload — pointless to spin up 8 threads
    # for 3 supplements, and the pool wouldn't use them anyway.
    effective_concurrency = min(concurrency, len(supp_ids))
    _reset_bulk_price_state(total=len(supp_ids), concurrency=effective_concurrency)
    from flask import current_app
    app = current_app._get_current_object()
    threading.Thread(
        target=_bulk_price_worker,
        args=(app, supp_ids, throttle, effective_concurrency),
        daemon=True,
    ).start()
    return jsonify({
        "started": True,
        "total": len(supp_ids),
        "concurrency": effective_concurrency,
        "state": dict(_BULK_PRICE_STATE),
    })


@admin_supplements_bp.route("/bulk-refresh-price/status", methods=["GET"])
@login_required
@limiter.exempt
def bulk_refresh_price_status():
    # Polled every 2s by the admin UI while a job runs — exempt from the
    # global hourly limit so a long-running job doesn't lock the admin out.
    with _BULK_PRICE_LOCK:
        return jsonify(dict(_BULK_PRICE_STATE))


@admin_supplements_bp.route("/bulk-refresh-price/stop", methods=["POST"])
@require_editor
def bulk_refresh_price_stop():
    with _BULK_PRICE_LOCK:
        if not _BULK_PRICE_STATE["running"]:
            return jsonify({"running": False, "message": "Not running."})
        _BULK_PRICE_STATE["stop_requested"] = True
    return jsonify({"running": True, "message": "Stop requested — worker will halt after the current product."})
