"""Admin endpoint: trigger a full Meilisearch reindex.

Useful after bulk-import scripts that bypass the SQLAlchemy admin routes (and
therefore the per-row sync hooks). The endpoint is synchronous because the
catalog is small enough to rebuild in well under a second; if the catalog ever
crosses ~10K supplements, switch to a background task.
"""
from flask import Blueprint, jsonify

from ...admin_auth import require_editor
from ...services import search_index


admin_search_bp = Blueprint("admin_search", __name__)


@admin_search_bp.route("/reindex", methods=["POST"])
@require_editor
def reindex():
    if not search_index.is_enabled():
        return jsonify({
            "ok": False,
            "reason": "Meilisearch is not configured (set MEILI_URL and MEILI_MASTER_KEY).",
        }), 503
    report = search_index.reindex_all()
    status = 200 if report.get("ok") else 500
    return jsonify(report), status


@admin_search_bp.route("/status", methods=["GET"])
@require_editor
def status():
    """Quick health probe — useful for an admin UI badge."""
    enabled = search_index.is_enabled()
    if not enabled:
        return jsonify({"enabled": False})
    index = search_index.get_index()
    if index is None:
        return jsonify({"enabled": True, "reachable": False})
    try:
        stats = index.get_stats()
        # The Python SDK returns either an object with attributes or a plain dict
        # depending on the version. Normalize to a dict either way.
        if hasattr(stats, "__dict__"):
            stats_dict = {
                k: getattr(stats, k)
                for k in ("number_of_documents", "is_indexing", "field_distribution")
                if hasattr(stats, k)
            }
        else:
            stats_dict = dict(stats)
        return jsonify({"enabled": True, "reachable": True, "stats": stats_dict})
    except Exception as e:  # noqa: BLE001
        return jsonify({"enabled": True, "reachable": False, "error": str(e)})
