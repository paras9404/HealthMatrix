from datetime import datetime
from ..extensions import db


class Source(db.Model):
    """A testing/rating platform — Labdoor, ConsumerLab, NSF, USP, Trustified, Informed Sport, etc."""
    __tablename__ = "sources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    slug = db.Column(db.String(140), nullable=False, unique=True, index=True)
    website_url = db.Column(db.String(500), nullable=False)
    logo_url = db.Column(db.String(500))
    description = db.Column(db.Text)
    rating_scale = db.Column(db.String(60), default="0-100", nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    ratings = db.relationship("Rating", back_populates="source", lazy="dynamic")

    @property
    def active_supplement_count(self) -> int:
        """Distinct supplements rated by this source that are currently visible
        (published + brand active + category active)."""
        from .brand import Brand
        from .category import Category
        from .supplement import Supplement
        from .rating import Rating
        from sqlalchemy import distinct, func
        from ..extensions import db
        return (db.session.query(func.count(distinct(Supplement.id)))
                .select_from(Rating)
                .join(Supplement, Supplement.id == Rating.supplement_id)
                .join(Brand, Brand.id == Supplement.brand_id)
                .join(Category, Category.id == Supplement.category_id)
                .filter(Rating.source_id == self.id,
                        Supplement.is_published.is_(True),
                        Brand.is_active.is_(True),
                        Category.is_active.is_(True))
                .scalar() or 0)

    def to_dict(self, include_count=False):
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "website_url": self.website_url,
            "logo_url": self.logo_url,
            "description": self.description,
            "rating_scale": self.rating_scale,
            "is_verified": self.is_verified,
            "is_active": self.is_active,
        }
        if include_count:
            data["supplement_count"] = self.active_supplement_count
        return data
