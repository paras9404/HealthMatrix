from flask import Blueprint, request, jsonify, g

from ...extensions import db, limiter
from ...models import AdminUser
from ...admin_auth import (
    issue_token,
    login_required,
    log_action,
    touch_login,
)


admin_auth_bp = Blueprint("admin_auth", __name__)


@admin_auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Bad Request", "message": "username and password are required"}), 400

    user = AdminUser.query.filter(db.func.lower(AdminUser.username) == username).first()
    if not user or not user.is_active or not user.check_password(password):
        # Always log a failed attempt (without g.admin_user — anonymous).
        try:
            from ...models import AdminAuditLog
            log = AdminAuditLog(
                admin_username=username[:80] if username else None,
                action="LOGIN_FAILED",
                summary=f"Failed login for '{username}'",
                ip_address=(request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:45],
                user_agent=(request.headers.get("User-Agent") or "")[:255],
            )
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({"error": "Unauthorized", "message": "Invalid username or password"}), 401

    touch_login(user)
    g.admin_user = user
    log_action("LOGIN", summary=f"{user.username} signed in")
    return jsonify(issue_token(user))


@admin_auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    return jsonify(g.admin_user.to_dict())


@admin_auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_action("LOGOUT", summary=f"{g.admin_user.username} signed out")
    # Tokens are stateless — the client just discards it. We just record the event.
    return jsonify({"ok": True})


@admin_auth_bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    current = data.get("current_password") or ""
    new_pw = data.get("new_password") or ""

    user = g.admin_user
    if not user.check_password(current):
        return jsonify({"error": "Unauthorized", "message": "Current password is incorrect"}), 401
    if len(new_pw) < 8:
        return jsonify({"error": "Bad Request", "message": "New password must be at least 8 characters"}), 400

    user.set_password(new_pw)
    db.session.commit()
    log_action("UPDATE", entity_type="admin_user", entity_id=user.id,
               summary=f"{user.username} changed their password")
    # Issue a fresh token because the old one is invalidated by the password change.
    return jsonify(issue_token(user))
