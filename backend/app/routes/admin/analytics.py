"""Admin analytics endpoints. All require login. All queries filter out bot
sessions by default — the dashboard reflects human visitors."""
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from flask import Blueprint, jsonify, request
from sqlalchemy import func, distinct, desc, and_

from ...extensions import db
from ...models import (
    VisitorSession, VisitorEvent, RateLimitHit, Supplement, Brand, Category,
    EVENT_PAGE_VIEW, EVENT_SEARCH, EVENT_SUPPLEMENT_VIEW, EVENT_OUTBOUND_CLICK,
)
from ...admin_auth import login_required


admin_analytics_bp = Blueprint("admin_analytics", __name__)


# --- helpers -----------------------------------------------------------------

RANGES = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_range() -> tuple[int, datetime]:
    """Read ?range=..., return (days, since_datetime). Defaults to 7d."""
    r = (request.args.get("range") or "7d").lower()
    days = RANGES.get(r, 7)
    if r == "24h":
        since = _utcnow() - timedelta(hours=24)
    else:
        since = _utcnow() - timedelta(days=days)
    return days, since


def _human_filter():
    """SQL filter — sessions that aren't bots."""
    return VisitorSession.is_bot.is_(False)


def _human_event_join(q):
    """Join VisitorEvent → VisitorSession and exclude bot sessions."""
    return q.join(VisitorSession, VisitorSession.id == VisitorEvent.session_id) \
            .filter(_human_filter())


def _limit_param(default: int = 10, cap: int = 100) -> int:
    try:
        n = int(request.args.get("limit", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(cap, n))


# --- 1. Overview -------------------------------------------------------------

@admin_analytics_bp.route("/overview", methods=["GET"])
@login_required
def overview():
    """High-level counters + week-over-week deltas."""
    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)
    month_ago = now - timedelta(days=30)
    five_min_ago = now - timedelta(minutes=5)

    def uniq_visitors(since):
        return (db.session.query(func.count(distinct(VisitorSession.visitor_id)))
                .filter(_human_filter(), VisitorSession.last_seen_at >= since)
                .scalar() or 0)

    def session_count(since):
        return (db.session.query(func.count(VisitorSession.id))
                .filter(_human_filter(), VisitorSession.started_at >= since)
                .scalar() or 0)

    def page_views(since):
        return (db.session.query(func.count(VisitorEvent.id))
                .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id)
                .filter(_human_filter(),
                        VisitorEvent.event_type == EVENT_PAGE_VIEW,
                        VisitorEvent.occurred_at >= since)
                .scalar() or 0)

    dau = uniq_visitors(day_ago)
    wau = uniq_visitors(week_ago)
    mau = uniq_visitors(month_ago)

    # Avg session duration + bounce rate over the last 7 days. Bounce = single
    # page_view session.
    week_sessions = (VisitorSession.query
                     .filter(_human_filter(), VisitorSession.started_at >= week_ago)
                     .all())
    if week_sessions:
        durations = [
            int((s.last_seen_at - s.started_at).total_seconds())
            for s in week_sessions if s.last_seen_at and s.started_at
        ]
        avg_duration = round(sum(durations) / len(durations)) if durations else 0
        bounces = sum(1 for s in week_sessions if (s.page_view_count or 0) <= 1)
        bounce_rate = round(100.0 * bounces / len(week_sessions), 1)
        avg_pages = round(
            sum((s.page_view_count or 0) for s in week_sessions) / len(week_sessions), 2
        )
    else:
        avg_duration = 0
        bounce_rate = 0.0
        avg_pages = 0.0

    pv_week = page_views(week_ago)
    pv_prev_week = (db.session.query(func.count(VisitorEvent.id))
                    .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id)
                    .filter(_human_filter(),
                            VisitorEvent.event_type == EVENT_PAGE_VIEW,
                            VisitorEvent.occurred_at >= prev_week_start,
                            VisitorEvent.occurred_at < week_ago)
                    .scalar() or 0)
    if pv_prev_week:
        wow_pct = round(100.0 * (pv_week - pv_prev_week) / pv_prev_week, 1)
    else:
        wow_pct = None  # not enough history

    # Bot share — proportion of sessions in the last 7 days flagged as bots.
    total_week = (db.session.query(func.count(VisitorSession.id))
                  .filter(VisitorSession.started_at >= week_ago)
                  .scalar() or 0)
    bot_week = (db.session.query(func.count(VisitorSession.id))
                .filter(VisitorSession.is_bot.is_(True),
                        VisitorSession.started_at >= week_ago)
                .scalar() or 0)
    bot_share = round(100.0 * bot_week / total_week, 1) if total_week else 0.0

    active_now = (db.session.query(func.count(distinct(VisitorSession.visitor_id)))
                  .filter(_human_filter(), VisitorSession.last_seen_at >= five_min_ago)
                  .scalar() or 0)

    return jsonify({
        "active_now": active_now,
        "today": {
            "visitors": uniq_visitors(today_start),
            "sessions": session_count(today_start),
            "page_views": page_views(today_start),
        },
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "page_views_week": pv_week,
        "page_views_prev_week": pv_prev_week,
        "page_views_wow_pct": wow_pct,
        "avg_session_seconds": avg_duration,
        "avg_pages_per_session": avg_pages,
        "bounce_rate_pct": bounce_rate,
        "bot_share_pct": bot_share,
    })


