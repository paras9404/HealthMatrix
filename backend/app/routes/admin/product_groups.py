"""Admin endpoints for ProductGroup — bundling sibling SKUs together.

Two physically-different supplement rows that represent the same product line
(different flavor, different pack size, but otherwise identical formulation) get
linked under one ProductGroup so the public site renders them as a single
listing with a variant selector.

Routes
------
- GET    /                           list groups
- POST   /                           create group with member ids
- GET    /<id>                       group detail with members + ratings
- PATCH  /<id>                       rename / change primary / description
- DELETE /<id>                       ungroup (members keep their data)
- POST   /<id>/members               add supplements to the group
- DELETE /<id>/members/<supp_id>     remove one supplement from the group
- GET    /suggestions                auto-detected candidate groups for review

Matching for /suggestions is intentionally aligned with merge_duplicates.py — same
token-set Jaccard, same noise/discriminator dictionaries — so what shows up here
is the same set of pairs the merge tool would touch, just exposed for admin
review instead of being merged automatically.
"""
from collections import defaultdict
import re

from flask import Blueprint, request, jsonify, abort
from sqlalchemy import or_, asc, desc, func

from ...extensions import db
from ...models import Brand, Category, ProductGroup, Supplement
from ...admin_auth import (
    login_required, require_editor, require_superadmin,
    log_action, diff_changes,
)
from ...services import search_index
from ...utils import slugify, unique_slug


admin_product_groups_bp = Blueprint("admin_product_groups", __name__)


WRITABLE_FIELDS = ("name", "description", "primary_supplement_id")


def _reindex_supplements(supplement_ids) -> None:
    """Push the post-mutation state of each supplement to Meilisearch.

    Membership/primary/name changes on a ProductGroup invalidate the indexed
    docs of every variant — non-primary variants must drop out of the index
    (so search returns the canonical card, not duplicates), and the primary's
    doc carries the group's name + cross-group aggregate score. `upsert_supplement`
    handles both add-or-update and remove-when-no-longer-indexable, so we just
    fan out the ids and let it sort each one out.

    Errors are swallowed inside `upsert_supplement` itself, so a flaky search
    server never fails an admin write. De-duped because callers commonly pass
    'old members + new members' lists with overlap."""
    seen = set()
    for sid in supplement_ids:
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        search_index.upsert_supplement(sid)


# ---------------------------------------------------------------------------
# Suggestion-matching helpers (shared shape with merge_duplicates.py)
# ---------------------------------------------------------------------------
_NOISE_TOKENS = {
    "sachet", "sachets", "stick", "sticks", "pack", "packs", "bottle", "bottles",
    "ct", "count", "servings", "serving",
    "g", "gm", "gms", "kg", "mg", "mcg", "iu", "ml", "l", "oz", "lb",
    "flavor", "flavored", "flavour", "flavoured", "unflavored", "unflavoured",
    "chocolate", "vanilla", "strawberry", "mango", "kulfi", "coffee", "cocoa",
    "double", "rich", "dark", "light", "creamy", "natural", "kesar", "saffron",
    "choco", "crunch", "berry", "classic", "cookies", "cream", "caramel",
    "raw", "pure", "premium", "ultra", "complete", "extra", "high", "low",
    "wellness", "vitals", "wonder", "boost", "booster", "essential", "essentials",
    "2023", "2024", "2025", "2026",
    "and", "with", "for", "the", "of", "in", "by", "from",
}

_ALIASES = {
    "antarctic": "krill",
    "deep": "fish", "sea": "fish",
}

