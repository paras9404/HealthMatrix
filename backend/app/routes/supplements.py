import re

from flask import Blueprint, request, jsonify, abort, current_app
from sqlalchemy import or_, desc, asc, func, exists, and_
from sqlalchemy.orm import aliased

from ..extensions import db
from ..models import Supplement, Category, Brand, Source, Rating, SupplementAlias, ProductGroup
from ..services import search_index


def _parse_price(amazon_data) -> float | None:
    """Pull a numeric price out of the Amazon snapshot. Strings like 'INR2,749.00'
    become 2749.0; missing or unparseable values return None. Used by the price
    sort handlers — JSONB/Text storage and locale-specific formatting make pure-SQL
    sorting awkward across SQLite + Postgres, so the listing path does this in
    Python after fetching the visible window."""
    if not amazon_data:
        return None
    raw = amazon_data.get("price") if isinstance(amazon_data, dict) else None
    if not raw:
        return None
    digits = re.sub(r"[^0-9.]", "", str(raw))
    if not digits or digits == ".":
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _trust_subquery():
    """Per-supplement aggregate: avg normalized score + count of active-source ratings.

    Used by the listing's default 'top' sort so that highly-rated supplements tested by
    multiple labs surface first. Only active-source ratings with non-null scores count."""
    return (
        db.session.query(
            Rating.supplement_id.label("supplement_id"),
            func.avg(Rating.score / Rating.max_score * 100.0).label("avg_score"),
            func.count(Rating.id).label("source_count"),
        )
        .join(Source, Source.id == Rating.source_id)
        .filter(Source.is_active.is_(True), Rating.score.isnot(None))
        .group_by(Rating.supplement_id)
        .subquery()
    )


def _has_visible_rating_filter():
    """SQL filter: supplement either has no ratings OR has ≥1 rating from an active source.

    Hides supplements whose only ratings come from sources an admin has marked inactive
    — without those, the card would show '0 labs' which is misleading.

    Uses aliased Rating/Source so the EXISTS subquery doesn't auto-correlate against
    outer queries that also reference these tables (e.g., the featured endpoint joins
    Rating and Source — without aliases, SQLAlchemy strips them from the subquery FROM
    and raises InvalidRequestError)."""
    R = aliased(Rating)
    S = aliased(Source)
    has_any_rating = exists().where(R.supplement_id == Supplement.id)
    has_active_source_rating = exists().where(and_(
        R.supplement_id == Supplement.id,
        R.source_id == S.id,
        S.is_active.is_(True),
    ))
    return or_(~has_any_rating, has_active_source_rating)


def _visible_supplements_query():
    """Base query: only supplements that are published, have active brand+category,
    and either are unrated or have ≥1 rating from an active source.

    Also collapses ProductGroup siblings: when a supplement belongs to a group with
    a designated primary, only the primary surfaces in listings — the public site
    sees one card per product line, and the detail endpoint merges sibling ratings
    onto it via Supplement.to_public_dict().
    """
    PG = aliased(ProductGroup)
    return (Supplement.query
            .join(Brand, Brand.id == Supplement.brand_id)
            .join(Category, Category.id == Supplement.category_id)
            .outerjoin(PG, PG.id == Supplement.product_group_id)
            .filter(Supplement.is_published.is_(True),
                    Brand.is_active.is_(True),
                    Category.is_active.is_(True),
                    _has_visible_rating_filter(),
                    or_(
                        Supplement.product_group_id.is_(None),
                        # Broken group with no primary set — fall back to showing
                        # all members so we never accidentally hide products.
                        PG.primary_supplement_id.is_(None),
                        PG.primary_supplement_id == Supplement.id,
                    )))

supplements_bp = Blueprint("supplements", __name__)


