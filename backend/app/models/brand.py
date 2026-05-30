from datetime import datetime
from ..extensions import db


class Brand(db.Model):
    """Supplement manufacturer / brand (e.g., Nordic Naturals, NOW Foods, Thorne)."""
    __tablename__ = "brands"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    slug = db.Column(db.String(140), nullable=False, unique=True, index=True)
    website_url = db.Column(db.String(500))
    logo_url = db.Column(db.String(500))
    description = db.Column(db.Text)
    country = db.Column(db.String(60))
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    supplements = db.relationship("Supplement", back_populates="brand", lazy="dynamic")

    @property
    def active_supplement_count(self) -> int:
        from .supplement import Supplement
        return (Supplement.query
                .filter(Supplement.brand_id == self.id, Supplement.is_published.is_(True))
                .count())

    def to_dict(self, include_count=False):
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "website_url": self.website_url,
            "logo_url": self.logo_url,
            "description": self.description,
            "country": self.country,
            "is_active": self.is_active,
        }
        if include_count:
            data["supplement_count"] = self.active_supplement_count
        return data