_STRICT_DISCRIMINATIVE = [
    {"isolate"}, {"concentrate"}, {"blend"}, {"hydrolyzed", "hydrolysate"},
    {"vegan", "plant"},
    {"men", "male", "mens"},
    {"women", "female", "womens"},
    {"kids", "kid", "child", "children"},
    {"d3"}, {"d2"}, {"k2"},
    {"b12"}, {"b6"}, {"b9"}, {"b1"}, {"b2"},
    {"pre", "preworkout"}, {"post", "postworkout"},
    {"biozyme"}, {"biozorb"}, {"isoboost"}, {"isorich"},
    {"performance"}, {"max"}, {"elite"}, {"advanced"}, {"professional"},
    {"sport", "sports"}, {"gainer", "mass"},
]

_SOFT_DISCRIMINATIVE = [
    {"liquid", "drops", "syrup", "spray"},
    {"tablet", "tablets", "capsule", "capsules", "softgel", "softgels", "caplet", "caplets"},
    {"gummy", "gummies"},
    {"powder", "powders"},
]

_DEFINING_TOKENS = {
    "whey", "casein", "protein", "plant", "soy", "pea", "creatine", "monohydrate",
    "omega", "fish", "krill", "algal", "multivitamin", "vitamin", "biotin",
    "magnesium", "zinc", "iron", "calcium", "selenium",
    "ashwagandha", "shilajit", "turmeric", "curcumin", "moringa", "berberine",
    "coq10", "astaxanthin", "collagen", "probiotic", "melatonin", "electrolyte",
    "preworkout", "bcaa", "eaa", "glutamine", "fiber", "shatavari",
    "ginseng", "elderberry", "spirulina", "chlorella",
    "bisglycinate", "glycinate", "picolinate", "citrate", "oxide",
}


def _normalize_tokens(name: str, brand: str | None) -> set[str]:
    if not name:
        return set()
    s = name.lower()
    if brand:
        bl = brand.lower()
        for variant in (bl, bl.replace("nutrition", "").strip(),
                        bl.replace("foods", "").strip(),
                        bl.replace("supplements", "").strip()):
            if variant and s.startswith(variant):
                s = s[len(variant):].lstrip(" -|:")
                break
    s = re.sub(r"[^a-z0-9]+", " ", s)
    raw = [t for t in s.split() if t and t not in _NOISE_TOKENS]
    return {_ALIASES.get(t, t) for t in raw}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _disagrees(a: set[str], b: set[str]) -> bool:
    for group in _STRICT_DISCRIMINATIVE:
        if bool(a & group) != bool(b & group):
            return True
    for group in _SOFT_DISCRIMINATIVE:
        ai, bi = a & group, b & group
        if ai and bi and not (ai & bi):
            return True
    return False


def _shares_defining(a: set[str], b: set[str]) -> bool:
    return bool(a & b & _DEFINING_TOKENS)


def _candidate_pair(a: set[str], b: set[str], threshold: float = 0.5) -> tuple[bool, float]:
    """Suggest-mode: a touch more lenient than merge_duplicates so the admin sees
    plausible matches and decides. Same safety guards (defining-token + non-disagreement)
    apply, threshold lowered slightly for surface."""
    if not a or not b:
        return False, 0.0
    if _disagrees(a, b):
        return False, 0.0
    if not _shares_defining(a, b):
        return False, 0.0
    sim = _jaccard(a, b)
    if len(a) >= 2 and a.issubset(b):
        return True, sim
    if len(b) >= 2 and b.issubset(a):
        return True, sim
    return sim >= threshold, sim


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_ungrouped_or_in_this_group(supp: Supplement, group_id: int | None):
    """Reject supplements already pinned to a different group — moves should be
    explicit (remove from the other group first) so the audit trail is clean."""
    if supp.product_group_id and supp.product_group_id != group_id:
        abort(409, description=(
            f"Supplement '{supp.name}' (id={supp.id}) is already a member of "
            f"product group #{supp.product_group_id}. Remove it from that group first."
        ))


