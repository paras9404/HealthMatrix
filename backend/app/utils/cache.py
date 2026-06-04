"""Tiny in-process TTL cache for read-heavy public endpoints.

Why not Flask-Caching: this app runs one Gunicorn worker on Render free tier and
we don't need cross-process or distributed caching. A dict + a monotonic clock is
~30 lines and zero new dependencies.

Two helpers:

    @ttl_cache(seconds=300)
    def list_categories():
        ...

    @cached_view(seconds=60, browser_seconds=30)
    def site_stats():
        ...

`ttl_cache` caches arbitrary callables (key = positional args + sorted kwargs).
`cached_view` is the Flask-route flavour: caches the (body, status) tuple keyed
by request path+query, and sets `Cache-Control: public, max-age=N` so the
browser and any CDN can short-circuit subsequent visits.
"""
from __future__ import annotations

import time
from functools import wraps
from threading import Lock
from typing import Any, Callable

from flask import request, make_response


def ttl_cache(seconds: float) -> Callable:
    """Decorator: memoize a function's return value for `seconds`.

    Thread-safe; safe to use on routes with the gthread/sync worker. Cache key
    is `(args, tuple(sorted(kwargs.items())))`. Don't decorate functions that
    return mutable objects you intend to mutate downstream — callers share the
    same reference.
    """
    def decorator(fn: Callable) -> Callable:
        store: dict[Any, tuple[float, Any]] = {}
        lock = Lock()

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit and hit[0] > now:
                    return hit[1]
            value = fn(*args, **kwargs)
            with lock:
                store[key] = (now + seconds, value)
            return value

        wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator


def cached_view(seconds: float, browser_seconds: float | None = None) -> Callable:
    """Decorator for Flask routes: memoize the response by path+query.

    `seconds` is the server-side TTL (cheap re-use across users).
    `browser_seconds` becomes `Cache-Control: public, max-age=N` on every
    response so the browser/CDN doesn't even hit us until it expires.
    Defaults browser_seconds to `seconds` when omitted.

    Only caches successful 2xx responses — error responses pass through so
    a transient 500 doesn't get pinned for the TTL.
    """
    if browser_seconds is None:
        browser_seconds = seconds

    def decorator(fn: Callable) -> Callable:
        store: dict[str, tuple[float, Any, int]] = {}
        lock = Lock()

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = request.full_path  # includes querystring
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit and hit[0] > now:
                    _, body, status = hit
                    resp = make_response(body, status)
                    resp.headers["Cache-Control"] = f"public, max-age={int(browser_seconds)}"
                    resp.headers["X-Cache"] = "HIT"
                    return resp

            resp = make_response(fn(*args, **kwargs))
            if 200 <= resp.status_code < 300:
                with lock:
                    store[key] = (now + seconds, resp.get_data(), resp.status_code)
                resp.headers["Cache-Control"] = f"public, max-age={int(browser_seconds)}"
                resp.headers["X-Cache"] = "MISS"
            return resp

        wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator
