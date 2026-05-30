from datetime import datetime
from sqlalchemy import CheckConstraint, Index
from ..extensions import db


class SupplementImage(db.Model):
    """A single image in a supplement's image gallery.

    Each supplement can have multiple images: main product shot, ingredients
    panel, nutrition facts, back of package, etc. Frontend displays them as
    a swipeable carousel."""
    __tablename__ = "supplement_images"
    __table_args__ = (
        CheckConstraint(
            "image_type IN ('main', 'ingredients', 'nutrition_facts', 'back', 'side', 'box', 'label', 'lifestyle', 'other')",
            name="ck_image_type",
        ),
        Index("ix_supplement_images_supplement", "supplement_id", "display_order"),
        Index("ix_supplement_images_type", "image_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    supplement_id = db.Column(
        db.Integer,
        db.ForeignKey("supplements.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_path = db.Column(db.String(500))
    image_url = db.Column(db.String(500))
    image_source = db.Column(db.String(60))
    image_type = db.Column(db.String(40), nullable=False, default="main")
    display_order = db.Column(db.Integer, nullable=False, default=0)
    alt_text = db.Column(db.String(200))
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    supplement = db.relationship("Supplement", back_populates="images")

    @property
    def url(self):
        """Resolved URL: locally hosted file if available, else the remote URL."""
        if self.image_path:
            return f"/static/images/supplements/{self.image_path}"
        return self.image_url

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "type": self.image_type,
            "order": self.display_order,
            "alt": self.alt_text,
            "source": self.image_source,
        }