def _validate_member_compat(group: ProductGroup, supp: Supplement):
    """All variants of a group must share brand + category. The matcher already biases
    toward this, but a manual selector could violate it — guard explicitly."""
    if supp.brand_id != group.brand_id:
        abort(400, description=(
            f"Supplement '{supp.name}' belongs to brand id={supp.brand_id} "
            f"but the group is brand id={group.brand_id}."
        ))
    if supp.category_id != group.category_id:
        abort(400, description=(
            f"Supplement '{supp.name}' belongs to category id={supp.category_id} "
            f"but the group is category id={group.category_id}."
        ))


def _pick_primary(group: ProductGroup) -> int | None:
    """Choose a sensible primary when one isn't set or has been removed:
    most ratings, then oldest. Returns None if the group has no members."""
    members = group.members.all()
    if not members:
        return None
    members_with_count = [(m, m.review_count) for m in members]
    members_with_count.sort(key=lambda x: (-x[1], x[0].created_at or 0))
    return members_with_count[0][0].id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@admin_product_groups_bp.route("", methods=["GET"])
@login_required
def list_groups():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 25)), 1), 200)
    q = (request.args.get("q") or "").strip()
    brand_id = request.args.get("brand_id")
    category_id = request.args.get("category_id")
    sort = request.args.get("sort", "newest")

    query = ProductGroup.query.join(Brand, Brand.id == ProductGroup.brand_id) \
                              .join(Category, Category.id == ProductGroup.category_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            ProductGroup.name.ilike(like),
            ProductGroup.slug.ilike(like),
            Brand.name.ilike(like),
        ))
    if brand_id:
        query = query.filter(ProductGroup.brand_id == int(brand_id))
    if category_id:
        query = query.filter(ProductGroup.category_id == int(category_id))

    if sort == "name":
        query = query.order_by(asc(ProductGroup.name), ProductGroup.id)
    elif sort == "oldest":
        query = query.order_by(asc(ProductGroup.created_at), ProductGroup.id)
    else:  # newest
        query = query.order_by(desc(ProductGroup.created_at), ProductGroup.id)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "items": [g.to_dict() for g in items],
        "page": page, "per_page": per_page, "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


@admin_product_groups_bp.route("/<int:group_id>", methods=["GET"])
@login_required
def get_group(group_id):
    g = ProductGroup.query.get_or_404(group_id)
    return jsonify(g.to_dict(include_members=True))


@admin_product_groups_bp.route("", methods=["POST"])
@require_editor
def create_group():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, description="name is required")
    member_ids = data.get("member_ids") or []
    if not isinstance(member_ids, list) or len(member_ids) < 1:
        abort(400, description="member_ids must be a list of at least one supplement id")

    members = Supplement.query.filter(Supplement.id.in_(member_ids)).all()
    if len(members) != len(set(member_ids)):
        abort(400, description="One or more member_ids do not exist")
    for m in members:
        _ensure_ungrouped_or_in_this_group(m, None)

    # All members must share brand and category — derive these from the first member.
    brand_ids = {m.brand_id for m in members}
    category_ids = {m.category_id for m in members}
    if len(brand_ids) > 1:
        abort(400, description="All members must share the same brand")
    if len(category_ids) > 1:
        abort(400, description="All members must share the same category")

    base_slug = slugify((data.get("slug") or "").strip() or name)
    group = ProductGroup(
        name=name,
        slug=unique_slug(ProductGroup, base_slug),
        description=data.get("description"),
        brand_id=members[0].brand_id,
        category_id=members[0].category_id,
    )
    db.session.add(group)
    db.session.flush()  # get group.id before linking members

    for m in members:
        m.product_group_id = group.id
        # If the variant_label wasn't already set, leave it blank — admin can fill in later.

    primary_id = data.get("primary_supplement_id")
    if primary_id and int(primary_id) in {m.id for m in members}:
        group.primary_supplement_id = int(primary_id)
    else:
        group.primary_supplement_id = _pick_primary(group)

    db.session.commit()
    _reindex_supplements(m.id for m in members)
    log_action(
        "CREATE", entity_type="product_group", entity_id=group.id,
        summary=f"Created product group '{group.name}' with {len(members)} members",
        changes={"name": group.name, "slug": group.slug, "member_ids": [m.id for m in members]},
    )
    return jsonify(group.to_dict(include_members=True)), 201