# --- 2. Time series ----------------------------------------------------------

@admin_analytics_bp.route("/timeseries", methods=["GET"])
@login_required
def timeseries():
    """Daily buckets of unique visitors / sessions / page-views.
    Bucketing done in Python so SQLite + Postgres behave identically."""
    days, since = _resolve_range()
    bucket_hours = 1 if days == 1 else 24

    # Pull everything we need in one shot — small data, big upside.
    rows = (db.session.query(
                VisitorEvent.occurred_at,
                VisitorEvent.event_type,
                VisitorEvent.visitor_id,
                VisitorEvent.session_id,
            )
            .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id)
            .filter(_human_filter(),
                    VisitorEvent.occurred_at >= since)
            .all())

    buckets = defaultdict(lambda: {"visitors": set(), "sessions": set(), "page_views": 0})
    for occurred_at, event_type, visitor_id, session_id in rows:
        if not occurred_at:
            continue
        # Normalize to UTC — Postgres returns timestamps in the server's local
        # timezone, but our fill-loop keys are UTC. Mismatched tzinfo means dict
        # lookup misses even when the wall-clock looks right.
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = occurred_at.astimezone(timezone.utc)
        if bucket_hours == 1:
            key = occurred_at.replace(minute=0, second=0, microsecond=0)
        else:
            key = occurred_at.replace(hour=0, minute=0, second=0, microsecond=0)
        b = buckets[key]
        b["visitors"].add(visitor_id)
        b["sessions"].add(session_id)
        if event_type == EVENT_PAGE_VIEW:
            b["page_views"] += 1

    # Fill in empty buckets so charts don't have gaps.
    if days == 1:
        end = _utcnow().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=23)
        step = timedelta(hours=1)
    else:
        end = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days - 1)
        step = timedelta(days=1)

    series = []
    cur = start
    while cur <= end:
        b = buckets.get(cur, {"visitors": set(), "sessions": set(), "page_views": 0})
        series.append({
            "bucket": cur.isoformat(),
            "visitors": len(b["visitors"]),
            "sessions": len(b["sessions"]),
            "page_views": b["page_views"],
        })
        cur += step

    return jsonify({"range": request.args.get("range") or "7d", "series": series})


# --- 3. Top pages ------------------------------------------------------------

@admin_analytics_bp.route("/top-pages", methods=["GET"])
@login_required
def top_pages():
    _, since = _resolve_range()
    limit = _limit_param(10)

    rows = (db.session.query(
                VisitorEvent.path,
                func.count(VisitorEvent.id).label("views"),
                func.count(distinct(VisitorEvent.visitor_id)).label("uniques"),
            )
            .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id)
            .filter(_human_filter(),
                    VisitorEvent.event_type == EVENT_PAGE_VIEW,
                    VisitorEvent.occurred_at >= since,
                    VisitorEvent.path.isnot(None))
            .group_by(VisitorEvent.path)
            .order_by(desc("views"))
            .limit(limit)
            .all())

    return jsonify({"items": [
        {"path": r.path, "views": r.views, "unique_visitors": r.uniques}
        for r in rows
    ]})


# --- 4. Top supplements ------------------------------------------------------

@admin_analytics_bp.route("/top-supplements", methods=["GET"])
@login_required
def top_supplements():
    _, since = _resolve_range()
    limit = _limit_param(10)

    rows = (db.session.query(
                VisitorEvent.entity_id,
                func.count(VisitorEvent.id).label("views"),
                func.count(distinct(VisitorEvent.visitor_id)).label("uniques"),
            )
            .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id)
            .filter(_human_filter(),
                    VisitorEvent.event_type == EVENT_SUPPLEMENT_VIEW,
                    VisitorEvent.occurred_at >= since,
                    VisitorEvent.entity_id.isnot(None))
            .group_by(VisitorEvent.entity_id)
            .order_by(desc("views"))
            .limit(limit)
            .all())

    # Resolve slugs → name + brand. Fast: small N (limit caps at 100).
    slugs = [r.entity_id for r in rows]
    sups = {s.slug: s for s in Supplement.query.filter(Supplement.slug.in_(slugs)).all()} if slugs else {}

    items = []
    for r in rows:
        s = sups.get(r.entity_id)
        items.append({
            "slug": r.entity_id,
            "name": s.name if s else None,
            "brand": s.brand.name if s and s.brand else None,
            "views": r.views,
            "unique_visitors": r.uniques,
            "found": s is not None,
        })
    return jsonify({"items": items})


