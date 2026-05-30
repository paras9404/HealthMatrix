"""Visitor tracking service: cookie/session resolution, UA classification, IP hashing,
bot detection, and event recording.

Why service-level: keep route handlers thin and let admin analytics share the
exact same UA/bot rules used at write time.
"""
import hashlib
import ipaddress
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from urllib.parse import urlparse

from flask import current_app, request

from ..extensions import db
from ..models import VisitorSession, VisitorEvent, EVENT_TYPES, EVENT_PAGE_VIEW


COOKIE_VISITOR = "hm_visitor"
COOKIE_SESSION = "hm_session"
VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 365         # 1 year
SESSION_INACTIVITY_SECONDS = 30 * 60                 # 30 min sliding
DEDUP_SECONDS = 5                                    # rapid same-path reload window
SEARCH_QUERY_MAX = 200
PATH_MAX = 500


# --- UA / bot classification --------------------------------------------------

# Cheap regex patterns; not perfect but covers the long tail of legit crawlers.
_BOT_RE = re.compile(
    r"(bot|crawl|spider|slurp|bingpreview|facebookexternalhit|embedly|"
    r"vkshare|w3c_validator|whatsapp|telegrambot|discordbot|linkedinbot|"
    r"applebot|petalbot|yandex|baidu|duckduckbot|ahrefs|semrush|mj12|"
    r"dotbot|seznam|pingdom|gtmetrix|lighthouse|headlesschrome)",
    re.IGNORECASE,
)
_MOBILE_RE = re.compile(r"(iphone|android.*mobile|windows phone|blackberry)", re.IGNORECASE)
_TABLET_RE = re.compile(r"(ipad|android(?!.*mobile)|tablet)", re.IGNORECASE)

# Strip likely PII out of search-query strings before persisting.
_EMAIL_RE = re.compile(r"[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{7,}\d")


def classify_device(ua: str) -> str:
    if not ua:
        return "unknown"
    if _BOT_RE.search(ua):
        return "bot"
    if _TABLET_RE.search(ua):
        return "tablet"
    if _MOBILE_RE.search(ua):
        return "mobile"
    return "desktop"


def classify_browser(ua: str) -> str:
    if not ua:
        return "other"
    ua_lower = ua.lower()
    # Order matters: Edge/Chrome both contain "Safari", Edge contains "Chrome".
    if "edg/" in ua_lower or "edge/" in ua_lower:
        return "Edge"
    if "opr/" in ua_lower or "opera/" in ua_lower:
        return "Opera"
    if "firefox/" in ua_lower:
        return "Firefox"
    if "chrome/" in ua_lower:
        return "Chrome"
    if "safari/" in ua_lower:
        return "Safari"
    return "other"


def classify_os(ua: str) -> str:
    if not ua:
        return "other"
    ua_lower = ua.lower()
    if "iphone" in ua_lower or "ipad" in ua_lower or "ipod" in ua_lower:
        return "iOS"
    if "android" in ua_lower:
        return "Android"
    if "mac os x" in ua_lower or "macintosh" in ua_lower:
        return "macOS"
    if "windows" in ua_lower:
        return "Windows"
    if "linux" in ua_lower or "x11" in ua_lower:
        return "Linux"
    return "other"


def is_bot_ua(ua: str) -> bool:
    return bool(ua and _BOT_RE.search(ua))


# --- IP handling --------------------------------------------------------------

