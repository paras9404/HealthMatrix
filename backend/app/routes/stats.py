from flask import Blueprint, jsonify
from sqlalchemy import distinct, func

from ..extensions import db
from ..models import Supplement, Source, Brand, Category, Rating

stats_bp = Blueprint("stats", __name__)


@stats_bp.route("", methods=["GET"])
def site_stats():
    """Live counts used by the homepage hero. Everything respects is_active flags.

    'supplements' = published + active brand + active category + ≥1 rating from
    an active source. Matches the supplements list visibility rule so the hero
    stat never overstates what users can actually browse — and reflects only
    products that have been *rated* by an active lab (the hero label is
    'supplements rated', not 'supplements catalogued')."""
    visible_supplements = (
        db.session.query(func.count(distinct(Supplement.id)))
        .join(Brand, Brand.id == Supplement.brand_id)
        .join(Category, Category.id == Supplement.category_id)
        .join(Rating, Rating.supplement_id == Supplement.id)
        .join(Source, Source.id == Rating.source_id)
        .filter(Supplement.is_published.is_(True),
                Brand.is_active.is_(True),
                Category.is_active.is_(True),
                Source.is_active.is_(True))
        .scalar() or 0
    )

    active_sources_with_data = (
        db.session.query(func.count(distinct(Source.id)))
        .join(Rating, Rating.source_id == Source.id)
        .filter(Source.is_active.is_(True))
        .scalar() or 0
    )

    active_sources_total = Source.query.filter(Source.is_active.is_(True)).count()
    active_brands = Brand.query.filter(Brand.is_active.is_(True)).count()
    active_categories = Category.query.filter(Category.is_active.is_(True)).count()

    return jsonify({
        "supplements": visible_supplements,
        "sources_with_data": active_sources_with_data,
        "sources_total": active_sources_total,
        "brands": active_brands,
        "categories": active_categories,
    })
