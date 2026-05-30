from flask import Blueprint, jsonify
from sqlalchemy import func, distinct, select
from datetime import datetime, timedelta

from ...extensions import db
from ...models import (
    Supplement, Brand, Category, Source, Rating,
    SupplementImage, AdminUser, AdminAuditLog,
)
from ...admin_auth import login_required


admin_dashboard_bp = Blueprint("admin_dashboard", __name__)


@admin_dashboard_bp.route("/stats", methods=["GET"])
@login_required
def stats():
    """All counts an admin needs at a glance — totals + visible/hidden split."""
    total_supplements = db.session.query(func.count(Supplement.id)).scalar() or 0
    published_supplements = (db.session.query(func.count(Supplement.id))
                             .filter(Supplement.is_published.is_(True))
                             .scalar() or 0)
    featured_supplements = (db.session.query(func.count(Supplement.id))
                            .filter(Supplement.is_featured.is_(True))
                            .scalar() or 0)

    total_brands = db.session.query(func.count(Brand.id)).scalar() or 0
    active_brands = (db.session.query(func.count(Brand.id))
                     .filter(Brand.is_active.is_(True)).scalar() or 0)

    total_categories = db.session.query(func.count(Category.id)).scalar() or 0
    active_categories = (db.session.query(func.count(Category.id))
                         .filter(Category.is_active.is_(True)).scalar() or 0)

    total_sources = db.session.query(func.count(Source.id)).scalar() or 0
    active_sources = (db.session.query(func.count(Source.id))
                      .filter(Source.is_active.is_(True)).scalar() or 0)

    total_ratings = db.session.query(func.count(Rating.id)).scalar() or 0
    total_images = db.session.query(func.count(SupplementImage.id)).scalar() or 0
    total_admin_users = db.session.query(func.count(AdminUser.id)).scalar() or 0

    # Supplements with no rating from any active source — likely needs attention.
    rated_supp_ids = (
        select(distinct(Rating.supplement_id))
        .select_from(Rating)
        .join(Source, Source.id == Rating.source_id)
        .where(Source.is_active.is_(True))
    )
    unrated_count = (db.session.query(func.count(Supplement.id))
                     .filter(~Supplement.id.in_(rated_supp_ids))
                     .scalar() or 0)

    # Activity this week.
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    recent_activity = (db.session.query(func.count(AdminAuditLog.id))
                       .filter(AdminAuditLog.created_at >= one_week_ago)
                       .scalar() or 0)
    new_supplements_week = (db.session.query(func.count(Supplement.id))
                            .filter(Supplement.created_at >= one_week_ago)
                            .scalar() or 0)

    return jsonify({
        "supplements": {
            "total": total_supplements,
            "published": published_supplements,
            "unpublished": total_supplements - published_supplements,
            "featured": featured_supplements,
            "unrated": unrated_count,
            "new_this_week": new_supplements_week,
        },
        "brands": {"total": total_brands, "active": active_brands, "inactive": total_brands - active_brands},
        "categories": {"total": total_categories, "active": active_categories, "inactive": total_categories - active_categories},
        "sources": {"total": total_sources, "active": active_sources, "inactive": total_sources - active_sources},
        "ratings": {"total": total_ratings},
        "images": {"total": total_images},
        "admin_users": {"total": total_admin_users},
        "activity": {"audit_events_this_week": recent_activity},
    })


@admin_dashboard_bp.route("/recent-activity", methods=["GET"])
@login_required
def recent_activity():
    """Last 20 audit events. Cheap fetch for the dashboard feed."""
    items = (AdminAuditLog.query
             .order_by(AdminAuditLog.created_at.desc())
             .limit(20)
             .all())
    return jsonify({"items": [a.to_dict() for a in items]})