# --- 5. Top searches ---------------------------------------------------------

@admin_analytics_bp.route("/top-searches", methods=["GET"])
@login_required
def top_searches():
    _, since = _resolve_range()
    limit = _limit_param(20)

    rows = (db.session.query(
                VisitorEvent.search_query.label("q"),
                func.count(VisitorEvent.id).label("count"),
                func.count(distinct(VisitorEvent.visitor_id)).label("uniques"),
            )
            .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id)
            .filter(_human_filter(),
                    VisitorEvent.event_type == EVENT_SEARCH,
                    VisitorEvent.occurred_at >= since,
                    VisitorEvent.search_query.isnot(None),
                    func.length(VisitorEvent.search_query) > 0)
            .group_by(VisitorEvent.search_query)
            .order_by(desc("count"))
            .limit(limit)
            .all())

    return jsonify({"items": [
        {"query": r.q, "count": r.count, "unique_visitors": r.uniques}
        for r in rows
    ]})


# --- 6. Top referrers --------------------------------------------------------

@admin_analytics_bp.route("/top-referrers", methods=["GET"])
@login_required
def top_referrers():
    _, since = _resolve_range()
    limit = _limit_param(15)

    rows = (db.session.query(
                VisitorSession.referrer_domain,
                func.count(VisitorSession.id).label("sessions"),
                func.count(distinct(VisitorSession.visitor_id)).label("uniques"),
            )
            .filter(_human_filter(),
                    VisitorSession.started_at >= since,
                    VisitorSession.referrer_domain.isnot(None))
            .group_by(VisitorSession.referrer_domain)
            .order_by(desc("sessions"))
            .limit(limit)
            .all())

    return jsonify({"items": [
        {"domain": r.referrer_domain, "sessions": r.sessions, "unique_visitors": r.uniques}
        for r in rows
    ]})


# --- 7. Devices --------------------------------------------------------------

@admin_analytics_bp.route("/devices", methods=["GET"])
@login_required
def devices():
    _, since = _resolve_range()

    def breakdown(column):
        rows = (db.session.query(column, func.count(VisitorSession.id).label("n"))
                .filter(_human_filter(),
                        VisitorSession.started_at >= since,
                        column.isnot(None))
                .group_by(column)
                .order_by(desc("n"))
                .all())
        return [{"label": r[0] or "unknown", "count": r.n} for r in rows]

    return jsonify({
        "device_type": breakdown(VisitorSession.device_type),
        "browser": breakdown(VisitorSession.browser),
        "os": breakdown(VisitorSession.os),
    })


# --- 8. Active now -----------------------------------------------------------

@admin_analytics_bp.route("/active-now", methods=["GET"])
@login_required
def active_now():
    """Visitors with events in the last 5 minutes — for a real-time widget."""
    now = _utcnow()
    five_min = now - timedelta(minutes=5)

    sessions = (VisitorSession.query
                .filter(_human_filter(), VisitorSession.last_seen_at >= five_min)
                .order_by(VisitorSession.last_seen_at.desc())
                .limit(50)
                .all())

    # Top current paths — what people are looking at right now.
    rows = (db.session.query(
                VisitorEvent.path,
                func.count(distinct(VisitorEvent.visitor_id)).label("uniques"),
            )
            .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id)
            .filter(_human_filter(),
                    VisitorEvent.event_type == EVENT_PAGE_VIEW,
                    VisitorEvent.occurred_at >= five_min,
                    VisitorEvent.path.isnot(None))
            .group_by(VisitorEvent.path)
            .order_by(desc("uniques"))
            .limit(10)
            .all())

    return jsonify({
        "as_of": now.isoformat(),
        "active_visitors": len({s.visitor_id for s in sessions}),
        "active_sessions": len(sessions),
        "current_pages": [{"path": r.path, "viewers": r.uniques} for r in rows],
        "sessions": [s.to_dict() for s in sessions[:20]],
    })


# --- 9. Recent events feed ---------------------------------------------------

