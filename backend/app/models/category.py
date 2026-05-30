from datetime import datetime
from ..extensions import db


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    icon = db.Column(db.String(50))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    supplements = db.relationship("Supplement", back_populates="category", lazy="dynamic")

    @property
    def active_supplement_count(self) -> int:
        """Count of supplements in this category that are visible to end users
        (published + parent brand active + has ≥1 rating from an active source, or
        is unrated). Mirrors the visibility filter in the listing API so the sidebar
        count matches what actually appears when the category filter is applied."""
        from sqlalchemy import exists, and_, or_
        from .brand import Brand
        from .supplement import Supplement
        from .rating import Rating
        from .source import Source
        has_any_rating = exists().where(Rating.supplement_id == Supplement.id)
        has_active_source_rating = exists().where(and_(
            Rating.supplement_id == Supplement.id,
            Rating.source_id == Source.id,
            Source.is_active.is_(True),
        ))
        return (Supplement.query
                .join(Brand, Brand.id == Supplement.brand_id)
                .filter(Supplement.category_id == self.id,
                        Supplement.is_published.is_(True),
                        Brand.is_active.is_(True),
                        or_(~has_any_rating, has_active_source_rating))
                .count())

    def to_dict(self, include_count=False):
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "icon": self.icon,
            "is_active": self.is_active,
        }
        if include_count:
            data["supplement_count"] = self.active_supplement_count
        return data
