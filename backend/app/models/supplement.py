import re
from datetime import datetime
from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from ..extensions import db


_FORM_PLURALS = {
    "tablet": "tablets",
    "capsule": "capsules",
    "softgel": "softgels",
    "gummy": "gummies",
    "chewable": "chewables",
    "sachet": "sachets",
    "drop": "drops",
    "lozenge": "lozenges",
    "patch": "patches",
}
_COUNTABLE_FORMS = set(_FORM_PLURALS.keys())


def _format_number(val: float) -> str:
    """Drop trailing zeros: 1.0 -> '1', 1.5 -> '1.5'."""
    if val == int(val):
        return str(int(val))
    return f"{val:g}"


def _normalize_measure(s: str | None) -> str | None:
    """Tidy Amazon weight strings: '1000.0 Grams' -> '1 kg', '0.09 Kilograms' -> '90 g'.
    Returns the original string unchanged if the unit isn't recognized."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^([\d.]+)\s*(.+?)\.?$", s)
    if not m:
        return s
    try:
        val = float(m.group(1))
    except ValueError:
        return s
    unit = m.group(2).strip().lower()
    if unit in ("grams", "gram", "g"):
        if val >= 1000:
            return f"{_format_number(val / 1000)} kg"
        return f"{_format_number(val)} g"
    if unit in ("kilograms", "kilogram", "kgs", "kg"):
        if val < 1:
            return f"{_format_number(val * 1000)} g"
        return f"{_format_number(val)} kg"
    if unit in ("ounces", "ounce", "oz"):
        return f"{_format_number(val)} oz"
    if "fluid" in unit:
        return f"{_format_number(val)} fl oz"
    if unit in ("milliliters", "milliliter", "ml"):
        return f"{_format_number(val)} ml"
    if unit in ("liters", "liter", "l"):
        return f"{_format_number(val)} L"
    if unit in ("pounds", "pound", "lb", "lbs"):
        return f"{_format_number(val)} lb"
    return s


def _parse_count(unit_count: str | None) -> int | None:
    """'60.00 Count' / '60 Count' -> 60. Anything else (weight/volume) -> None."""
    if not unit_count:
        return None
    m = re.match(r"^([\d.]+)\s*Count$", unit_count.strip(), re.IGNORECASE)
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except ValueError:
        return None


def _pluralize_form(form: str | None) -> str | None:
    if not form:
        return None
    return _FORM_PLURALS.get(form.lower().strip())


def _derive_size(amazon_data) -> str | None:
    """Single human-readable size string for the product card.

    Capsules/tablets/gummies → '60 capsules'. Powders/liquids → cleaned weight ('1 kg').
    Returns None when Amazon data is missing or unparseable."""
    if not amazon_data:
        return None
    specs = (amazon_data.get("specs") or {}) if isinstance(amazon_data, dict) else {}
    form = (specs.get("Item Form") or "").strip()
    unit_count = specs.get("Unit Count")
    item_weight = specs.get("Item Weight")

    count = _parse_count(unit_count)
    plural = _pluralize_form(form)
    if count and plural and form.lower() in _COUNTABLE_FORMS:
        return f"{count} {plural}"

    cleaned_weight = _normalize_measure(item_weight)
    if cleaned_weight:
        return cleaned_weight

    # Fall through: maybe Unit Count is itself a weight string ('1000.0 Grams')
    if unit_count and not count:
        return _normalize_measure(unit_count)

    return None


def _clean_price(price: str | None) -> str | None:
    """'INR734.22' -> '₹734.22'. Empty/whitespace -> None."""
    if not price:
        return None
    s = str(price).strip()
    if not s:
        return None
    if s.upper().startswith("INR"):
        return "₹" + s[3:].lstrip()
    return s


def _derive_servings(amazon_data) -> int | None:
    if not amazon_data:
        return None
    specs = (amazon_data.get("specs") or {}) if isinstance(amazon_data, dict) else {}
    raw = specs.get("Total Servings Per Container") or specs.get("Servings per Container")
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return None


class SupplementAlias(db.Model):
    """Records slugs that previously pointed to a Supplement before it was merged.
    Preserves URL stability across deduplication runs — visitors arriving at an old
    slug get served the canonical supplement instead of a 404."""
    __tablename__ = "supplement_aliases"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(250), nullable=False, unique=True, index=True)
    supplement_id = db.Column(
        db.Integer,
        db.ForeignKey("supplements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class Supplement(db.Model):
    __tablename__ = "supplements"
    __table_args__ = (
        CheckConstraint("price_range IN ('$', '$$', '$$$', '$$$$') OR price_range IS NULL",
                        name="ck_supplement_price_range"),
        CheckConstraint("form IN ('Capsule', 'Tablet', 'Softgel', 'Powder', 'Liquid', 'Gummy', 'Drop', 'Other') OR form IS NULL",
                        name="ck_supplement_form"),
        Index("ix_supplement_brand_category", "brand_id", "category_id"),
        Index("ix_supplement_featured_created", "is_featured", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    # 500 char width is large enough to hold Amazon's marketing-style titles
    # (e.g. "Brand X 30g Plant Protein | Supports Muscle Growth & Recovery | …")
    # which routinely exceed 200 chars. The image-validation tool overwrites
    # name with the Amazon title on import so the catalog matches the listing.
    name = db.Column(db.String(500), nullable=False, index=True)
    slug = db.Column(db.String(250), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))            # Remote / fallback URL
    image_path = db.Column(db.String(500))            # Local filename in /static/images/supplements/
    image_source = db.Column(db.String(60))           # Where the image came from (e.g., "manufacturer", "dsld", "unsplash")
    ingredients = db.Column(db.Text)
    serving_size = db.Column(db.String(100))
    form = db.Column(db.String(20))
    price_range = db.Column(db.String(4))
    dsld_id = db.Column(db.String(40), index=True)    # NIH DSLD product ID for cross-reference
    upc = db.Column(db.String(20), index=True)        # Universal Product Code (barcode)

    # Amazon listing reference. Lets us re-fetch images / pricing / specs in the
    # future without losing the link a human admin originally vetted.
    amazon_url = db.Column(db.String(500))
    amazon_asin = db.Column(db.String(20), index=True)
    # Snapshot of Amazon product info — title, price, brand, spec key/value pairs,
    # bullet list, and fetched_at. JSONB so we can extend without schema churn.
    amazon_data = db.Column(JSONB)
    # Cached candidates from the auto-search step (top results across .in/.com
    # with their thumbnails + scores). Populated by the bulk-search job so that
    # opening a product in the validation tool is instant — no live search.
    amazon_candidates = db.Column(JSONB)
    amazon_searched_at = db.Column(db.DateTime(timezone=True))

    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Optional pointer to a ProductGroup that bundles this supplement with its sibling
    # variants (different flavor / pack size of the same product). SET NULL on group
    # deletion so ungrouping doesn't cascade into the supplement rows.
    product_group_id = db.Column(db.Integer,
                                 db.ForeignKey("product_groups.id", ondelete="SET NULL"),
                                 nullable=True, index=True)
    # Short label that distinguishes this variant within its group, e.g.
    # "4Kg Double Rich Chocolate" or "1kg Kesar Kulfi". Free-form; admin-edited.
    variant_label = db.Column(db.String(200))

    is_featured = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_published = db.Column(db.Boolean, default=True, nullable=False, index=True)

    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    brand = db.relationship("Brand", back_populates="supplements")
    category = db.relationship("Category", back_populates="supplements")
    product_group = db.relationship(
        "ProductGroup",
        primaryjoin="Supplement.product_group_id == ProductGroup.id",
        foreign_keys=[product_group_id],
        back_populates="members",
    )
    ratings = db.relationship(
        "Rating",
        back_populates="supplement",
        lazy="dynamic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    images = db.relationship(
        "SupplementImage",
        back_populates="supplement",
        order_by="SupplementImage.display_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def visible_ratings(self):
        """Ratings whose source is currently active. Aggregate score uses these only."""
        return [r for r in self.ratings.all() if r.source and r.source.is_active]

    @property
    def aggregate_score(self):
        normalized = [r.normalized_score for r in self.visible_ratings if r.normalized_score is not None]
        if not normalized:
            return None
        return round(sum(normalized) / len(normalized), 1)

    @property
    def review_count(self):
        return len(self.visible_ratings)

    @property
    def is_visible(self) -> bool:
        """Frontend visibility = published AND brand active AND category active AND
        (unrated OR ≥1 rating from an active source). A supplement whose only ratings
        come from hidden sources is treated as not visible — otherwise the detail page
        would render with '0 labs' even though the data exists in the database."""
        if not (self.is_published
                and (self.brand is None or self.brand.is_active)
                and (self.category is None or self.category.is_active)):
            return False
        all_ratings = self.ratings.all()
        if not all_ratings:
            return True
        return any(r.source and r.source.is_active for r in all_ratings)

    @property
    def image(self):
        """Resolve primary image: prefer first gallery image, then legacy single image."""
        if self.images:
            return self.images[0].url
        if self.image_path:
            return f"/static/images/supplements/{self.image_path}"
        return self.image_url

    @property
    def gallery(self):
        """Ordered list of all images (main first, then ingredients/back/etc.).
        Falls back to the legacy single image if no gallery rows exist."""
        if self.images:
            return [img.to_dict() for img in self.images]
        if self.image_path or self.image_url:
            url = (f"/static/images/supplements/{self.image_path}"
                   if self.image_path else self.image_url)
            return [{
                "id": None,
                "url": url,
                "type": "main",
                "order": 0,
                "alt": self.name,
                "source": self.image_source,
            }]
        return []

    def to_dict(self, include_ratings=False):
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "image": self.image,
            "images": self.gallery,
            "image_source": self.image_source,
            "ingredients": self.ingredients,
            "serving_size": self.serving_size,
            "form": self.form,
            "price_range": self.price_range,
            "price": _clean_price((self.amazon_data or {}).get("price")),
            "size": _derive_size(self.amazon_data),
            "servings": _derive_servings(self.amazon_data),
            "dsld_id": self.dsld_id,
            "upc": self.upc,
            "brand": self.brand.to_dict() if self.brand else None,
            "category": self.category.to_dict() if self.category else None,
            "product_group_id": self.product_group_id,
            "variant_label": self.variant_label,
            "is_featured": self.is_featured,
            "aggregate_score": self.aggregate_score,
            "review_count": self.review_count,
        }
        if include_ratings:
            data["ratings"] = [r.to_dict() for r in self.visible_ratings]
        return data

    def to_public_dict(self, include_ratings: bool = False) -> dict:
        """Public-facing serializer that collapses ProductGroup variants into one card.

        - Ungrouped supplement: identical to to_dict().
        - Grouped supplement (when serialized as the group's PRIMARY): merges all
          variants' ratings/review counts, and exposes a `variants` list so the
          detail page can render a flavor / pack-size selector.
        - Grouped supplement that is NOT the primary: same data is returned, but
          callers should generally not be serializing non-primary variants in the
          listing — the listing endpoint filters them out before reaching here.
        """
        base = self.to_dict(include_ratings=False)
        group = self.product_group
        if not group:
            if include_ratings:
                base["ratings"] = [r.to_dict() for r in self.visible_ratings]
            return base

        # Pull the variants once so we don't trigger N queries below.
        variants = group.members.all()
        # Merged ratings: every visible rating from every variant. Each rating
        # gets a `variant_label` / `variant_slug` hint so the UI can label
        # "Labdoor (4Kg Double Rich Chocolate)" if it wants.
        merged = []
        for v in variants:
            for r in v.visible_ratings:
                rd = r.to_dict()
                rd["variant_id"] = v.id
                rd["variant_slug"] = v.slug
                rd["variant_label"] = v.variant_label or v.name
                merged.append(rd)

        # Dedupe by source slug — when multiple variants share the same source
        # rating (e.g., two flavors both tested by Trustified) the public page
        # only needs one entry. Keep the highest normalized_score (a tie picks
        # the rating with a non-null tested_at; otherwise the first encounter).
        deduped: dict[str, dict] = {}
        for r in merged:
            src = r.get("source") or {}
            slug = src.get("slug") or src.get("id") or "(unknown)"
            existing = deduped.get(slug)
            if existing is None:
                deduped[slug] = r
                continue
            new_score = r.get("normalized_score")
            old_score = existing.get("normalized_score")
            # Treat None as -1 so any real score wins over a missing one.
            new_rank = new_score if new_score is not None else -1
            old_rank = old_score if old_score is not None else -1
            if new_rank > old_rank:
                deduped[slug] = r
            elif new_rank == old_rank:
                # Tiebreaker: prefer the rating with a tested_at date.
                if r.get("tested_at") and not existing.get("tested_at"):
                    deduped[slug] = r
        merged = list(deduped.values())

        normalized = [r["normalized_score"] for r in merged
                      if r.get("normalized_score") is not None]
        base["aggregate_score"] = (
            round(sum(normalized) / len(normalized), 1) if normalized else None
        )
        base["review_count"] = len(merged)
        base["product_group"] = {
            "id": group.id,
            "name": group.name,
            "slug": group.slug,
            "primary_supplement_id": group.primary_supplement_id,
            "variants": [
                {
                    "id": v.id,
                    "name": v.name,
                    "slug": v.slug,
                    "image": v.image,
                    "variant_label": v.variant_label,
                    "is_primary": v.id == group.primary_supplement_id,
                    "aggregate_score": v.aggregate_score,
                    "review_count": v.review_count,
                    "size": _derive_size(v.amazon_data),
                    "price": _clean_price((v.amazon_data or {}).get("price")),
                }
                for v in variants
            ],
        }
        # The card's "headline" should reflect the canonical product line, not
        # whichever variant happens to be primary in the DB. Override only when the
        # group has a description filled in — otherwise keep the supplement's own.
        base["name"] = group.name
        if group.description:
            base["description"] = group.description
        if include_ratings:
            base["ratings"] = merged
        return base