@admin_analytics_bp.route("/recent-events", methods=["GET"])
@login_required
def recent_events():
    limit = _limit_param(50, cap=200)
    include_bots = (request.args.get("include_bots") or "").lower() in ("1", "true", "yes")

    q = (db.session.query(VisitorEvent, VisitorSession)
         .join(VisitorSession, VisitorSession.id == VisitorEvent.session_id))
    if not include_bots:
        q = q.filter(_human_filter())
    rows = q.order_by(VisitorEvent.occurred_at.desc()).limit(limit).all()

    items = []
    for ev, sess in rows:
        d = ev.to_dict()
        d["device_type"] = sess.device_type
        d["browser"] = sess.browser
        d["referrer_domain"] = sess.referrer_domain
        d["is_bot"] = sess.is_bot
        items.append(d)
    return jsonify({"items": items})


# --- 10. Sessions list -------------------------------------------------------

@admin_analytics_bp.route("/sessions", methods=["GET"])
@login_required
def sessions():
    """Paginated session browser. Surfaces a single visitor's journey for
    qualitative review."""
    _, since = _resolve_range()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    per_page = _limit_param(25, cap=100)
    include_bots = (request.args.get("include_bots") or "").lower() in ("1", "true", "yes")

    q = VisitorSession.query.filter(VisitorSession.started_at >= since)
    if not include_bots:
        q = q.filter(_human_filter())
    total = q.count()
    items = (q.order_by(VisitorSession.last_seen_at.desc())
             .offset((page - 1) * per_page).limit(per_page).all())

    total_pages = (total + per_page - 1) // per_page if per_page else 1

    return jsonify({
        "items": [s.to_dict() for s in items],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    })


# --- 11. Rate-limit telemetry -------------------------------------------------

@admin_analytics_bp.route("/rate-limits", methods=["GET"])
@login_required
def rate_limits():
    """Counts of HTTP 429 rejections from Flask-Limiter, bucketed by day (or
    hour for ?range=24h) plus the top offending paths and IP hashes."""
    days, since = _resolve_range()
    bucket_hours = 1 if days == 1 else 24

    rows = (db.session.query(RateLimitHit.occurred_at, RateLimitHit.path, RateLimitHit.ip_hash)
            .filter(RateLimitHit.occurred_at >= since)
            .all())

    buckets: dict = {}
    path_counts: dict = {}
    ip_counts: dict = {}
    for occurred_at, path, ip_hash in rows:
        if not occurred_at:
            continue
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = occurred_at.astimezone(timezone.utc)
        if bucket_hours == 1:
            key = occurred_at.replace(minute=0, second=0, microsecond=0)
        else:
            key = occurred_at.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets[key] = buckets.get(key, 0) + 1
        if path:
            path_counts[path] = path_counts.get(path, 0) + 1
        if ip_hash:
            ip_counts[ip_hash] = ip_counts.get(ip_hash, 0) + 1

    if days == 1:
        end = _utcnow().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=23)
        step = timedelta(hours=1)
    else:
        end = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days - 1)
        step = timedelta(days=1)

    series = []
    cur = start
    while cur <= end:
        series.append({"bucket": cur.isoformat(), "hits": buckets.get(cur, 0)})
        cur += step

    top_paths = sorted(path_counts.items(), key=lambda x: -x[1])[:10]
    top_ips = sorted(ip_counts.items(), key=lambda x: -x[1])[:10]

    # Active 429s right now (last 5 min) — surface a spike alert on the dashboard.
    five_min_ago = _utcnow() - timedelta(minutes=5)
    spike_now = (db.session.query(func.count(RateLimitHit.id))
                 .filter(RateLimitHit.occurred_at >= five_min_ago)
                 .scalar() or 0)

    return jsonify({
        "range": request.args.get("range") or "7d",
        "total": len(rows),
        "spike_last_5m": spike_now,
        "series": series,
        "top_paths": [{"path": p, "hits": c} for p, c in top_paths],
        "top_ip_hashes": [{"ip_hash": h[:12] + "…", "hits": c} for h, c in top_ips],
    })


# --- 12. Single-session journey ----------------------------------------------

@admin_analytics_bp.route("/sessions/<session_uuid>", methods=["GET"])
@login_required
def session_detail(session_uuid: str):
    sess = VisitorSession.query.filter_by(session_uuid=session_uuid).first()
    if not sess:
        return jsonify({"error": "Not Found"}), 404
    events = (VisitorEvent.query
              .filter(VisitorEvent.session_id == sess.id)
              .order_by(VisitorEvent.occurred_at.asc())
              .all())
    return jsonify({
        "session": sess.to_dict(),
        "events": [e.to_dict() for e in events],
    })
