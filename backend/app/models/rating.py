from datetime import datetime
from sqlalchemy import CheckConstraint
from ..extensions import db


class Rating(db.Model):
    """A rating of a supplement from a specific testing source."""
    __tablename__ = "ratings"
    __table_args__ = (
        db.UniqueConstraint("supplement_id", "source_id", name="uq_supplement_source"),
        CheckConstraint("score IS NULL OR score >= 0", name="ck_rating_score_min"),
        CheckConstraint("max_score IS NULL OR max_score > 0", name="ck_rating_max_score_positive"),
        CheckConstraint("score IS NULL OR max_score IS NULL OR score <= max_score",
                        name="ck_rating_score_within_max"),
        db.Index("ix_rating_source_score", "source_id", "score"),
    )

    id = db.Column(db.Integer, primary_key=True)
    supplement_id = db.Column(
        db.Integer,
        db.ForeignKey("supplements.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id = db.Column(
        db.Integer,
        db.ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )

    score = db.Column(db.Float)
    max_score = db.Column(db.Float, default=100.0, nullable=False)
    verdict = db.Column(db.String(60))
    summary = db.Column(db.Text)
    report_url = db.Column(db.String(500), nullable=False)
    buy_url = db.Column(db.String(500))
    tested_at = db.Column(db.Date)
    batch_no = db.Column(db.String(80))                    # batch number tested (e.g., JJGWCF0001)
    manufacturing_date = db.Column(db.String(40))           # raw string — formats vary across labs
    expiration_date = db.Column(db.String(40))              # raw string
    tested_by = db.Column(db.String(80))                    # external lab (e.g., Eurofins)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    supplement = db.relationship("Supplement", back_populates="ratings")
    source = db.relationship("Source", back_populates="ratings")

    @property
    def normalized_score(self):
        """Score normalized to a 0-100 scale for cross-source comparison."""
        if self.score is None or self.max_score is None or self.max_score == 0:
            return None
        return (self.score / self.max_score) * 100

    def to_dict(self):
        return {
            "id": self.id,
            "score": self.score,
            "max_score": self.max_score,
            "normalized_score": round(self.normalized_score, 1) if self.normalized_score is not None else None,
            "verdict": self.verdict,
            "summary": self.summary,
            "report_url": self.report_url,
            "buy_url": self.buy_url,
            "tested_at": self.tested_at.isoformat() if self.tested_at else None,
            "batch_no": self.batch_no,
            "manufacturing_date": self.manufacturing_date,
            "expiration_date": self.expiration_date,
            "tested_by": self.tested_by,
            "source": self.source.to_dict() if self.source else None,
        }