def _client_ip() -> str:
    """Best-effort client IP. X-Forwarded-For first hop wins."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or ""


def anonymize_ip(raw: str) -> str:
    """Truncate to /24 (IPv4) or /48 (IPv6) before hashing — never store raw."""
    if not raw:
        return ""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return ""
    if isinstance(ip, ipaddress.IPv4Address):
        net = ipaddress.IPv4Network(f"{raw}/24", strict=False)
    else:
        net = ipaddress.IPv6Network(f"{raw}/48", strict=False)
    return str(net.network_address)


def hash_ip(raw: str) -> str:
    anon = anonymize_ip(raw)
    if not anon:
        return ""
    salt = current_app.config.get("SECRET_KEY", "")
    return hashlib.sha256(f"{anon}|{salt}".encode("utf-8")).hexdigest()


# --- Misc helpers -------------------------------------------------------------

def referrer_domain(referrer: Optional[str]) -> Optional[str]:
    if not referrer:
        return None
    try:
        host = urlparse(referrer).hostname or ""
    except Exception:
        return None
    host = host.lower()
    if not host:
        return None
    # Drop our own host so internal navigation doesn't dominate "top referrers".
    site_url = current_app.config.get("SITE_URL", "") or ""
    own_host = ""
    try:
        own_host = (urlparse(site_url).hostname or "").lower()
    except Exception:
        pass
    if own_host and host == own_host:
        return None
    return host[:160]


def sanitize_query(q: Optional[str]) -> Optional[str]:
    if not q:
        return None
    q = q.strip()
    if not q:
        return None
    q = _EMAIL_RE.sub("[email]", q)
    q = _PHONE_RE.sub("[phone]", q)
    return q[:SEARCH_QUERY_MAX]


def sanitize_path(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    p = p.strip()
    if not p.startswith("/"):
        p = "/" + p
    return p[:PATH_MAX]


def respect_dnt() -> bool:
    """Honor the Do Not Track header if the browser sends DNT: 1."""
    return request.headers.get("DNT") == "1"


# --- Session lifecycle --------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _read_or_mint_visitor_id() -> Tuple[str, bool]:
    """Returns (visitor_id, is_new). Reads cookie if present, mints UUID if not."""
    existing = request.cookies.get(COOKIE_VISITOR)
    if existing and len(existing) == 36:
        try:
            uuid.UUID(existing)  # validate format
            return existing, False
        except ValueError:
            pass
    return str(uuid.uuid4()), True


def get_or_create_session(visitor_id: str, ua: str) -> Tuple[VisitorSession, bool]:
    """Find a still-live session for this visitor, or create one. Returns (session, created)."""
    cookie_session_uuid = request.cookies.get(COOKIE_SESSION)
    cutoff = _utcnow() - timedelta(seconds=SESSION_INACTIVITY_SECONDS)

    if cookie_session_uuid:
        sess = (VisitorSession.query
                .filter(VisitorSession.session_uuid == cookie_session_uuid,
                        VisitorSession.visitor_id == visitor_id)
                .first())
        if sess and sess.last_seen_at and sess.last_seen_at >= cutoff:
            return sess, False

    referrer = request.headers.get("Referer", "")
    sess = VisitorSession(
        session_uuid=str(uuid.uuid4()),
        visitor_id=visitor_id,
        started_at=_utcnow(),
        last_seen_at=_utcnow(),
        entry_path=sanitize_path(request.headers.get("X-Page-Path") or ""),
        referrer_domain=referrer_domain(referrer),
        device_type=classify_device(ua),
        browser=classify_browser(ua),
        os=classify_os(ua),
        ip_hash=hash_ip(_client_ip()),
        is_bot=is_bot_ua(ua),
    )
    db.session.add(sess)
    db.session.flush()  # we need sess.id before inserting events
    return sess, True


# --- Event write -------------------------------------------------------------

def _is_duplicate_recent(
    session_id: int, event_type: str,
    path: Optional[str], entity_id: Optional[str], query: Optional[str],
) -> bool:
    """Suppress same-event re-fires within DEDUP_SECONDS.

    Catches:
      - Back-button reloads (page_view with same path)
      - React StrictMode double-mount in dev (any event type)
      - Sloppy double-clicks on outbound links

    Match key is (event_type, path, entity_id, query) — all-NULL fields included
    so e.g. two supplement_views of the same slug collapse to one row.
    """
    cutoff = _utcnow() - timedelta(seconds=DEDUP_SECONDS)
    q = (db.session.query(VisitorEvent.id)
         .filter(VisitorEvent.session_id == session_id,
                 VisitorEvent.event_type == event_type,
                 VisitorEvent.occurred_at >= cutoff))
    # Use IS comparison for nullable columns so two identical NULL paths match.
    q = q.filter(
        (VisitorEvent.path == path) if path is not None else VisitorEvent.path.is_(None)
    )
    q = q.filter(
        (VisitorEvent.entity_id == entity_id) if entity_id is not None else VisitorEvent.entity_id.is_(None)
    )
    q = q.filter(
        (VisitorEvent.search_query == query) if query is not None else VisitorEvent.search_query.is_(None)
    )
    return db.session.query(q.exists()).scalar()


def record_event(
    event_type: str,
    *,
    path: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id=None,
    referrer: Optional[str] = None,
    query: Optional[str] = None,
    meta: Optional[dict] = None,
) -> Optional[dict]:
    """Resolve visitor + session and append an event. Returns dict with cookies
    to set (visitor_id_cookie, session_uuid_cookie) so the route handler can
    attach them to the response. Never raises — failures swallowed.
    """
    if event_type not in EVENT_TYPES:
        return None
    if respect_dnt():
        return None

    try:
        ua = request.headers.get("User-Agent", "")[:500]
        visitor_id, _new = _read_or_mint_visitor_id()
        session, _created = get_or_create_session(visitor_id, ua)

        clean_path = sanitize_path(path)
        clean_entity = str(entity_id) if entity_id is not None else None
        clean_query = sanitize_query(query)
        if _is_duplicate_recent(session.id, event_type, clean_path, clean_entity, clean_query):
            # Still bump last_seen so the session stays alive.
            session.last_seen_at = _utcnow()
            db.session.commit()
            return {"visitor_id": visitor_id, "session_uuid": session.session_uuid}

        ev = VisitorEvent(
            session_id=session.id,
            visitor_id=visitor_id,
            event_type=event_type,
            path=clean_path,
            entity_type=entity_type,
            entity_id=clean_entity,
            referrer=(referrer or "")[:500] or None,
            search_query=clean_query,
            meta=meta or None,
        )
        db.session.add(ev)

        session.last_seen_at = _utcnow()
        session.event_count = (session.event_count or 0) + 1
        if event_type == EVENT_PAGE_VIEW:
            session.page_view_count = (session.page_view_count or 0) + 1

        db.session.commit()
        return {"visitor_id": visitor_id, "session_uuid": session.session_uuid}
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("visitor_tracking.record_event failed")
        return None


def attach_cookies(response, cookie_data: Optional[dict]):
    """Apply visitor + session cookies to a Flask response. Idempotent — safe to
    call when cookie_data is None.
    """
    if not cookie_data:
        return response
    secure = not current_app.debug
    if cookie_data.get("visitor_id"):
        response.set_cookie(
            COOKIE_VISITOR, cookie_data["visitor_id"],
            max_age=VISITOR_COOKIE_MAX_AGE,
            samesite="Lax", secure=secure, httponly=False,
            path="/",
        )
    if cookie_data.get("session_uuid"):
        response.set_cookie(
            COOKIE_SESSION, cookie_data["session_uuid"],
            max_age=SESSION_INACTIVITY_SECONDS,
            samesite="Lax", secure=secure, httponly=False,
            path="/",
        )
    return response
