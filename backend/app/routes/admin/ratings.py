from flask import Blueprint, request, jsonify, abort
from datetime import date
from sqlalchemy import asc, desc, nullslast

from ...extensions import db
from ...models import Rating, Supplement, Source
from ...admin_auth import login_required, require_editor, require_superadmin, log_action, diff_changes
from ...services import search_index


def _reindex_supplement_with_group(supplement_id: int) -> None:
    """A rating change on supplement X also affects its product-group siblings'
    indexed scores (visibility/aggregate). Refresh every member."""
    if not supplement_id:
        return
    s = Supplement.query.get(supplement_id)
    if s is None:
        return
    if s.product_group_id and s.product_group is not None:
        for v in s.product_group.members.all():
            search_index.upsert_supplement(v.id)
    else:
        search_index.upsert_supplement(s.id)


admin_ratings_bp = Blueprint("admin_ratings", __name__)


WRITABLE_FIELDS = (
    "supplement_id", "source_id", "score", "max_score", "verdict", "summary",
    "report_url", "buy_url", "tested_at", "batch_no", "manufacturing_date",
    "expiration_date", "tested_by",
)


def _serialize(r: Rating) -> dict:
    base = r.to_dict()
    base.update({
        "supplement_id": r.supplement_id,
        "source_id": r.source_id,
        "supplement": {"id": r.supplement.id, "name": r.supplement.name, "slug": r.supplement.slug} if r.supplement else None,
    })
    return base


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except Exception:
        abort(400, description=f"Invalid date format for tested_at: {value} (expected YYYY-MM-DD)")


_RATING_SORTS = {
    "score": Rating.score,
    "verdict": Rating.verdict,
    "tested_at": Rating.tested_at,
    "created_at": Rating.created_at,
    # Joined sorts handled below since they need an outer join.
    "supplement": "supplement",
    "source": "source",
}


@admin_ratings_bp.route("", methods=["GET"])
@login_required
def list_ratings():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 25)), 1), 200)
    supplement_id = request.args.get("supplement_id")
    source_id = request.args.get("source_id")
    sort = request.args.get("sort", "created_at")
    direction = request.args.get("dir", "desc").lower()

    query = Rating.query
    if supplement_id:
        query = query.filter(Rating.supplement_id == int(supplement_id))
    if source_id:
        query = query.filter(Rating.source_id == int(source_id))

    if sort == "supplement":
        query = query.outerjoin(Supplement, Supplement.id == Rating.supplement_id)
        col = Supplement.name
    elif sort == "source":
        query = query.outerjoin(Source, Source.id == Rating.source_id)
        col = Source.name
    else:
        col = _RATING_SORTS.get(sort, Rating.created_at)
    order = nullslast(desc(col) if direction == "desc" else asc(col))
    query = query.order_by(order, Rating.id)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "items": [_serialize(r) for r in items],
        "page": page, "per_page": per_page, "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })


@admin_ratings_bp.route("/<int:rating_id>", methods=["GET"])
@login_required
def get_rating(rating_id):
    r = Rating.query.get_or_404(rating_id)
    return jsonify(_serialize(r))


@admin_ratings_bp.route("", methods=["POST"])
@require_editor
def create_rating():
    data = request.get_json(silent=True) or {}
    supplement_id = data.get("supplement_id")
    source_id = data.get("source_id")
    report_url = (data.get("report_url") or "").strip()

    if not supplement_id or not Supplement.query.get(supplement_id):
        abort(400, description="supplement_id is required and must reference an existing supplement")
    if not source_id or not Source.query.get(source_id):
        abort(400, description="source_id is required and must reference an existing source")
    if not report_url:
        abort(400, description="report_url is required")

    if Rating.query.filter_by(supplement_id=supplement_id, source_id=source_id).first():
        abort(400, description="A rating from this source already exists for this supplement (one per source)")

    r = Rating(supplement_id=supplement_id, source_id=source_id, report_url=report_url)
    for field in WRITABLE_FIELDS:
        if field in ("supplement_id", "source_id", "report_url"):
            continue
        if field in data:
            value = data[field]
            if field == "tested_at":
                value = _parse_date(value)
            setattr(r, field, value)
    db.session.add(r)
    db.session.commit()
    _reindex_supplement_with_group(r.supplement_id)
    log_action("CREATE", entity_type="rating", entity_id=r.id,
               summary=f"Added rating from source {source_id} for supplement {supplement_id}",
               changes={"supplement_id": supplement_id, "source_id": source_id, "score": r.score, "verdict": r.verdict})
    return jsonify(_serialize(r)), 201


@admin_ratings_bp.route("/<int:rating_id>", methods=["PATCH", "PUT"])
@require_editor
def update_rating(rating_id):
    r = Rating.query.get_or_404(rating_id)
    data = request.get_json(silent=True) or {}
    before = {k: getattr(r, k) for k in WRITABLE_FIELDS}

    old_supplement_id = r.supplement_id
    for field in WRITABLE_FIELDS:
        if field in data:
            value = data[field]
            if field in ("supplement_id", "source_id"):
                target = Supplement if field == "supplement_id" else Source
                if not value or not target.query.get(value):
                    abort(400, description=f"{field} does not reference an existing record")
            if field == "tested_at":
                value = _parse_date(value)
            if field == "report_url" and (not value or not str(value).strip()):
                abort(400, description="report_url cannot be empty")
            setattr(r, field, value)

    db.session.commit()
    # If the rating was reassigned to a different supplement, reindex both the
    # old and new homes so the old supplement's score also reflects the loss.
    _reindex_supplement_with_group(r.supplement_id)
    if old_supplement_id and old_supplement_id != r.supplement_id:
        _reindex_supplement_with_group(old_supplement_id)
    after = {k: getattr(r, k) for k in WRITABLE_FIELDS}
    # Convert dates to strings for JSON-serializable diff.
    def _norm(v):
        return v.isoformat() if isinstance(v, date) else v
    before = {k: _norm(v) for k, v in before.items()}
    after = {k: _norm(v) for k, v in after.items()}
    log_action("UPDATE", entity_type="rating", entity_id=r.id,
               summary=f"Updated rating {r.id}", changes=diff_changes(before, after))
    return jsonify(_serialize(r))


@admin_ratings_bp.route("/<int:rating_id>", methods=["DELETE"])
@require_superadmin
def delete_rating(rating_id):
    r = Rating.query.get_or_404(rating_id)
    supplement_id = r.supplement_id
    summary = f"Deleted rating from source {r.source_id} for supplement {r.supplement_id}"
    db.session.delete(r)
    db.session.commit()
    _reindex_supplement_with_group(supplement_id)
    log_action("DELETE", entity_type="rating", entity_id=rating_id, summary=summary)
    return jsonify({"ok": True})
