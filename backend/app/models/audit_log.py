from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON

from ..extensions import db


# Use JSONB on Postgres, fall back to JSON on SQLite (testing).
JsonType = JSON().with_variant(JSONB(), "postgresql")


def _utcnow():
    """Timezone-aware UTC. Required for DateTime(timezone=True) columns —
    naive datetimes get interpreted in the Postgres session timezone."""
    return datetime.now(timezone.utc)


class AdminAuditLog(db.Model):
    """Append-only log of admin actions. Visible to superadmins."""
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(
        db.Integer,
        db.ForeignKey("admin_users.id", ondelete="SET NULL"),
        index=True,
    )
    admin_username = db.Column(db.String(80), index=True)  # snapshot — survives user deletion
    action = db.Column(db.String(40), nullable=False, index=True)  # CREATE, UPDATE, DELETE, LOGIN, LOGIN_FAILED, LOGOUT
    entity_type = db.Column(db.String(40), index=True)             # supplement, brand, category, ...
    entity_id = db.Column(db.String(40), index=True)               # store as str so we can use slug for entities w/o numeric id
    summary = db.Column(db.String(255))                            # human-readable one-liner
    changes = db.Column(JsonType)                                  # {field: [before, after]} for UPDATE; full payload for CREATE
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    def to_dict(self) -> dict:
        # Always serialize as UTC — clients render in the user's local timezone.
        ts = self.created_at
        if ts and ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return {
            "id": self.id,
            "admin_user_id": self.admin_user_id,
            "admin_username": self.admin_username,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "summary": self.summary,
            "changes": self.changes,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "created_at": ts.isoformat() if ts else None,
        }