@admin_product_groups_bp.route("/<int:group_id>", methods=["PATCH", "PUT"])
@require_editor
def update_group(group_id):
    group = ProductGroup.query.get_or_404(group_id)
    data = request.get_json(silent=True) or {}
    before = {k: getattr(group, k) for k in WRITABLE_FIELDS + ("slug",)}

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            abort(400, description="name cannot be empty")
        group.name = new_name
    if "slug" in data and data["slug"]:
        group.slug = unique_slug(ProductGroup, slugify(data["slug"]), exclude_id=group.id)
    if "description" in data:
        group.description = data["description"] or None
    if "primary_supplement_id" in data:
        new_primary = data["primary_supplement_id"]
        if new_primary is not None:
            new_primary = int(new_primary)
            member_ids = {m.id for m in group.members.all()}
            if new_primary not in member_ids:
                abort(400, description="primary_supplement_id must reference a member of this group")
        group.primary_supplement_id = new_primary

    db.session.commit()
    # Re-index every member: a primary swap demotes the old primary out of the
    # index and promotes the new one, while a name change updates the public
    # name carried on the (single) indexed primary doc.
    _reindex_supplements(m.id for m in group.members.all())
    after = {k: getattr(group, k) for k in WRITABLE_FIELDS + ("slug",)}
    log_action(
        "UPDATE", entity_type="product_group", entity_id=group.id,
        summary=f"Updated product group '{group.name}'", changes=diff_changes(before, after),
    )
    return jsonify(group.to_dict(include_members=True))


@admin_product_groups_bp.route("/<int:group_id>", methods=["DELETE"])
@require_editor
def delete_group(group_id):
    """Ungroup — drop the wrapper, keep the supplement rows. Members get their
    product_group_id cleared and become standalone again."""
    group = ProductGroup.query.get_or_404(group_id)
    name = group.name
    members = group.members.all()
    member_ids = [m.id for m in members]
    member_count = len(members)
    # Explicitly null out the FK so we don't depend on SET NULL behavior with SQLite.
    for m in members:
        m.product_group_id = None
    # Avoid leaving primary_supplement_id pointing into a deleted row.
    group.primary_supplement_id = None
    db.session.flush()
    db.session.delete(group)
    db.session.commit()
    # Each former member is now a standalone product — they all need to come
    # back into the index (the non-primary variants were absent before).
    _reindex_supplements(member_ids)
    log_action(
        "DELETE", entity_type="product_group", entity_id=group_id,
        summary=f"Ungrouped product group '{name}' ({member_count} members released)",
    )
    return jsonify({"ok": True})


@admin_product_groups_bp.route("/<int:group_id>/members", methods=["POST"])
@require_editor
def add_members(group_id):
    group = ProductGroup.query.get_or_404(group_id)
    data = request.get_json(silent=True) or {}
    member_ids = data.get("member_ids") or []
    if not isinstance(member_ids, list) or not member_ids:
        abort(400, description="member_ids must be a non-empty list")

    supps = Supplement.query.filter(Supplement.id.in_(member_ids)).all()
    found = {s.id for s in supps}
    missing = [sid for sid in member_ids if sid not in found]
    if missing:
        abort(400, description=f"Supplement ids not found: {missing}")

    for s in supps:
        _ensure_ungrouped_or_in_this_group(s, group.id)
        _validate_member_compat(group, s)
        s.product_group_id = group.id

    if group.primary_supplement_id is None:
        group.primary_supplement_id = _pick_primary(group)
    db.session.commit()
    # Re-index the whole group: the existing primary's aggregate score now
    # spans the new members, and the new members themselves need to drop out
    # of the index (or, if any of them is now the primary, refresh).
    _reindex_supplements(m.id for m in group.members.all())
    log_action(
        "UPDATE", entity_type="product_group", entity_id=group.id,
        summary=f"Added {len(supps)} member(s) to product group '{group.name}'",
        changes={"added_member_ids": [s.id for s in supps]},
    )
    return jsonify(group.to_dict(include_members=True))


