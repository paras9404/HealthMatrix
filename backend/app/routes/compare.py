from flask import Blueprint, request, jsonify, abort

from ..models import Supplement

compare_bp = Blueprint("compare", __name__)


@compare_bp.route("", methods=["GET"])
def compare():
    slugs_param = request.args.get("slugs", "").strip()
    if not slugs_param:
        abort(400, description="Provide at least 2 supplement slugs via ?slugs=a,b,c")

    slugs = [s.strip() for s in slugs_param.split(",") if s.strip()][:4]
    if len(slugs) < 2:
        abort(400, description="Provide at least 2 supplement slugs to compare")

    items = Supplement.query.filter(Supplement.slug.in_(slugs)).all()
    found = {s.slug: s for s in items if s.is_visible}  # hide inactive products from compare
    ordered = [found[slug].to_dict(include_ratings=True) for slug in slugs if slug in found]

    return jsonify({"items": ordered, "count": len(ordered)})
