from flask import Blueprint, jsonify, abort

from ..models import Brand

brands_bp = Blueprint("brands", __name__)


@brands_bp.route("", methods=["GET"])
def list_brands():
    brands = (Brand.query
              .filter(Brand.is_active.is_(True))
              .order_by(Brand.name)
              .all())
    return jsonify({"items": [b.to_dict(include_count=True) for b in brands]})


@brands_bp.route("/<slug>", methods=["GET"])
def get_brand(slug):
    brand = Brand.query.filter_by(slug=slug).first()
    if not brand or not brand.is_active:
        abort(404, description=f"Brand '{slug}' not found")
    return jsonify(brand.to_dict(include_count=True))