@admin_product_groups_bp.route("/<int:group_id>/members/<int:supp_id>", methods=["DELETE"])
@require_editor
def remove_member(group_id, supp_id):
    group = ProductGroup.query.get_or_404(group_id)
    supp = Supplement.query.get_or_404(supp_id)
    if supp.product_group_id != group.id:
        abort(404, description="That supplement is not a member of this group")

    supp.product_group_id = None
    db.session.flush()

    remaining = group.members.count()
    if remaining == 0:
        # Empty group is a footgun — delete it so the list doesn't fill with ghosts.
        name = group.name
        group_id_for_log = group.id
        group.primary_supplement_id = None
        db.session.delete(group)
        db.session.commit()
        # The released supplement is now standalone — index it under its own name.
        _reindex_supplements([supp_id])
        log_action(
            "DELETE", entity_type="product_group", entity_id=group_id_for_log,
            summary=f"Auto-deleted empty product group '{name}' after removing its last member",
        )
        return jsonify({"ok": True, "group_deleted": True})

    if group.primary_supplement_id == supp_id:
        group.primary_supplement_id = _pick_primary(group)
    db.session.commit()
    # Re-index released supplement (now standalone) plus every remaining member —
    # the primary may have just been swapped and the group's aggregate shrunk.
    _reindex_supplements([supp_id, *(m.id for m in group.members.all())])
    log_action(
        "UPDATE", entity_type="product_group", entity_id=group.id,
        summary=f"Removed supplement '{supp.name}' from product group '{group.name}'",
        changes={"removed_member_id": supp_id},
    )
    return jsonify(group.to_dict(include_members=True))


@admin_product_groups_bp.route("/<int:group_id>/members/<int:supp_id>/variant-label",
                                methods=["PATCH"])
@require_editor
def set_variant_label(group_id, supp_id):
    """Lightweight endpoint to edit a single member's variant_label without
    going through the full supplement update flow."""
    group = ProductGroup.query.get_or_404(group_id)
    supp = Supplement.query.get_or_404(supp_id)
    if supp.product_group_id != group.id:
        abort(404, description="That supplement is not a member of this group")
    data = request.get_json(silent=True) or {}
    label = data.get("variant_label")
    if label is not None:
        label = str(label).strip() or None
    supp.variant_label = label
    db.session.commit()
    # `variant_label` is one of the indexed fields on the primary's doc; for
    # non-primary members `upsert_supplement` is a no-op (still not indexable).
    _reindex_supplements([supp.id])
    return jsonify({"ok": True, "variant_label": supp.variant_label})


