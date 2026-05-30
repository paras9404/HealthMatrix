from flask import Blueprint, jsonify, abort

from ..models import Category

categories_bp = Blueprint("categories", __name__)


@categories_bp.route("", methods=["GET"])
def list_categories():
    cats = (Category.query
            .filter(Category.is_active.is_(True))
            .order_by(Category.sort_order, Category.name)
            .all())
    return jsonify({"items": [c.to_dict(include_count=True) for c in cats]})


@categories_bp.route("/<slug>", methods=["GET"])
def get_category(slug):
    cat = Category.query.filter_by(slug=slug).first()
    if not cat or not cat.is_active:
        abort(404, description=f"Category '{slug}' not found")
    return jsonify(cat.to_dict(include_count=True))
