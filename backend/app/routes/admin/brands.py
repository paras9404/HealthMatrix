from flask import Blueprint, request, jsonify, abort
from sqlalchemy import or_, asc, desc, func, select, nullslast

from ...extensions import db
from ...models import Brand, Supplement
from ...admin_auth import login_required, require_editor, require_superadmin, log_action, diff_changes
from ...utils import slugify, unique_slug


admin_brands_bp = Blueprint("admin_brands", __name__)


WRITABLE_FIELDS = ("name", "website_url", "logo_url", "description", "country", "is_active")


def _serialize(brand: Brand) -> dict:
    return {
        **brand.to_dict(include_count=True),
        "created_at": brand.created_at.isoformat() if brand.created_at else None,
        "updated_at": brand.updated_at.isoformat() if brand.updated_at else None,
    }


def _supplement_count_expr():
    """Correlated subquery: number of supplements per brand. Used for sorting since
    the Python-side active_supplement_count property isn't reachable from SQL."""
    return (select(func.count(Supplement.id))
            .where(Supplement.brand_id == Brand.id)
            .scalar_subquery())


_BRAND_SORTS = {
    "name": Brand.name,
    "slug": Brand.slug,
    "country": Brand.country,
    "is_active": Brand.is_active,
    "supplement_count": _supplement_count_expr,
    "created_at": Brand.created_at,
}


@admin_brands_bp.route("", methods=["GET"])
@login_required
def list_brands():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 25)), 1), 200)
    search = (request.args.get("q") or "").strip()
    is_active = request.args.get("is_active")
    sort = request.args.get("sort", "name")
    direction = request.args.get("dir", "asc").lower()

    query = Brand.query
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Brand.name.ilike(like), Brand.slug.ilike(like)))
    if is_active in ("true", "false"):
        query = query.filter(Brand.is_active.is_(is_active == "true"))

    sort_col = _BRAND_SORTS.get(sort, Brand.name)
    if callable(sort_col):
        sort_col = sort_col()
    order = nullslast(desc(sort_col) if direction == "desc" else asc(sort_col))
    # Stable secondary sort so equal values get a deterministic order across pages.
    query = query.order_by(order, Brand.id)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "items": [_serialize(b) for b in items],
        "page": page, "per_page": per_page, "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


@admin_brands_bp.route("/<int:brand_id>", methods=["GET"])
@login_required
def get_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    return jsonify(_serialize(brand))


@admin_brands_bp.route("", methods=["POST"])
@require_editor
def create_brand():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, description="name is required")

    slug_input = (data.get("slug") or "").strip()
    base_slug = slugify(slug_input or name)
    slug = unique_slug(Brand, base_slug)

    brand = Brand(name=name, slug=slug)
    for field in WRITABLE_FIELDS:
        if field == "name":
            continue
        if field in data:
            setattr(brand, field, data[field])
    db.session.add(brand)
    db.session.commit()

    log_action("CREATE", entity_type="brand", entity_id=brand.id,
               summary=f"Created brand '{brand.name}'", changes={k: getattr(brand, k) for k in WRITABLE_FIELDS})
    return jsonify(_serialize(brand)), 201


@admin_brands_bp.route("/<int:brand_id>", methods=["PATCH", "PUT"])
@require_editor
def update_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    data = request.get_json(silent=True) or {}
    before = {k: getattr(brand, k) for k in WRITABLE_FIELDS + ("slug",)}

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            abort(400, description="name cannot be empty")
        brand.name = new_name
    if "slug" in data and data["slug"]:
        new_slug = unique_slug(Brand, slugify(data["slug"]), exclude_id=brand.id)
        brand.slug = new_slug
    active_changed = ("is_active" in data and bool(data["is_active"]) != bool(brand.is_active))
    name_changed = ("name" in data and data["name"] != before.get("name"))
    slug_changed = ("slug" in data and data["slug"] and brand.slug != before.get("slug"))
    for field in ("website_url", "logo_url", "description", "country", "is_active"):
        if field in data:
            setattr(brand, field, data[field])

    db.session.commit()
    # Brand visibility/name changes ripple into every one of its supplements'
    # search documents — refresh them all. Only touch the index when something
    # actually changed that the index encodes.
    if active_changed or name_changed or slug_changed:
        from ...services import search_index
        for s in Supplement.query.filter_by(brand_id=brand.id).all():
            search_index.upsert_supplement(s.id)
    after = {k: getattr(brand, k) for k in WRITABLE_FIELDS + ("slug",)}
    log_action("UPDATE", entity_type="brand", entity_id=brand.id,
               summary=f"Updated brand '{brand.name}'", changes=diff_changes(before, after))
    return jsonify(_serialize(brand))


@admin_brands_bp.route("/<int:brand_id>", methods=["DELETE"])
@require_superadmin
def delete_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    in_use = Supplement.query.filter_by(brand_id=brand.id).count()
    if in_use:
        abort(400, description=f"Brand has {in_use} supplements — reassign or delete them first")
    name = brand.name
    db.session.delete(brand)
    db.session.commit()
    log_action("DELETE", entity_type="brand", entity_id=brand_id,
               summary=f"Deleted brand '{name}'")
    return jsonify({"ok": True})
