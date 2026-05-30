from flask import Blueprint, request, jsonify, abort

from ...extensions import db
from ...models import SupplementImage, Supplement
from ...admin_auth import login_required, require_editor, require_superadmin, log_action, diff_changes


admin_images_bp = Blueprint("admin_images", __name__)


WRITABLE_FIELDS = ("image_path", "image_url", "image_source", "image_type",
                   "display_order", "alt_text")

VALID_TYPES = ("main", "ingredients", "nutrition_facts", "back", "side",
               "box", "label", "lifestyle", "other")

# Mirrors SupplementImage column widths so we can defensively trim long values
# (Amazon marketing titles routinely exceed 200 chars and would otherwise blow
# up the INSERT with a Postgres "value too long" DataError → opaque 500).
_FIELD_LIMITS = {
    "alt_text": 200,
    "image_url": 500,
    "image_path": 500,
    "image_source": 60,
}


def _coerce(field: str, value):
    """Trim string values to their column width. None / non-strings pass through."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    limit = _FIELD_LIMITS.get(field)
    if limit and len(value) > limit:
        # Cut at a word boundary if possible so the truncation reads cleanly.
        cut = value[: limit - 1]
        last_space = cut.rfind(" ")
        if last_space > limit * 0.7:
            cut = cut[:last_space]
        return cut + "…"
    return value


@admin_images_bp.route("", methods=["GET"])
@login_required
def list_images():
    supplement_id = request.args.get("supplement_id")
    if not supplement_id:
        abort(400, description="supplement_id is required")
    items = (SupplementImage.query
             .filter_by(supplement_id=int(supplement_id))
             .order_by(SupplementImage.display_order)
             .all())
    return jsonify({"items": [i.to_dict() | {"id": i.id, "supplement_id": i.supplement_id} for i in items]})


@admin_images_bp.route("", methods=["POST"])
@require_editor
def create_image():
    data = request.get_json(silent=True) or {}
    supplement_id = data.get("supplement_id")
    if not supplement_id or not Supplement.query.get(supplement_id):
        abort(400, description="supplement_id is required and must reference an existing supplement")
    if not (data.get("image_url") or data.get("image_path")):
        abort(400, description="Either image_url or image_path is required")
    image_type = data.get("image_type", "main")
    if image_type not in VALID_TYPES:
        abort(400, description=f"image_type must be one of: {', '.join(VALID_TYPES)}")

    img = SupplementImage(supplement_id=supplement_id, image_type=image_type)
    for field in WRITABLE_FIELDS:
        if field == "image_type":
            continue
        if field in data:
            setattr(img, field, _coerce(field, data[field]))
    db.session.add(img)
    db.session.commit()
    log_action("CREATE", entity_type="supplement_image", entity_id=img.id,
               summary=f"Added image to supplement {supplement_id}",
               changes={k: getattr(img, k) for k in WRITABLE_FIELDS})
    return jsonify(img.to_dict() | {"id": img.id, "supplement_id": img.supplement_id}), 201


@admin_images_bp.route("/<int:img_id>", methods=["PATCH", "PUT"])
@require_editor
def update_image(img_id):
    img = SupplementImage.query.get_or_404(img_id)
    data = request.get_json(silent=True) or {}
    before = {k: getattr(img, k) for k in WRITABLE_FIELDS}

    if "image_type" in data:
        if data["image_type"] not in VALID_TYPES:
            abort(400, description=f"image_type must be one of: {', '.join(VALID_TYPES)}")
        img.image_type = data["image_type"]
    for field in ("image_path", "image_url", "image_source", "display_order", "alt_text"):
        if field in data:
            setattr(img, field, _coerce(field, data[field]))

    db.session.commit()
    after = {k: getattr(img, k) for k in WRITABLE_FIELDS}
    log_action("UPDATE", entity_type="supplement_image", entity_id=img.id,
               summary=f"Updated image {img.id} for supplement {img.supplement_id}",
               changes=diff_changes(before, after))
    return jsonify(img.to_dict() | {"id": img.id, "supplement_id": img.supplement_id})


@admin_images_bp.route("/<int:img_id>", methods=["DELETE"])
@require_superadmin
def delete_image(img_id):
    img = SupplementImage.query.get_or_404(img_id)
    supp_id = img.supplement_id
    db.session.delete(img)
    db.session.commit()
    log_action("DELETE", entity_type="supplement_image", entity_id=img_id,
               summary=f"Deleted image {img_id} from supplement {supp_id}")
    return jsonify({"ok": True})
