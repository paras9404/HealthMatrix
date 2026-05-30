from datetime import datetime
from ..extensions import db


class ProductGroup(db.Model):
    """A family of supplement variants that share a product line.

    Two SKUs that are obviously the same product (same brand, same formulation, just
    different flavor or pack size) keep their own Supplement rows — so each can carry
    its own image, UPC, and per-source ratings — but get pinned together under a
    ProductGroup. The public site can then render them as one card with a flavor /
    size selector instead of duplicate-looking listings.

    Constraints
    -----------
    - All members must share `brand_id` and `category_id` (enforced in the admin API,
      not at the DB level — keeps the schema simple even if a brand later adds a
      variant in a different category for some reason).
    - `primary_supplement_id` points at the variant whose name/image is used as the
      group's default. It gets fixed up automatically when the primary is removed.
    """
    __tablename__ = "product_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(500), nullable=False, index=True)
    slug = db.Column(db.String(250), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)

    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id", ondelete="RESTRICT"),
                         nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="RESTRICT"),
                            nullable=False, index=True)
    # SET NULL on delete so removing the canonical variant doesn't blow up the group;
    # the API layer picks a new primary in that case.
    primary_supplement_id = db.Column(db.Integer,
                                      db.ForeignKey("supplements.id", ondelete="SET NULL"),
                                      nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    brand = db.relationship("Brand")
    category = db.relationship("Category")
    primary_supplement = db.relationship("Supplement", foreign_keys=[primary_supplement_id])
    members = db.relationship(
        "Supplement",
        primaryjoin="Supplement.product_group_id == ProductGroup.id",
        foreign_keys="Supplement.product_group_id",
        back_populates="product_group",
        lazy="dynamic",
    )

    @property
    def member_count(self) -> int:
        return self.members.count()

    @property
    def aggregate_review_count(self) -> int:
        """Total ratings across all variants — for the admin summary table."""
        return sum(m.review_count for m in self.members.all())

    @property
    def aggregate_score(self):
        """Mean of variant aggregate_score values, weighted equally per variant.
        None if no variant has any visible rating."""
        scores = [m.aggregate_score for m in self.members.all() if m.aggregate_score is not None]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 1)

    @property
    def all_source_names(self) -> list[str]:
        """Distinct sources providing at least one rating across all variants."""
        names = set()
        for m in self.members.all():
            for r in m.visible_ratings:
                if r.source:
                    names.add(r.source.name)
        return sorted(names)

    def to_dict(self, include_members: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "brand": self.brand.to_dict() if self.brand else None,
            "category": self.category.to_dict() if self.category else None,
            "brand_id": self.brand_id,
            "category_id": self.category_id,
            "primary_supplement_id": self.primary_supplement_id,
            "primary_slug": (self.primary_supplement.slug
                             if self.primary_supplement else None),
            "member_count": self.member_count,
            "aggregate_score": self.aggregate_score,
            "aggregate_review_count": self.aggregate_review_count,
            "sources": self.all_source_names,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_members:
            data["members"] = [
                {
                    "id": m.id,
                    "name": m.name,
                    "slug": m.slug,
                    "variant_label": m.variant_label,
                    "image": m.image,
                    "is_published": m.is_published,
                    "is_primary": m.id == self.primary_supplement_id,
                    "aggregate_score": m.aggregate_score,
                    "review_count": m.review_count,
                    "ratings": [r.to_dict() for r in m.visible_ratings],
                }
                for m in self.members.all()
            ]
        return data