@supplements_bp.route("", methods=["GET"])
def list_supplements():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 12)), 1), 50)
    search = request.args.get("q", "").strip()
    category_slug = request.args.get("category", "").strip()
    brand_slug = request.args.get("brand", "").strip()
    source_slug = request.args.get("source", "").strip()
    sort = request.args.get("sort", "top")
    featured_only = request.args.get("featured", "").lower() == "true"
    highlight = request.args.get("highlight", "").lower() == "true"

    # Meilisearch path: only when the user actually typed a query. Empty-query
    # browse keeps using SQL because (a) our trust ranking is the source of
    # truth there and (b) we don't want to introduce a behavior split when the
    # engine is unreachable. `featured_only` also stays SQL-side; we don't index
    # an `is_featured` ranking field worth deviating for. Price sorts also bypass
    # the engine — the index doesn't carry a numeric price attribute, so we let
    # SQL handle them so the order is correct regardless of index state.
    price_sort = sort in ("price_asc", "price_desc")
    if search and not featured_only and not price_sort and search_index.is_enabled():
        result = search_index.search(
            q=search,
            page=page,
            per_page=per_page,
            category_slug=category_slug or None,
            source_slug=source_slug or None,
            brand_slug=brand_slug or None,
            sort=sort,
            highlight=highlight,
        )
        if result is not None:
            return jsonify(result)
        # Engine errored — fall through to SQL so the user still gets results.

    query = _visible_supplements_query()

    if search:
        like = f"%{search}%"
        # Match against the group's canonical name too — admins may rename a group
        # to something the variants' raw names don't contain (e.g., "Halaup Omega-3"
        # group with a "Haleup Vegan Omega 3" variant). Without this, searching the
        # group name returns nothing because the variant rows don't carry that text.
        group_name_match = Supplement.product_group_id.in_(
            db.session.query(ProductGroup.id).filter(ProductGroup.name.ilike(like))
        )
        query = query.filter(or_(
            Supplement.name.ilike(like),
            Brand.name.ilike(like),
            Supplement.ingredients.ilike(like),
            group_name_match,
        ))

    if category_slug:
        query = query.filter(Category.slug == category_slug)

    if brand_slug:
        query = query.filter(Brand.slug == brand_slug)

    if source_slug:
        # Only supplements that have a rating from this active source.
        # Use EXISTS instead of JOIN+DISTINCT — DISTINCT conflicts with our trust sort's
        # ORDER BY on aggregated subquery columns under Postgres.
        source_match = exists().where(and_(
            Rating.supplement_id == Supplement.id,
            Rating.source_id == Source.id,
            Source.slug == source_slug,
            Source.is_active.is_(True),
        ))
        query = query.filter(source_match)

    if featured_only:
        query = query.filter(Supplement.is_featured.is_(True))

    if sort == "name":
        query = query.order_by(asc(Supplement.name))
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
    elif sort == "newest":
        query = query.order_by(desc(Supplement.created_at))
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
    elif sort in ("price_asc", "price_desc"):
        # Price lives inside the amazon_data JSON blob as a locale-formatted string
        # ('INR2,749.00'). Rather than juggle dialect-specific JSON+regex extraction
        # we fetch the filtered set and sort in Python — category listings cap at a
        # few hundred rows so this stays well within budget. Unpriced products are
        # pushed to the end regardless of direction so they never crowd the top.
        all_items = query.all()
        keyed = [(_parse_price(s.amazon_data), s) for s in all_items]
        priced = [(p, s) for p, s in keyed if p is not None]
        unpriced = [s for p, s in keyed if p is None]
        priced.sort(key=lambda x: x[0], reverse=(sort == "price_desc"))
        ordered = [s for _, s in priced] + unpriced
        total = len(ordered)
        items = ordered[(page - 1) * per_page : page * per_page]
    elif sort == "lowest":
        # "Worst rated first" — useful when filtering by Fail/Expired, etc.
        ts = _trust_subquery()
        query = (query
                 .outerjoin(ts, ts.c.supplement_id == Supplement.id)
                 .order_by(asc(func.coalesce(ts.c.avg_score, 0)),
                           asc(func.coalesce(ts.c.source_count, 0))))
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
    else:
        # Default: 'top' — highest-scoring products first, with lab count as the
        # tiebreaker so that among equally-rated products the more-tested one ranks
        # higher. Unrated products drift to the very end.
        ts = _trust_subquery()
        avg = func.coalesce(ts.c.avg_score, 0)
        cnt = func.coalesce(ts.c.source_count, 0)

        query = (query
                 .outerjoin(ts, ts.c.supplement_id == Supplement.id)
                 .order_by(desc(cnt > 0),  # rated products first
                           desc(avg),       # then highest score
                           desc(cnt),       # then most-tested first (tiebreaker)
                           desc(Supplement.is_featured),
                           desc(Supplement.created_at)))
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        "items": [s.to_public_dict() for s in items],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


