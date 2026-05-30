from datetime import datetime, timezone
from sqlalchemy import CheckConstraint
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db


def _utcnow():
    """Timezone-aware UTC. Required for DateTime(timezone=True) columns —
    naive datetimes get interpreted in the Postgres session timezone."""
    return datetime.now(timezone.utc)


# Role hierarchy. Each higher role implies all permissions of the ones above it.
ROLE_READONLY = "readonly"     # GET only
ROLE_EDITOR = "editor"         # GET, POST, PUT/PATCH (no DELETE, no user mgmt)
ROLE_SUPERADMIN = "superadmin" # full access incl. DELETE, user management, audit log

ROLES = (ROLE_READONLY, ROLE_EDITOR, ROLE_SUPERADMIN)

# Numeric rank used for role >= role checks.
ROLE_RANK = {ROLE_READONLY: 1, ROLE_EDITOR: 2, ROLE_SUPERADMIN: 3}


class AdminUser(db.Model):
    """A user authorized to access the /api/admin/* control panel."""
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('readonly', 'editor', 'superadmin')",
            name="ck_admin_user_role",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    email = db.Column(db.String(160), unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_READONLY)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    last_login_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    def set_password(self, raw_password: str) -> None:
        if not raw_password or len(raw_password) < 8:
            raise ValueError("Password must be at least 8 characters")
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    def has_permission(self, required_role: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK.get(required_role, 99)

    @property
    def can_write(self) -> bool:
        return self.has_permission(ROLE_EDITOR)

    @property
    def can_delete(self) -> bool:
        return self.has_permission(ROLE_SUPERADMIN)

    def to_dict(self) -> dict:
        # Serialize timestamps as UTC. Clients render them in the user's local tz.
        def _utc(dt):
            if not dt:
                return None
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "last_login_at": _utc(self.last_login_at),
            "created_at": _utc(self.created_at),
        }
