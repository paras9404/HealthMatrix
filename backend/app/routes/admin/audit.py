from flask import Blueprint, request, jsonify
from sqlalchemy import asc, desc, nullslast

from ...models import AdminAuditLog
from ...admin_auth import require_superadmin


admin_audit_bp = Blueprint("admin_audit", __name__)


_AUDIT_SORTS = {
    "created_at": AdminAuditLog.created_at,
    "admin_username": AdminAuditLog.admin_username,
    "action": AdminAuditLog.action,
    "entity_type": AdminAuditLog.entity_type,
    "ip_address": AdminAuditLog.ip_address,
}


@admin_audit_bp.route("", methods=["GET"])
@require_superadmin
def list_audit():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 50)), 1), 200)
    action = request.args.get("action")
    entity_type = request.args.get("entity_type")
    username = request.args.get("username")
    sort = request.args.get("sort", "created_at")
    direction = request.args.get("dir", "desc").lower()

    query = AdminAuditLog.query
    if action:
        query = query.filter(AdminAuditLog.action == action)
    if entity_type:
        query = query.filter(AdminAuditLog.entity_type == entity_type)
    if username:
        query = query.filter(AdminAuditLog.admin_username.ilike(f"%{username}%"))

    col = _AUDIT_SORTS.get(sort, AdminAuditLog.created_at)
    order = nullslast(desc(col) if direction == "desc" else asc(col))
    query = query.order_by(order, AdminAuditLog.id)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        "items": [a.to_dict() for a in items],
        "page": page, "per_page": per_page, "total": total,
        "total_pages": (total + per_page - 1) // per_page,
    })