@supplements_bp.route("/<slug>", methods=["GET"])
def get_supplement(slug):
    """Look up by current slug, then fall back to slug aliases (preserves URL stability
    across deduplication merges — old slugs continue to resolve to the canonical row).

    When the matched row is a NON-PRIMARY variant of a product group, serve the
    primary's data instead — keeps the URL bookmarkable while showing the canonical
    grouped card. The response includes a `canonical_slug` hint so the frontend can
    history.replaceState() to the primary's URL if it wants to."""
    supplement = Supplement.query.filter_by(slug=slug).first()
    if not supplement:
        alias = SupplementAlias.query.filter_by(slug=slug).first()
        if alias:
            supplement = Supplement.query.get(alias.supplement_id)
    if not supplement or not supplement.is_visible:
        abort(404, description=f"Supplement '{slug}' not found")

    # If this supplement is a non-primary variant in a group, hand back the primary
    # so the public detail page renders the canonical product card. Falls back to
    # the requested supplement if the group has no primary set (broken state).
    canonical = supplement
    group = supplement.product_group
    if group and group.primary_supplement_id and group.primary_supplement_id != supplement.id:
        primary = Supplement.query.get(group.primary_supplement_id)
        if primary and primary.is_visible:
            canonical = primary

    payload = canonical.to_public_dict(include_ratings=True)
    payload["canonical_slug"] = canonical.slug
    return jsonify(payload)


@supplements_bp.route("/featured", methods=["GET"])
def featured():
    """Top-rated supplements: only products with ≥1 rating from an active source,
    ranked by their average normalized score (computed in SQL). No 'Not yet rated' cards.

    `include_ratings=true` embeds each card's lab breakdown — used by the home page
    hero so it doesn't have to follow up with a per-slug detail fetch."""
    limit = min(int(request.args.get("limit", 6)), 20)
    include_ratings = request.args.get("include_ratings", "").lower() == "true"
    from sqlalchemy import func
    from ..models import Rating

    avg_score = (func.avg(Rating.score / Rating.max_score * 100.0)).label("avg_score")
    rating_count = func.count(Rating.id).label("rating_count")

    rows = (
        _visible_supplements_query()
        .join(Rating, Rating.supplement_id == Supplement.id)
        .join(Source, Source.id == Rating.source_id)
        .filter(Source.is_active.is_(True), Rating.score.isnot(None))
        .group_by(Supplement.id, Brand.id, Category.id)
        .order_by(desc(Supplement.is_featured), desc(avg_score), desc(rating_count))
        .limit(limit)
        .all()
    )
    return jsonify({"items": [s.to_public_dict(include_ratings=include_ratings) for s in rows]})


@supplements_bp.route("/search/suggest", methods=["GET"])
def search_suggest():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"items": []})

    # Prefer Meilisearch — it does prefix matching + typo tolerance + highlights.
    if search_index.is_enabled():
        items = search_index.suggest(q, limit=8)
        if items is not None:
            # Map to the shape the existing Navbar typeahead expects, but also
            # forward the new `*_highlighted` strings for nicer rendering.
            return jsonify({"items": [
                {
                    "id": h.get("id"),
                    "slug": h.get("slug"),
                    "name": h.get("name"),
                    "brand": h.get("brand"),
                    "category": h.get("category"),
                    "aggregate_score": h.get("aggregate_score"),
                    "image": h.get("image"),
                    "name_highlighted": h.get("name_highlighted"),
                    "brand_highlighted": h.get("brand_highlighted"),
                }
                for h in items
            ]})

    like = f"%{q}%"
    group_name_match = Supplement.product_group_id.in_(
        db.session.query(ProductGroup.id).filter(ProductGroup.name.ilike(like))
    )
    items = (_visible_supplements_query()
             .filter(or_(Supplement.name.ilike(like), Brand.name.ilike(like), group_name_match))
             .limit(8).all())

    return jsonify({"items": [
        {
            "id": s.id,
            # When the supplement is a group primary, show the canonical group name
            # in the typeahead so users see "Whey Protein XL" not the long variant.
            "name": (s.product_group.name if s.product_group else s.name),
            "brand": s.brand.name if s.brand else None,
            "slug": s.slug,
            # `image` is a model @property that resolves gallery → static → url.
            # Category drives the fallback emoji when no image is set.
            "image": s.image,
            "category": s.category.to_dict() if s.category else None,
        }
        for s in items
    ]})
