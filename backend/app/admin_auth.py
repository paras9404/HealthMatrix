"""Admin authentication: token issuance, request authentication, and role-based decorators.

Uses itsdangerous.URLSafeTimedSerializer (already a Flask dependency) for signed
bearer tokens — no extra packages needed. Tokens encode the admin_user_id and a
short stable check value (password_hash prefix) so changing a password invalidates
existing tokens, and embed an issue timestamp for expiry.
"""
from functools import wraps
from datetime import datetime, timezone
from typing import Optional

from flask import current_app, request, g, jsonify
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from .extensions import db
from .models import AdminUser, AdminAuditLog
from .models.admin_user import ROLE_READONLY, ROLE_EDITOR, ROLE_SUPERADMIN


# 12 hours by default — long enough to be useful, short enough to be safe.
TOKEN_TTL_SECONDS = 12 * 60 * 60
TOKEN_SALT = "healthmatrix-admin-token"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)


def issue_token(user: AdminUser) -> dict:
    """Mint a signed bearer token for `user`. Embeds a password_hash prefix so a
    password change invalidates issued tokens."""
    pw_check = (user.password_hash or "")[-12:]
    payload = {"uid": user.id, "u": user.username, "pc": pw_check}
    token = _serializer().dumps(payload)
    return {
        "token": token,
        "expires_in": TOKEN_TTL_SECONDS,
        "user": user.to_dict(),
    }


def authenticate_request() -> Optional[AdminUser]:
    """Read the bearer token from the Authorization header, validate it,
    and return the active AdminUser. Returns None if no/invalid/expired token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):].strip()
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=TOKEN_TTL_SECONDS)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    except Exception:
        return None

    uid = payload.get("uid")
    if not uid:
        return None
    user = AdminUser.query.get(uid)
    if not user or not user.is_active:
        return None
    # Invalidate the token if the password has changed since issue.
    if (user.password_hash or "")[-12:] != payload.get("pc"):
        return None
    return user


def _unauthorized():
    return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401


def _forbidden(message="Insufficient permissions"):
    return jsonify({"error": "Forbidden", "message": message}), 403


def login_required(fn):
    """Require any active admin user. Sets `g.admin_user` for downstream use."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = authenticate_request()
        if not user:
            return _unauthorized()
        g.admin_user = user
        return fn(*args, **kwargs)
    return wrapper


def require_role(min_role: str):
    """Decorator factory: require min_role or higher. Use ROLE_EDITOR for write
    routes and ROLE_SUPERADMIN for delete and user-management routes."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = authenticate_request()
            if not user:
                return _unauthorized()
            if not user.has_permission(min_role):
                return _forbidden(f"Requires '{min_role}' role")
            g.admin_user = user
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# Convenience aliases.
require_editor = require_role(ROLE_EDITOR)
require_superadmin = require_role(ROLE_SUPERADMIN)


def log_action(action: str, entity_type: Optional[str] = None,
               entity_id=None, summary: Optional[str] = None,
               changes: Optional[dict] = None) -> None:
    """Record an admin action to the audit log. Best-effort; failures are swallowed
    so logging can't break the actual operation."""
    try:
        user = getattr(g, "admin_user", None)
        log = AdminAuditLog(
            admin_user_id=user.id if user else None,
            admin_username=user.username if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            summary=summary,
            changes=changes,
            ip_address=(request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:45],
            user_agent=(request.headers.get("User-Agent") or "")[:255],
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def diff_changes(before: dict, after: dict) -> dict:
    """Return only fields whose values differ between before/after, as {field: [old, new]}."""
    out = {}
    for k, new_v in after.items():
        old_v = before.get(k)
        if old_v != new_v:
            out[k] = [old_v, new_v]
    return out


def touch_login(user: AdminUser) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()
