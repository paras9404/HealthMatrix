"""Public visitor-tracking endpoint.

Single endpoint accepts a JSON event payload from the SPA, validates it,
records it through the tracking service, and attaches visitor + session
cookies to the response. Rate-limited because it's unauthenticated.
"""
from flask import Blueprint, request, jsonify, make_response

from ..extensions import limiter
from ..models import EVENT_TYPES
from ..services import visitor_tracking as vt


track_bp = Blueprint("track", __name__)


@track_bp.route("/event", methods=["POST", "OPTIONS"])
@limiter.limit("120 per minute")
def event():
    if request.method == "OPTIONS":
        return ("", 204)

    if vt.respect_dnt():
        return ("", 204)

    data = request.get_json(silent=True) or {}
    event_type = data.get("type")
    if event_type not in EVENT_TYPES:
        return jsonify({"error": "Bad Request", "message": "Unknown event type"}), 400

    # Coerce all incoming fields to strings/None — the SPA controls the payload
    # but we never trust it. Lengths are clamped inside the service.
    cookie_data = vt.record_event(
        event_type,
        path=data.get("path"),
        entity_type=data.get("entity_type"),
        entity_id=data.get("entity_id"),
        referrer=data.get("referrer") or request.headers.get("Referer"),
        query=data.get("query"),
        meta=data.get("meta") if isinstance(data.get("meta"), dict) else None,
    )

    resp = make_response(jsonify({"ok": True}))
    return vt.attach_cookies(resp, cookie_data), 200