@admin_product_groups_bp.route("/suggestions", methods=["GET"])
@login_required
def suggestions():
    """Auto-detected candidate groups for review.

    Looks at every brand and runs the same Jaccard token-set matcher used by
    merge_duplicates.py. Only emits clusters of supplements that are NOT already
    in any product group. Each cluster comes with similarity scores so the admin
    can eyeball the strength before clicking 'Group these'.
    """
    min_size = max(int(request.args.get("min_size", 2)), 2)
    max_groups = min(max(int(request.args.get("max_groups", 200)), 1), 500)
    threshold = float(request.args.get("threshold", 0.5))

    candidates = (Supplement.query
                  .filter(Supplement.product_group_id.is_(None))
                  .all())

    by_brand: dict[int, list[Supplement]] = defaultdict(list)
    for s in candidates:
        if s.brand_id is not None:
            by_brand[s.brand_id].append(s)

    suggested = []
    for brand_id, items in by_brand.items():
        if len(items) < 2:
            continue
        # All items also need to share category. Group within (brand, category) buckets.
        by_cat: dict[int, list[Supplement]] = defaultdict(list)
        for s in items:
            by_cat[s.category_id].append(s)

        for cat_id, cat_items in by_cat.items():
            if len(cat_items) < 2:
                continue
            tokens = {s.id: _normalize_tokens(s.name, s.brand.name if s.brand else None)
                      for s in cat_items}
            parent = {s.id: s.id for s in cat_items}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(x, y):
                rx, ry = find(x), find(y)
                if rx != ry:
                    parent[rx] = ry

            pair_scores: dict[tuple[int, int], float] = {}
            ids = [s.id for s in cat_items]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    ok, sim = _candidate_pair(tokens[ids[i]], tokens[ids[j]], threshold)
                    if ok:
                        union(ids[i], ids[j])
                        pair_scores[(ids[i], ids[j])] = round(sim, 3)

            clusters: dict[int, list[Supplement]] = defaultdict(list)
            for s in cat_items:
                clusters[find(s.id)].append(s)

            for cluster in clusters.values():
                if len(cluster) < min_size:
                    continue
                # Compute the smallest pairwise Jaccard inside the cluster — gives
                # the admin a sense of weakest link in the proposed group.
                cluster_ids = [c.id for c in cluster]
                pair_sims = []
                for i in range(len(cluster_ids)):
                    for j in range(i + 1, len(cluster_ids)):
                        a, b = cluster_ids[i], cluster_ids[j]
                        sim = pair_scores.get((a, b)) or pair_scores.get((b, a))
                        if sim is not None:
                            pair_sims.append(sim)
                weakest = round(min(pair_sims), 3) if pair_sims else None
                strongest = round(max(pair_sims), 3) if pair_sims else None
                suggested.append({
                    "brand": cluster[0].brand.to_dict() if cluster[0].brand else None,
                    "category": cluster[0].category.to_dict() if cluster[0].category else None,
                    "weakest_similarity": weakest,
                    "strongest_similarity": strongest,
                    "members": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "slug": s.slug,
                            "image": s.image,
                            "review_count": s.review_count,
                            "aggregate_score": s.aggregate_score,
                            "sources": sorted({r.source.name for r in s.visible_ratings if r.source}),
                        }
                        for s in cluster
                    ],
                })

    # Strongest matches first — admin's attention is highest at the top.
    suggested.sort(key=lambda c: (c["weakest_similarity"] or 0), reverse=True)
    return jsonify({"items": suggested[:max_groups], "total": len(suggested)})


@admin_product_groups_bp.route("/ungrouped", methods=["GET"])
@login_required
def ungrouped_supplements():
    """Supplements not yet in any group — used by the manual-builder UI search box.

    Filters by brand_id and category_id when provided so the admin can scope the
    picker to compatible candidates.
    """
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 50)), 1), 200)
    q = (request.args.get("q") or "").strip()
    brand_id = request.args.get("brand_id")
    category_id = request.args.get("category_id")

    query = (Supplement.query
             .filter(Supplement.product_group_id.is_(None))
             .join(Brand, Brand.id == Supplement.brand_id))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Supplement.name.ilike(like),
            Supplement.slug.ilike(like),
            Brand.name.ilike(like),
        ))
    if brand_id:
        query = query.filter(Supplement.brand_id == int(brand_id))
    if category_id:
        query = query.filter(Supplement.category_id == int(category_id))

    query = query.order_by(asc(Brand.name), asc(Supplement.name), Supplement.id)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "slug": s.slug,
                "image": s.image,
                "brand": s.brand.to_dict() if s.brand else None,
                "category": s.category.to_dict() if s.category else None,
                "brand_id": s.brand_id,
                "category_id": s.category_id,
                "review_count": s.review_count,
                "aggregate_score": s.aggregate_score,
            }
            for s in items
        ],
        "page": page, "per_page": per_page, "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })
