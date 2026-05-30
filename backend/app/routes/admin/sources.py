from flask import Blueprint, request, jsonify, abort
from sqlalchemy import or_, asc, desc, func, select, nullslast

from ...extensions import db
from ...models import Source, Rating
from ...admin_auth import login_required, require_editor, require_superadmin, log_action, diff_changes
from ...utils import slugify, unique_slug


admin_sources_bp = Blueprint("admin_sources", __name__)


WRITABLE_FIELDS = ("name", "website_url", "logo_url", "description",
                   "rating_scale", "is_verified", "is_active", "sort_order")


def _serialize(s: Source) -> dict:
    return {
        **s.to_dict(include_count=True),
        "sort_order": s.sort_order,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


_SOURCE_SORTS = {
    "name": Source.name,
    "slug": Source.slug,
    "rating_scale": Source.rating_scale,
    "is_verified": Source.is_verified,
    "is_active": Source.is_active,
    "sort_order": Source.sort_order,
    "supplement_count": lambda: (
        select(func.count(func.distinct(Rating.supplement_id)))
        .where(Rating.source_id == Source.id)
        .scalar_subquery()
    ),
}


@admin_sources_bp.route("", methods=["GET"])
@login_required
def list_sources():
    search = (request.args.get("q") or "").strip()
    sort = request.args.get("sort")
    direction = request.args.get("dir", "asc").lower()

    query = Source.query
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Source.name.ilike(like), Source.slug.ilike(like)))

    if sort and sort in _SOURCE_SORTS:
        col = _SOURCE_SORTS[sort]
        if callable(col):
            col = col()
        order = nullslast(desc(col) if direction == "desc" else asc(col))
        query = query.order_by(order, Source.id)
    else:
        query = query.order_by(Source.sort_order, Source.name)

    items = query.all()
    return jsonify({"items": [_serialize(s) for s in items]})


@admin_sources_bp.route("/<int:source_id>", methods=["GET"])
@login_required
def get_source(source_id):
    s = Source.query.get_or_404(source_id)
    return jsonify(_serialize(s))


@admin_sources_bp.route("", methods=["POST"])
@require_editor
def create_source():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    website_url = (data.get("website_url") or "").strip()
    if not name:
        abort(400, description="name is required")
    if not website_url:
        abort(400, description="website_url is required")

    base_slug = slugify((data.get("slug") or "").strip() or name)
    s = Source(name=name, slug=unique_slug(Source, base_slug), website_url=website_url)
    for field in WRITABLE_FIELDS:
        if field in ("name", "website_url"):
            continue
        if field in data:
            setattr(s, field, data[field])
    db.session.add(s)
    db.session.commit()
    log_action("CREATE", entity_type="source", entity_id=s.id,
               summary=f"Created source '{s.name}'", changes={k: getattr(s, k) for k in WRITABLE_FIELDS})
    return jsonify(_serialize(s)), 201


@admin_sources_bp.route("/<int:source_id>", methods=["PATCH", "PUT"])
@require_editor
def update_source(source_id):
    s = Source.query.get_or_404(source_id)
    data = request.get_json(silent=True) or {}
    before = {k: getattr(s, k) for k in WRITABLE_FIELDS + ("slug",)}

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            abort(400, description="name cannot be empty")
        s.name = new_name
    if "slug" in data and data["slug"]:
        s.slug = unique_slug(Source, slugify(data["slug"]), exclude_id=s.id)
    active_changed = ("is_active" in data and bool(data["is_active"]) != bool(s.is_active))
    slug_changed = ("slug" in data and data["slug"] and s.slug != before.get("slug"))
    for field in ("website_url", "logo_url", "description", "rating_scale",
                  "is_verified", "is_active", "sort_order"):
        if field in data:
            setattr(s, field, data[field])

    db.session.commit()
    # Toggling a source's active flag changes which ratings count for visibility
    # and aggregate scores — every supplement rated by this source needs a refresh.
    if active_changed or slug_changed:
        from ...services import search_index
        from ...models import Supplement, Rating
        affected_ids = {row.supplement_id for row in
                        Rating.query.filter_by(source_id=s.id).all()}
        # Group siblings need to be refreshed too (group score is shared).
        sibling_ids: set[int] = set()
        for sid in affected_ids:
            sup = Supplement.query.get(sid)
            if sup is None:
                continue
            if sup.product_group_id and sup.product_group is not None:
                sibling_ids.update(v.id for v in sup.product_group.members.all())
        for sid in affected_ids | sibling_ids:
            search_index.upsert_supplement(sid)
    after = {k: getattr(s, k) for k in WRITABLE_FIELDS + ("slug",)}
    log_action("UPDATE", entity_type="source", entity_id=s.id,
               summary=f"Updated source '{s.name}'", changes=diff_changes(before, after))
    return jsonify(_serialize(s))


@admin_sources_bp.route("/<int:source_id>", methods=["DELETE"])
@require_superadmin
def delete_source(source_id):
    s = Source.query.get_or_404(source_id)
    in_use = Rating.query.filter_by(source_id=s.id).count()
    if in_use:
        abort(400, description=f"Source has {in_use} ratings — delete those ratings first or deactivate this source instead")
    name = s.name
    db.session.delete(s)
    db.session.commit()
    log_action("DELETE", entity_type="source", entity_id=source_id,
               summary=f"Deleted source '{name}'")
    return jsonify({"ok": True})
