from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON

from ..extensions import db


JsonType = JSON().with_variant(JSONB(), "postgresql")


def _utcnow():
    return datetime.now(timezone.utc)


# Event taxonomy. New types must be added here AND on the public tracker so the
# /api/track/event validator accepts them.
EVENT_PAGE_VIEW = "page_view"
EVENT_SEARCH = "search"
EVENT_SUPPLEMENT_VIEW = "supplement_view"
EVENT_BRAND_VIEW = "brand_view"
EVENT_CATEGORY_VIEW = "category_view"
EVENT_COMPARE = "compare"
EVENT_OUTBOUND_CLICK = "outbound_click"

EVENT_TYPES = {
    EVENT_PAGE_VIEW, EVENT_SEARCH, EVENT_SUPPLEMENT_VIEW, EVENT_BRAND_VIEW,
    EVENT_CATEGORY_VIEW, EVENT_COMPARE, EVENT_OUTBOUND_CLICK,
}


class VisitorSession(db.Model):
    """One row per browser session (30-min sliding inactivity window).

    `visitor_id` is a UUID stored client-side in the `hm_visitor` cookie so the
    same human across sessions counts as one unique visitor. `is_bot` is set at
    creation from UA classification — bot sessions are stored for SEO insight
    but excluded from "active visitors" / DAU.
    """
    __tablename__ = "visitor_sessions"

    id = db.Column(db.Integer, primary_key=True)
    session_uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)
    visitor_id = db.Column(db.String(36), nullable=False, index=True)

    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    page_view_count = db.Column(db.Integer, nullable=False, default=0)
    event_count = db.Column(db.Integer, nullable=False, default=0)

    # Source / device metadata captured once at session start.
    entry_path = db.Column(db.String(500))
    referrer_domain = db.Column(db.String(160), index=True)
    device_type = db.Column(db.String(20), index=True)   # mobile | tablet | desktop | bot | unknown
    browser = db.Column(db.String(40))                    # Chrome | Safari | Firefox | Edge | other
    os = db.Column(db.String(40))                         # iOS | Android | macOS | Windows | Linux | other

    ip_hash = db.Column(db.String(64), index=True)        # sha256(truncated_ip + salt) — never raw
    country = db.Column(db.String(2))                     # nullable; populated later if geo lookup is wired

    is_bot = db.Column(db.Boolean, nullable=False, default=False, index=True)

    def to_dict(self) -> dict:
        def _utc(dt):
            if not dt:
                return None
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        duration = None
        if self.started_at and self.last_seen_at:
            duration = int((self.last_seen_at - self.started_at).total_seconds())
        return {
            "id": self.id,
            "session_uuid": self.session_uuid,
            "visitor_id": self.visitor_id,
            "started_at": _utc(self.started_at),
            "last_seen_at": _utc(self.last_seen_at),
            "duration_seconds": duration,
            "page_view_count": self.page_view_count,
            "event_count": self.event_count,
            "entry_path": self.entry_path,
            "referrer_domain": self.referrer_domain,
            "device_type": self.device_type,
            "browser": self.browser,
            "os": self.os,
            "country": self.country,
            "is_bot": self.is_bot,
        }


class VisitorEvent(db.Model):
    """Append-only event stream. One row per tracked action.

    `entity_type` + `entity_id` let us aggregate "top supplements / brands /
    categories" without joining through path parsing. `meta` stores per-event
    extras (search query, outbound URL, etc.) — kept small.
    """
    __tablename__ = "visitor_events"

    id = db.Column(db.BigInteger, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("visitor_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    visitor_id = db.Column(db.String(36), nullable=False, index=True)

    event_type = db.Column(db.String(30), nullable=False, index=True)
    path = db.Column(db.String(500), index=True)
    entity_type = db.Column(db.String(40), index=True)   # supplement | brand | category
    entity_id = db.Column(db.String(40), index=True)     # str so slugs work too
    referrer = db.Column(db.String(500))                  # full referrer when first hit; nullable

    # Stored as `search_query` because `query` would shadow Flask-SQLAlchemy's
    # Model.query manager — accessing VisitorEvent.query would return this column
    # descriptor instead of the query interface, breaking ORM operations.
    search_query = db.Column("search_query", db.String(200))
    meta = db.Column(JsonType)                            # outbound_url, etc.

    occurred_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    __table_args__ = (
        db.Index("ix_visitor_events_occurred_event", "occurred_at", "event_type"),
        db.Index("ix_visitor_events_entity", "entity_type", "entity_id"),
    )

    def to_dict(self) -> dict:
        ts = self.occurred_at
        if ts and ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return {
            "id": self.id,
            "session_id": self.session_id,
            "visitor_id": self.visitor_id,
            "event_type": self.event_type,
            "path": self.path,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "referrer": self.referrer,
            "query": self.search_query,
            "meta": self.meta,
            "occurred_at": ts.isoformat() if ts else None,
        }


class RateLimitHit(db.Model):
    """One row per 429 rejected by Flask-Limiter, anywhere in the API.

    Separate from VisitorEvent because the request never reaches the visitor-
    tracking layer (no cookies, no session, no UA classification done). We
    deliberately store only the IP hash so we can detect abuse patterns
    without retaining raw IPs.
    """
    __tablename__ = "rate_limit_hits"

    id = db.Column(db.BigInteger, primary_key=True)
    ip_hash = db.Column(db.String(64), index=True)
    path = db.Column(db.String(500), index=True)
    method = db.Column(db.String(10))
    user_agent = db.Column(db.String(255))
    occurred_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    def to_dict(self) -> dict:
        ts = self.occurred_at
        if ts and ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return {
            "id": self.id,
            "ip_hash": self.ip_hash,
            "path": self.path,
            "method": self.method,
            "user_agent": self.user_agent,
            "occurred_at": ts.isoformat() if ts else None,
        }
