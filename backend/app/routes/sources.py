from flask import Blueprint, jsonify

from ..models import Source
from ..utils.cache import cached_view

sources_bp = Blueprint("sources", __name__)


@sources_bp.route("", methods=["GET"])
@cached_view(seconds=300)
def list_sources():
    from flask import request
    include_counts = request.args.get("counts", "").lower() == "true"
    sources = (Source.query
               .filter(Source.is_active.is_(True))
               .order_by(Source.sort_order, Source.name)
               .all())
    return jsonify({"items": [s.to_dict(include_count=include_counts) for s in sources]})
