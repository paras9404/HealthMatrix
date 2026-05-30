from flask import Blueprint, request, jsonify, abort
from sqlalchemy import or_, asc, desc, func, select, nullslast

from ...extensions import db
from ...models import Category, Supplement
from ...admin_auth import login_required, require_editor, require_superadmin, log_action, diff_changes
from ...utils import slugify, unique_slug


admin_categories_bp = Blueprint("admin_categories", __name__)


WRITABLE_FIELDS = ("name", "description", "icon", "sort_order", "is_active")


def _serialize(cat: Category) -> dict:
    return {
        **cat.to_dict(include_count=True),
        "sort_order": cat.sort_order,
        "created_at": cat.created_at.isoformat() if cat.created_at else None,
    }


_CATEGORY_SORTS = {
    "name": Category.name,
    "slug": Category.slug,
    "sort_order": Category.sort_order,
    "is_active": Category.is_active,
    "supplement_count": lambda: (
        select(func.count(Supplement.id))
        .where(Supplement.category_id == Category.id)
        .scalar_subquery()
    ),
}


@admin_categories_bp.route("", methods=["GET"])
@login_required
def list_categories():
    search = (request.args.get("q") or "").strip()
    sort = request.args.get("sort")
    direction = request.args.get("dir", "asc").lower()

    query = Category.query
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Category.name.ilike(like), Category.slug.ilike(like)))

    if sort and sort in _CATEGORY_SORTS:
        col = _CATEGORY_SORTS[sort]
        if callable(col):
            col = col()
        order = nullslast(desc(col) if direction == "desc" else asc(col))
        query = query.order_by(order, Category.id)
    else:
        # Default: editorial sort_order then name (preserves admin-defined ordering).
        query = query.order_by(Category.sort_order, Category.name)

    items = query.all()
    return jsonify({"items": [_serialize(c) for c in items]})


@admin_categories_bp.route("/<int:cat_id>", methods=["GET"])
@login_required
def get_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    return jsonify(_serialize(cat))


@admin_categories_bp.route("", methods=["POST"])
@require_editor
def create_category():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, description="name is required")

    base_slug = slugify((data.get("slug") or "").strip() or name)
    cat = Category(name=name, slug=unique_slug(Category, base_slug))
    for field in WRITABLE_FIELDS:
        if field == "name":
            continue
        if field in data:
            setattr(cat, field, data[field])
    db.session.add(cat)
    db.session.commit()
    log_action("CREATE", entity_type="category", entity_id=cat.id,
               summary=f"Created category '{cat.name}'", changes={k: getattr(cat, k) for k in WRITABLE_FIELDS})
    return jsonify(_serialize(cat)), 201


@admin_categories_bp.route("/<int:cat_id>", methods=["PATCH", "PUT"])
@require_editor
def update_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    data = request.get_json(silent=True) or {}
    before = {k: getattr(cat, k) for k in WRITABLE_FIELDS + ("slug",)}

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            abort(400, description="name cannot be empty")
        cat.name = new_name
    if "slug" in data and data["slug"]:
        cat.slug = unique_slug(Category, slugify(data["slug"]), exclude_id=cat.id)
    active_changed = ("is_active" in data and bool(data["is_active"]) != bool(cat.is_active))
    name_changed = ("name" in data and data["name"] != before.get("name"))
    icon_changed = ("icon" in data and data["icon"] != before.get("icon"))
    slug_changed = ("slug" in data and data["slug"] and cat.slug != before.get("slug"))
    for field in ("description", "icon", "sort_order", "is_active"):
        if field in data:
            setattr(cat, field, data[field])

    db.session.commit()
    if active_changed or name_changed or slug_changed or icon_changed:
        from ...services import search_index
        from ...models import Supplement
        for s in Supplement.query.filter_by(category_id=cat.id).all():
            search_index.upsert_supplement(s.id)
    after = {k: getattr(cat, k) for k in WRITABLE_FIELDS + ("slug",)}
    log_action("UPDATE", entity_type="category", entity_id=cat.id,
               summary=f"Updated category '{cat.name}'", changes=diff_changes(before, after))
    return jsonify(_serialize(cat))


@admin_categories_bp.route("/<int:cat_id>", methods=["DELETE"])
@require_superadmin
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    in_use = Supplement.query.filter_by(category_id=cat.id).count()
    if in_use:
        abort(400, description=f"Category has {in_use} supplements — reassign or delete them first")
    name = cat.name
    db.session.delete(cat)
    db.session.commit()
    log_action("DELETE", entity_type="category", entity_id=cat_id,
               summary=f"Deleted category '{name}'")
    return jsonify({"ok": True})
