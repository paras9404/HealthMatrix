import os
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .config import get_config
from .extensions import db, migrate, cors, limiter


def create_app(config_class=None):
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
    app = Flask(__name__, static_folder=static_dir, static_url_path="/static")
    app.config.from_object(config_class or get_config())

    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(
        app,
        resources={
            r"/api/*": {"origins": app.config["CORS_ORIGINS"]},
            r"/static/*": {"origins": app.config["CORS_ORIGINS"]},
        },
        supports_credentials=True,
    )
    limiter.init_app(app)

    from .routes.health import health_bp
    from .routes.supplements import supplements_bp
    from .routes.categories import categories_bp
    from .routes.sources import sources_bp
    from .routes.brands import brands_bp
    from .routes.compare import compare_bp
    from .routes.stats import stats_bp
    from .routes.sitemap import sitemap_bp
    from .routes.track import track_bp

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(supplements_bp, url_prefix="/api/supplements")
    app.register_blueprint(categories_bp, url_prefix="/api/categories")
    app.register_blueprint(sources_bp, url_prefix="/api/sources")
    app.register_blueprint(brands_bp, url_prefix="/api/brands")
    app.register_blueprint(compare_bp, url_prefix="/api/compare")
    app.register_blueprint(stats_bp, url_prefix="/api/stats")
    app.register_blueprint(track_bp, url_prefix="/api/track")
    # Sitemap + robots live at the root (no /api prefix) so search engines
    # find them at the conventional locations.
    app.register_blueprint(sitemap_bp)

    # Admin panel — separate URL prefix, requires bearer-token auth.
    from .routes.admin.auth import admin_auth_bp
    from .routes.admin.users import admin_users_bp
    from .routes.admin.brands import admin_brands_bp
    from .routes.admin.categories import admin_categories_bp
    from .routes.admin.sources import admin_sources_bp
    from .routes.admin.supplements import admin_supplements_bp
    from .routes.admin.ratings import admin_ratings_bp
    from .routes.admin.images import admin_images_bp
    from .routes.admin.dashboard import admin_dashboard_bp
    from .routes.admin.audit import admin_audit_bp
    from .routes.admin.image_validation import admin_image_validation_bp
    from .routes.admin.product_groups import admin_product_groups_bp
    from .routes.admin.source_import import admin_source_import_bp
    from .routes.admin.search import admin_search_bp
    from .routes.admin.analytics import admin_analytics_bp

    app.register_blueprint(admin_auth_bp, url_prefix="/api/admin/auth")
    app.register_blueprint(admin_users_bp, url_prefix="/api/admin/users")
    app.register_blueprint(admin_brands_bp, url_prefix="/api/admin/brands")
    app.register_blueprint(admin_categories_bp, url_prefix="/api/admin/categories")
    app.register_blueprint(admin_sources_bp, url_prefix="/api/admin/sources")
    app.register_blueprint(admin_supplements_bp, url_prefix="/api/admin/supplements")
    app.register_blueprint(admin_ratings_bp, url_prefix="/api/admin/ratings")
    app.register_blueprint(admin_images_bp, url_prefix="/api/admin/images")
    app.register_blueprint(admin_dashboard_bp, url_prefix="/api/admin/dashboard")
    app.register_blueprint(admin_audit_bp, url_prefix="/api/admin/audit")
    app.register_blueprint(admin_image_validation_bp, url_prefix="/api/admin/image-validation")
    app.register_blueprint(admin_product_groups_bp, url_prefix="/api/admin/product-groups")
    app.register_blueprint(admin_source_import_bp, url_prefix="/api/admin/source-import")
    app.register_blueprint(admin_search_bp, url_prefix="/api/admin/search")
    app.register_blueprint(admin_analytics_bp, url_prefix="/api/admin/analytics")

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        return jsonify({"error": e.name, "message": e.description}), e.code

    @app.errorhandler(429)
    def handle_rate_limit(e):
        # Best-effort telemetry — record the 429 so admins can see abuse patterns.
        # Failures here must NEVER mask the 429 response, hence the broad except.
        try:
            from flask import request
            from .models import RateLimitHit
            from .services.visitor_tracking import hash_ip, _client_ip
            db.session.add(RateLimitHit(
                ip_hash=hash_ip(_client_ip()),
                path=(request.path or "")[:500],
                method=(request.method or "")[:10],
                user_agent=(request.headers.get("User-Agent") or "")[:255],
            ))
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            app.logger.exception("rate_limit_hits insert skipped")
        return jsonify({"error": "Too Many Requests", "message": e.description}), 429

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if app.debug:
            raise e
        # Log the full traceback so we can debug 500s from the Render log viewer.
        # Without this, every unexpected error is silent except for an opaque
        # access-log 500 entry.
        app.logger.exception("Unhandled exception in request")
        return jsonify({"error": "Internal Server Error", "message": "Something went wrong"}), 500

    from . import models  # noqa: F401  (register models for Alembic autogenerate)

    # Best-effort: configure the Meilisearch index on boot so first-search isn't
    # cold. Failures (engine off, network) are logged inside and don't block app
    # startup — search routes detect the absence and fall back to SQL.
    if app.config.get("MEILI_URL") and app.config.get("MEILI_MASTER_KEY"):
        with app.app_context():
            try:
                from .services import search_index
                search_index.ensure_index_settings()
            except Exception:
                app.logger.exception("Meilisearch index configuration skipped")

    return app
