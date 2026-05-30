from flask import Blueprint, request, jsonify, g, abort
from sqlalchemy import asc, desc, nullslast

from ...extensions import db
from ...models import AdminUser
from ...models.admin_user import ROLES, ROLE_SUPERADMIN
from ...admin_auth import login_required, require_superadmin, log_action


admin_users_bp = Blueprint("admin_users", __name__)


def _validate_role(role: str):
    if role not in ROLES:
        abort(400, description=f"role must be one of: {', '.join(ROLES)}")


_USER_SORTS = {
    "username": AdminUser.username,
    "email": AdminUser.email,
    "role": AdminUser.role,
    "is_active": AdminUser.is_active,
    "last_login_at": AdminUser.last_login_at,
    "created_at": AdminUser.created_at,
}


@admin_users_bp.route("", methods=["GET"])
@login_required  # any logged-in admin may view the list (read-only is OK)
def list_users():
    sort = request.args.get("sort", "username")
    direction = request.args.get("dir", "asc").lower()
    col = _USER_SORTS.get(sort, AdminUser.username)
    order = nullslast(desc(col) if direction == "desc" else asc(col))
    users = AdminUser.query.order_by(order, AdminUser.id).all()
    return jsonify({"items": [u.to_dict() for u in users]})


@admin_users_bp.route("", methods=["POST"])
@require_superadmin
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower() or None
    role = (data.get("role") or "readonly").strip()
    password = data.get("password") or ""
    is_active = bool(data.get("is_active", True))

    if not username or len(username) < 3:
        abort(400, description="username must be at least 3 characters")
    if not password or len(password) < 8:
        abort(400, description="password must be at least 8 characters")
    _validate_role(role)
    if AdminUser.query.filter(db.func.lower(AdminUser.username) == username).first():
        abort(400, description="username already exists")
    if email and AdminUser.query.filter(db.func.lower(AdminUser.email) == email).first():
        abort(400, description="email already exists")

    user = AdminUser(username=username, email=email, role=role, is_active=is_active)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    log_action("CREATE", entity_type="admin_user", entity_id=user.id,
               summary=f"Created admin user '{user.username}' as {user.role}",
               changes={"username": user.username, "email": user.email, "role": user.role,
                        "is_active": user.is_active})
    return jsonify(user.to_dict()), 201


@admin_users_bp.route("/<int:user_id>", methods=["GET"])
@login_required
def get_user(user_id):
    user = AdminUser.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@admin_users_bp.route("/<int:user_id>", methods=["PATCH", "PUT"])
@require_superadmin
def update_user(user_id):
    user = AdminUser.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    before = user.to_dict()

    if "email" in data:
        new_email = (data["email"] or "").strip().lower() or None
        if new_email and new_email != user.email:
            existing = AdminUser.query.filter(db.func.lower(AdminUser.email) == new_email).first()
            if existing and existing.id != user.id:
                abort(400, description="email already in use")
        user.email = new_email
    if "role" in data:
        _validate_role(data["role"])
        # Prevent demoting the last active superadmin (you'd lock yourself out).
        if user.role == ROLE_SUPERADMIN and data["role"] != ROLE_SUPERADMIN:
            other_superadmins = AdminUser.query.filter(
                AdminUser.role == ROLE_SUPERADMIN,
                AdminUser.is_active.is_(True),
                AdminUser.id != user.id,
            ).count()
            if other_superadmins == 0:
                abort(400, description="Cannot demote the last active superadmin")
        user.role = data["role"]
    if "is_active" in data:
        new_active = bool(data["is_active"])
        if user.role == ROLE_SUPERADMIN and not new_active and user.is_active:
            other_superadmins = AdminUser.query.filter(
                AdminUser.role == ROLE_SUPERADMIN,
                AdminUser.is_active.is_(True),
                AdminUser.id != user.id,
            ).count()
            if other_superadmins == 0:
                abort(400, description="Cannot deactivate the last active superadmin")
        user.is_active = new_active
    if data.get("password"):
        if len(data["password"]) < 8:
            abort(400, description="password must be at least 8 characters")
        user.set_password(data["password"])

    db.session.commit()
    after = user.to_dict()
    diff = {k: [before.get(k), after.get(k)] for k in after if before.get(k) != after.get(k)}
    log_action("UPDATE", entity_type="admin_user", entity_id=user.id,
               summary=f"Updated admin user '{user.username}'", changes=diff)
    return jsonify(user.to_dict())


@admin_users_bp.route("/<int:user_id>", methods=["DELETE"])
@require_superadmin
def delete_user(user_id):
    user = AdminUser.query.get_or_404(user_id)
    if user.id == g.admin_user.id:
        abort(400, description="You cannot delete your own account")
    if user.role == ROLE_SUPERADMIN:
        other_superadmins = AdminUser.query.filter(
            AdminUser.role == ROLE_SUPERADMIN,
            AdminUser.is_active.is_(True),
            AdminUser.id != user.id,
        ).count()
        if other_superadmins == 0:
            abort(400, description="Cannot delete the last active superadmin")

    username = user.username
    db.session.delete(user)
    db.session.commit()
    log_action("DELETE", entity_type="admin_user", entity_id=user_id,
               summary=f"Deleted admin user '{username}'")
    return jsonify({"ok": True})
