"""
sitemap.xml + robots.txt for SEO.

Mounted at the root (no /api prefix) so search engines find them at the
expected URLs. In production, configure your CDN/edge to forward
GET /sitemap.xml and /robots.txt from the frontend host to this backend
(or copy /robots.txt as a static file at the frontend and just proxy
sitemap.xml — the dynamic one is the catalog).

Pulls SITE_URL from config so absolute URLs match the user-facing domain
even though the API may live on a different host (api.healthmatrix.com).
"""
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from flask import Blueprint, Response, current_app

from ..extensions import db
from ..models import Brand, Category, Source, Supplement


sitemap_bp = Blueprint("sitemap", __name__)


def _site_url() -> str:
    return current_app.config.get("SITE_URL", "https://healthmatrix.com").rstrip("/")


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(timezone.utc).date().isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.date().isoformat()


def _url(loc: str, lastmod: str | None = None, changefreq: str = "weekly", priority: str = "0.7") -> str:
    parts = [f"  <url>", f"    <loc>{escape(loc)}</loc>"]
    if lastmod:
        parts.append(f"    <lastmod>{lastmod}</lastmod>")
    parts.append(f"    <changefreq>{changefreq}</changefreq>")
    parts.append(f"    <priority>{priority}</priority>")
    parts.append("  </url>")
    return "\n".join(parts)


@sitemap_bp.route("/sitemap.xml", methods=["GET"])
def sitemap():
    base = _site_url()
    today = datetime.now(timezone.utc).date().isoformat()
    urls: list[str] = []

    # Static pages
    urls.append(_url(f"{base}/", lastmod=today, changefreq="daily", priority="1.0"))
    urls.append(_url(f"{base}/browse", lastmod=today, changefreq="daily", priority="0.9"))
    urls.append(_url(f"{base}/about", lastmod=today, changefreq="monthly", priority="0.5"))

    # Category landing URLs (use Browse with ?category= — it's the canonical filter UI)
    for cat in (Category.query
                .filter(Category.is_active.is_(True))
                .order_by(Category.sort_order.asc(), Category.name.asc())
                .all()):
        urls.append(_url(
            f"{base}/browse?category={cat.slug}",
            lastmod=_iso(cat.created_at),
            changefreq="weekly",
            priority="0.8",
        ))

    # Supplement detail pages — only published, with active brand+category.
    rows = (Supplement.query
            .join(Brand, Brand.id == Supplement.brand_id)
            .join(Category, Category.id == Supplement.category_id)
            .filter(Supplement.is_published.is_(True),
                    Brand.is_active.is_(True),
                    Category.is_active.is_(True))
            .with_entities(Supplement.slug, Supplement.updated_at)
            .all())
    for slug, updated in rows:
        urls.append(_url(
            f"{base}/supplement/{slug}",
            lastmod=_iso(updated),
            changefreq="weekly",
            priority="0.7",
        ))

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(body, mimetype="application/xml")


@sitemap_bp.route("/robots.txt", methods=["GET"])
def robots():
    base = _site_url()
    body = (
        "# HealthMatrix — robots policy\n"
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /compare\n"
        "Disallow: /*?sort=\n"
        "Disallow: /*?page=\n"
        "Disallow: /*&sort=\n"
        "Disallow: /*&page=\n"
        "Crawl-delay: 1\n"
        f"\nSitemap: {base}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")
