"""Meilisearch integration for HealthMatrix.

Design goals:
  * Optional — when MEILI_URL/MEILI_MASTER_KEY are unset, every helper turns into
    a no-op so the rest of the app keeps working with SQL ILIKE search.
  * Fail-soft — runtime errors talking to Meilisearch are caught and logged; we
    never bubble them up into a user request. The route layer is responsible for
    falling back to SQL when `search()` returns None.
  * Idempotent — `ensure_index_settings()` can be called on every startup; it
    only PATCHes the settings that actually drift from what we want.
  * Reflects visibility rules — only the same supplements that the public listing
    would surface (published, brand+category active, has ≥1 active-source rating
    or no ratings, group primary or ungrouped) get indexed. Hiding a brand or
    deactivating a source must remove products from the index too.

The index is keyed by Supplement.id (numeric primary key, stable across slug
renames). Slugs go in as a regular field so the route layer can hand them to
the frontend.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Iterable

from flask import current_app

from ..extensions import db
from ..models import Supplement, ProductGroup, Brand, Category, Rating, Source

log = logging.getLogger(__name__)

# Cached client per-process. Meilisearch's HTTP client is cheap, but we still
# avoid rebuilding it for every request.
_client_lock = threading.Lock()
_client: Any | None = None
_client_url: str | None = None
_client_key: str | None = None


# --- Index configuration ----------------------------------------------------

# Order = importance. A query word matching `name` outranks the same word in
# `ingredients`. Brand sits second so "Nutrabay creatine" still matches even
# when the supplement name omits the brand.
SEARCHABLE_ATTRIBUTES = [
    "name",
    "brand_name",
    "category_name",
    "product_group_name",
    "variant_label",
    "form",
    "ingredients",
]

FILTERABLE_ATTRIBUTES = [
    "category_slug",
    "brand_slug",
    "source_slugs",      # list — supplement is filterable by any of its rating sources
    "is_featured",
    "is_visible",        # always true in our index, but useful for safety filtering
    "form",
    "has_score",         # bool — useful for "rated only" toggles in the UI
]

SORTABLE_ATTRIBUTES = [
    "aggregate_score",
    "source_count",
    "created_at_ts",     # epoch seconds — Meilisearch sorts numbers, not ISO strings
    "name_lc",           # lowercase name for stable A–Z sort
]

# Ranking rules: `sort` is intentionally first so an explicit sort param from
# the listing endpoint (Top rated, Lowest, Name, Newest) drives the order
# strictly — relevance signals only break ties between docs with equal sort
# keys. This matches user expectation that picking a sort means *that* sort.
# Without an explicit sort (e.g. autocomplete `suggest`), `sort` is a no-op
# and ordering falls through to the relevance pipeline; the trailing
# aggregate_score / source_count tiebreakers still favor well-tested,
# high-scoring products on equal-relevance ties.
RANKING_RULES = [
    "sort",
    "words",
    "typo",
    "proximity",
    "attribute",
    "exactness",
    "aggregate_score:desc",
    "source_count:desc",
]

# Domain synonyms — the catalog uses both clinical and consumer terms freely,
# so we bridge them in the engine instead of asking users to know the alias.
SYNONYMS: dict[str, list[str]] = {
    "vitamin c": ["ascorbic acid"],
    "ascorbic acid": ["vitamin c"],
    "vitamin b12": ["cobalamin", "methylcobalamin"],
    "cobalamin": ["vitamin b12"],
    "vitamin b9": ["folate", "folic acid"],
    "folate": ["vitamin b9", "folic acid"],
    "folic acid": ["vitamin b9", "folate"],
    "vitamin d3": ["cholecalciferol", "vitamin d"],
    "vitamin d": ["vitamin d3", "cholecalciferol"],
    "fish oil": ["omega 3", "omega-3", "epa", "dha"],
    "omega 3": ["fish oil", "omega-3"],
    "omega-3": ["fish oil", "omega 3"],
    "whey": ["whey protein"],
    "protein": ["whey", "casein", "isolate"],
    "creatine": ["creatine monohydrate"],
    "magnesium": ["mg"],
    "calcium": ["ca"],
    "iron": ["fe"],
    "zinc": ["zn"],
    "multivitamin": ["multi vitamin", "multi"],
    "pre-workout": ["pre workout", "preworkout"],
    "pre workout": ["pre-workout", "preworkout"],
}

STOP_WORDS = ["the", "a", "an", "and", "with", "of", "for", "in"]

# Typo tolerance — keep defaults but drop the threshold a bit so 4-char words
# get one-typo allowance (e.g. "whey" → "wey"). Users mistype short brand names.
TYPO_TOLERANCE = {
    "enabled": True,
    "minWordSizeForTypos": {"oneTypo": 4, "twoTypos": 8},
}

# Display: only return what the frontend actually needs. We keep `_formatted`
# (highlights) on the server response — those bytes pay off in the UI.
DISPLAYED_ATTRIBUTES = [
    "id",
    "name",
    "slug",
    "image",
    "brand_name",
    "brand_slug",
    "category_name",
    "category_slug",
    "category_icon",
    "form",
    "size",
    "price",
    "aggregate_score",
    "source_count",
    "review_count",
    "is_featured",
    "product_group_id",
    "product_group_slug",
    "variant_label",
    "ingredients",
    "name_lc",
    "created_at_ts",
    "has_score",
    "is_visible",
    "source_slugs",
]


# --- Client / index access --------------------------------------------------

def _get_config() -> tuple[str, str, str, bool] | None:
    """Read Meilisearch settings off the active Flask app config.

    Returns None when Meilisearch is intentionally disabled (no URL/key set);
    callers treat that as a soft signal to fall back to SQL search.
    """
    try:
        url = (current_app.config.get("MEILI_URL") or "").strip()
        key = (current_app.config.get("MEILI_MASTER_KEY") or "").strip()
        index_uid = (current_app.config.get("MEILI_INDEX") or "supplements").strip()
        auto_sync = bool(current_app.config.get("MEILI_AUTO_SYNC", True))
    except RuntimeError:
        # Outside of an app context — used by CLI scripts that build their own.
        return None
    if not url or not key:
        return None
    return url, key, index_uid, auto_sync


def is_enabled() -> bool:
    return _get_config() is not None


def get_client():
    """Return a cached meilisearch.Client, or None when disabled.

    The import is lazy so the dependency is optional — installs without the
    `meilisearch` package still boot, just without search-engine features.
    """
    global _client, _client_url, _client_key
    cfg = _get_config()
    if cfg is None:
        return None
    url, key, _index, _sync = cfg

    with _client_lock:
        if _client is not None and _client_url == url and _client_key == key:
            return _client
        try:
            from meilisearch import Client  # type: ignore
        except ImportError:
            log.warning("meilisearch package not installed; search engine disabled")
            return None
        _client = Client(url, key, timeout=5)
        _client_url, _client_key = url, key
    return _client


def get_index():
    """Return the index handle, or None when disabled. Does not create the index."""
    client = get_client()
    if client is None:
        return None
    cfg = _get_config()
    if cfg is None:
        return None
    _url, _key, index_uid, _sync = cfg
    try:
        return client.index(index_uid)
    except Exception:
        log.exception("Meilisearch: failed to obtain index handle")
        return None


# --- Document mapping -------------------------------------------------------

def _aggregate_for(s: Supplement) -> tuple[float | None, int]:
    """Pre-computed aggregate_score + source_count, mirroring the SQL trust subquery.

    For grouped products we aggregate across the whole group (matches what the
    public listing/detail page show). Returns (score_or_None, source_count).
    """
    visible_ratings: list[Rating] = []
    if s.product_group_id and s.product_group is not None:
        members = s.product_group.members.all() if s.product_group.members else []
        for v in members:
            visible_ratings.extend(v.visible_ratings)
    else:
        visible_ratings = list(s.visible_ratings)

    # Dedupe by source slug (group merges may produce duplicates across variants).
    seen: dict[str, Rating] = {}
    for r in visible_ratings:
        if not r.source or r.score is None or r.max_score is None or r.max_score <= 0:
            continue
        slug = r.source.slug
        existing = seen.get(slug)
        if existing is None or (r.score / r.max_score) > (existing.score / existing.max_score):
            seen[slug] = r
    if not seen:
        return None, 0
    scores = [r.score / r.max_score * 100.0 for r in seen.values()]
    return round(sum(scores) / len(scores), 1), len(seen)


def _source_slugs_for(s: Supplement) -> list[str]:
    """Active-source slugs that have rated this supplement (or its group)."""
    rows: list[Rating] = []
    if s.product_group_id and s.product_group is not None:
        members = s.product_group.members.all() if s.product_group.members else []
        for v in members:
            rows.extend(v.visible_ratings)
    else:
        rows = list(s.visible_ratings)
    return sorted({r.source.slug for r in rows if r.source and r.source.is_active})


def _is_indexable(s: Supplement) -> bool:
    """Only index supplements the public listing would surface.

    Mirrors `_visible_supplements_query` in routes/supplements.py — soft-deleted /
    unpublished / hidden-brand-or-category / non-primary-variant rows stay out of
    the index. Otherwise users would get matches that 404 or redirect.
    """
    if not s.is_visible:
        return False
    if s.product_group_id and s.product_group is not None:
        primary = s.product_group.primary_supplement_id
        # Broken group with no primary set — fall back to indexing every member,
        # matching the listing query's behavior.
        if primary is not None and primary != s.id:
            return False
    return True


def supplement_to_document(s: Supplement) -> dict | None:
    """Convert a Supplement to the JSON shape we ship to Meilisearch.

    Returns None when the row should not be indexed (hidden / non-primary variant).
    """
    if not _is_indexable(s):
        return None

    score, source_count = _aggregate_for(s)
    group = s.product_group
    # Public-facing name uses the canonical group name when this supplement is
    # the primary of a group — keeps the search result text matching what the
    # card actually displays.
    public_name = group.name if group and group.primary_supplement_id == s.id else s.name

    return {
        "id": s.id,
        "name": public_name,
        "name_lc": (public_name or "").lower(),
        "slug": s.slug,
        "image": s.image,
        "brand_name": s.brand.name if s.brand else None,
        "brand_slug": s.brand.slug if s.brand else None,
        "category_name": s.category.name if s.category else None,
        "category_slug": s.category.slug if s.category else None,
        "category_icon": s.category.icon if s.category else None,
        "form": s.form,
        # Truncate ingredients to keep the document slim; full text isn't useful
        # for ranking past the first few hundred characters.
        "ingredients": (s.ingredients or "")[:500] or None,
        "size": _safe_size(s),
        "price": _safe_price(s),
        "aggregate_score": score if score is not None else 0.0,
        "has_score": score is not None,
        "source_count": source_count,
        "review_count": source_count,
        "source_slugs": _source_slugs_for(s),
        "is_featured": bool(s.is_featured),
        "is_visible": True,
        "product_group_id": s.product_group_id,
        "product_group_slug": group.slug if group else None,
        "product_group_name": group.name if group else None,
        "variant_label": s.variant_label,
        "created_at_ts": int(s.created_at.timestamp()) if s.created_at else 0,
    }


def _safe_size(s: Supplement) -> str | None:
    try:
        from ..models.supplement import _derive_size  # type: ignore
        return _derive_size(s.amazon_data)
    except Exception:
        return None


def _safe_price(s: Supplement) -> str | None:
    try:
        from ..models.supplement import _clean_price  # type: ignore
        return _clean_price((s.amazon_data or {}).get("price"))
    except Exception:
        return None


# --- Index lifecycle --------------------------------------------------------

def ensure_index_settings(force: bool = False) -> bool:
    """Create the index if missing and apply our settings idempotently.

    Returns True on success, False otherwise (engine off / unreachable). Safe to
    call on every app boot — Meilisearch task queue dedupes redundant updates.
    """
    cfg = _get_config()
    if cfg is None:
        return False
    _url, _key, index_uid, _sync = cfg

    client = get_client()
    if client is None:
        return False
    try:
        # Idempotent create — Meilisearch returns the existing index if uid matches
        # without raising. Primary key set explicitly so the very first document
        # add doesn't have to negotiate it.
        client.create_index(index_uid, {"primaryKey": "id"})
    except Exception as e:  # noqa: BLE001
        # Already-exists is fine; anything else we log and continue.
        log.debug("create_index: %s (probably already exists)", e)

    try:
        index = client.index(index_uid)
        # update_settings PATCHes; passing the full block on every boot is fine
        # for a small index. If you grow to many indexes consider hashing and
        # only writing on change.
        index.update_settings({
            "searchableAttributes": SEARCHABLE_ATTRIBUTES,
            "filterableAttributes": FILTERABLE_ATTRIBUTES,
            "sortableAttributes": SORTABLE_ATTRIBUTES,
            "rankingRules": RANKING_RULES,
            "displayedAttributes": DISPLAYED_ATTRIBUTES,
            "synonyms": SYNONYMS,
            "stopWords": STOP_WORDS,
            "typoTolerance": TYPO_TOLERANCE,
            "pagination": {"maxTotalHits": 5000},
        })
        return True
    except Exception:
        log.exception("Meilisearch: failed to apply index settings")
        return False


# --- Sync helpers (single doc + bulk) ---------------------------------------

def upsert_supplement(supplement_id: int) -> None:
    """Refresh one supplement in the index. Removes it if no longer indexable.

    Designed to be called from admin write hooks. Swallows engine errors so a
    flaky search server can't break a save.
    """
    cfg = _get_config()
    if cfg is None:
        return
    if not cfg[3]:  # auto_sync disabled
        return

    s = Supplement.query.get(supplement_id)
    index = get_index()
    if index is None:
        return

    try:
        if s is None:
            index.delete_document(supplement_id)
            return
        doc = supplement_to_document(s)
        if doc is None:
            # No longer eligible (unpublished, demoted to non-primary variant,
            # brand deactivated, etc.) — purge it so search can't surface it.
            index.delete_document(s.id)
            return
        index.add_documents([doc], primary_key="id")
    except Exception:
        log.exception("Meilisearch: upsert_supplement(%s) failed", supplement_id)


def delete_supplement(supplement_id: int) -> None:
    cfg = _get_config()
    if cfg is None or not cfg[3]:
        return
    index = get_index()
    if index is None:
        return
    try:
        index.delete_document(supplement_id)
    except Exception:
        log.exception("Meilisearch: delete_supplement(%s) failed", supplement_id)


def reindex_all(batch_size: int = 200) -> dict:
    """Wipe and rebuild the entire index from the database.

    Used by the admin reindex endpoint and the `flask reindex` CLI command.
    Returns a small report dict for the caller to surface.
    """
    cfg = _get_config()
    if cfg is None:
        return {"ok": False, "reason": "Meilisearch is not configured"}
    _url, _key, index_uid, _auto = cfg

    if not ensure_index_settings():
        return {"ok": False, "reason": "Failed to configure index"}
    index = get_index()
    if index is None:
        return {"ok": False, "reason": "Failed to obtain index handle"}

    try:
        # Atomic-feeling rebuild: delete all then bulk-add. Meilisearch handles
        # this as a queue of tasks; readers see the old data until the new tasks
        # complete. For our small catalog this is < 1 second.
        index.delete_all_documents()
    except Exception:
        log.exception("Meilisearch: delete_all_documents failed during reindex")
        return {"ok": False, "reason": "delete_all_documents failed"}

    total_seen = 0
    total_indexed = 0
    batch: list[dict] = []
    last_task_uid = None

    # Single eager query — pre-load relations to avoid N+1 inside the doc mapper.
    rows: Iterable[Supplement] = (
        Supplement.query
        .join(Brand, Brand.id == Supplement.brand_id)
        .join(Category, Category.id == Supplement.category_id)
        .filter(
            Supplement.is_published.is_(True),
            Brand.is_active.is_(True),
            Category.is_active.is_(True),
        )
        .order_by(Supplement.id.asc())
        .yield_per(batch_size)
    )

    for s in rows:
        total_seen += 1
        doc = supplement_to_document(s)
        if doc is None:
            continue
        batch.append(doc)
        total_indexed += 1
        if len(batch) >= batch_size:
            try:
                last_task_uid = index.add_documents(batch, primary_key="id").task_uid
            except Exception:
                log.exception("Meilisearch: batch add failed")
                return {"ok": False, "reason": "Batch add failed", "indexed": total_indexed}
            batch = []
    if batch:
        try:
            last_task_uid = index.add_documents(batch, primary_key="id").task_uid
        except Exception:
            log.exception("Meilisearch: tail batch add failed")
            return {"ok": False, "reason": "Tail batch add failed", "indexed": total_indexed}

    return {
        "ok": True,
        "scanned": total_seen,
        "indexed": total_indexed,
        "skipped": total_seen - total_indexed,
        "last_task_uid": last_task_uid,
    }


# --- Search -----------------------------------------------------------------

def search(
    *,
    q: str,
    page: int = 1,
    per_page: int = 12,
    category_slug: str | None = None,
    source_slug: str | None = None,
    brand_slug: str | None = None,
    sort: str = "top",
    highlight: bool = False,
) -> dict | None:
    """Run a Meilisearch query, returning a dict that's drop-in compatible with
    the SQL listing response (`items`, `page`, `per_page`, `total`, `total_pages`).

    Returns None when search is disabled or fails — caller falls back to SQL.
    """
    index = get_index()
    if index is None:
        return None

    page = max(1, int(page))
    per_page = max(1, min(50, int(per_page)))

    filters: list[str] = ["is_visible = true"]
    if category_slug:
        filters.append(f'category_slug = "{_esc(category_slug)}"')
    if brand_slug:
        filters.append(f'brand_slug = "{_esc(brand_slug)}"')
    if source_slug:
        filters.append(f'source_slugs = "{_esc(source_slug)}"')

    sort_param: list[str] | None = None
    if sort == "name":
        sort_param = ["name_lc:asc"]
    elif sort == "newest":
        sort_param = ["created_at_ts:desc"]
    elif sort == "lowest":
        # Mirror the SQL behavior: rated-but-low rises to the top.
        sort_param = ["aggregate_score:asc", "source_count:asc"]
    else:
        # 'top' — strict score order, matching the SQL path. Sent explicitly
        # so the `sort` ranking rule (now first in RANKING_RULES) wins over
        # search-relevance signals; otherwise a partial-match high-rated
        # product would lose to a strong-match low-rated one even though the
        # user picked "Top rated".
        sort_param = ["aggregate_score:desc", "source_count:desc"]

    payload: dict[str, Any] = {
        "filter": filters,
        "page": page,
        "hitsPerPage": per_page,
        "attributesToRetrieve": ["*"],
    }
    if sort_param:
        payload["sort"] = sort_param
    if highlight:
        payload["attributesToHighlight"] = ["name", "brand_name", "ingredients"]
        payload["highlightPreTag"] = "<mark>"
        payload["highlightPostTag"] = "</mark>"

    try:
        res = index.search(q or "", payload)
    except Exception:
        log.exception("Meilisearch: search failed; falling back to SQL")
        return None

    items = [_format_hit(h, with_highlight=highlight) for h in res.get("hits", [])]
    # `hitsPerPage` mode returns totalHits/totalPages directly.
    total = res.get("totalHits", res.get("estimatedTotalHits", len(items)))
    total_pages = res.get("totalPages") or max(1, (total + per_page - 1) // per_page)

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "engine": "meilisearch",
        "processing_ms": res.get("processingTimeMs"),
        "query": res.get("query", q),
    }


def suggest(q: str, limit: int = 8) -> list[dict] | None:
    """Lightweight typeahead — fewer fields, prefix-friendly via Meilisearch.

    Returns None when search is disabled / failed (caller falls back to SQL).
    """
    if not q or len(q.strip()) < 1:
        return []
    index = get_index()
    if index is None:
        return None
    try:
        res = index.search(q, {
            "filter": ["is_visible = true"],
            "limit": max(1, min(20, int(limit))),
            "attributesToRetrieve": [
                "id", "slug", "name", "brand_name", "category_name",
                "category_icon", "category_slug", "aggregate_score", "image",
            ],
            "attributesToHighlight": ["name", "brand_name"],
            "highlightPreTag": "<mark>",
            "highlightPostTag": "</mark>",
        })
    except Exception:
        log.exception("Meilisearch: suggest failed")
        return None

    out: list[dict] = []
    for h in res.get("hits", []):
        formatted = h.get("_formatted") or {}
        out.append({
            "id": h.get("id"),
            "slug": h.get("slug"),
            "name": h.get("name"),
            "name_highlighted": formatted.get("name") or h.get("name"),
            "brand": h.get("brand_name"),
            "brand_highlighted": formatted.get("brand_name") or h.get("brand_name"),
            "category": {
                "name": h.get("category_name"),
                "slug": h.get("category_slug"),
                "icon": h.get("category_icon"),
            } if h.get("category_slug") else None,
            "aggregate_score": h.get("aggregate_score"),
            "image": h.get("image"),
        })
    return out


# --- Internal utilities ----------------------------------------------------

def _esc(value: str) -> str:
    """Escape a string for use inside a Meilisearch filter literal.

    Meilisearch double-quoted strings allow embedded backslashes/quotes when
    escaped — we play it safe and reject the small set of characters that would
    let a hostile slug break out (slugs are sanitized server-side, but defense
    in depth is cheap)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_hit(hit: dict, *, with_highlight: bool) -> dict:
    """Shape a Meilisearch hit so the React listing/card components can render it
    without changes — same field names as Supplement.to_public_dict.
    """
    item = {
        "id": hit.get("id"),
        "slug": hit.get("slug"),
        "name": hit.get("name"),
        "image": hit.get("image"),
        "brand": (
            {"name": hit.get("brand_name"), "slug": hit.get("brand_slug")}
            if hit.get("brand_slug") else None
        ),
        "category": (
            {
                "name": hit.get("category_name"),
                "slug": hit.get("category_slug"),
                "icon": hit.get("category_icon"),
            }
            if hit.get("category_slug") else None
        ),
        "form": hit.get("form"),
        "size": hit.get("size"),
        "price": hit.get("price"),
        "ingredients": hit.get("ingredients"),
        "is_featured": hit.get("is_featured", False),
        "aggregate_score": hit.get("aggregate_score") if hit.get("has_score") else None,
        "review_count": hit.get("review_count", 0),
        "product_group_id": hit.get("product_group_id"),
        "variant_label": hit.get("variant_label"),
    }
    if with_highlight and hit.get("_formatted"):
        item["_highlighted"] = {
            "name": hit["_formatted"].get("name"),
            "brand_name": hit["_formatted"].get("brand_name"),
            "ingredients": hit["_formatted"].get("ingredients"),
        }
    return item
