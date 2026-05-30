/**
 * Visitor analytics tracker.
 *
 * Single source of truth for posting events to /api/track/event:
 *   - useTracker()                — fires page_view automatically on route change
 *   - trackEvent(type, payload)   — manual event from anywhere (search, click, etc.)
 *
 * Design notes:
 *   - Honors navigator.doNotTrack — stops at the door.
 *   - Uses sendBeacon when the page is unloading so the request actually leaves.
 *   - In-flight de-dup of identical paths fired within 1s (router double-renders).
 *   - Never throws; never blocks the UI; never depends on auth.
 */
import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

const ENDPOINT = '/api/track/event'

function dntEnabled() {
  if (typeof navigator === 'undefined') return false
  // Various browsers historically used different flags.
  const v = navigator.doNotTrack || window.doNotTrack || navigator.msDoNotTrack
  return v === '1' || v === 'yes'
}

/** Low-level send. Returns void; failures are silent. */
export function trackEvent(type, payload = {}) {
  if (!type || dntEnabled()) return
  const body = JSON.stringify({
    type,
    path: payload.path ?? (typeof window !== 'undefined' ? window.location.pathname + window.location.search : null),
    referrer: payload.referrer ?? (typeof document !== 'undefined' ? document.referrer : null),
    entity_type: payload.entity_type,
    entity_id: payload.entity_id,
    query: payload.query,
    meta: payload.meta,
  })

  // Beacon = best-effort, fire-and-forget, survives page unload.
  if (payload.beacon && typeof navigator !== 'undefined' && navigator.sendBeacon) {
    try {
      const blob = new Blob([body], { type: 'application/json' })
      navigator.sendBeacon(ENDPOINT, blob)
      return
    } catch (_) { /* fall through to fetch */ }
  }

  try {
    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      credentials: 'same-origin',
      keepalive: true,
    }).catch(() => {})
  } catch (_) { /* swallow */ }
}

/**
 * Hook that fires a page_view on every location change (excluding /admin).
 * Mount once at the App level.
 */
export function useTracker() {
  const location = useLocation()
  const lastPath = useRef(null)
  const lastFiredAt = useRef(0)

  useEffect(() => {
    const path = location.pathname + location.search
    // Never track the admin section — would skew everything.
    if (location.pathname.startsWith('/admin')) {
      lastPath.current = path
      return
    }
    const now = Date.now()
    // De-dup React double-render in StrictMode + back-to-back nav.
    if (path === lastPath.current && now - lastFiredAt.current < 1000) return
    lastPath.current = path
    lastFiredAt.current = now
    trackEvent('page_view', { path })
  }, [location.pathname, location.search])
}

/** Optional: best-effort "session end" beacon when the tab closes. */
export function useUnloadBeacon() {
  useEffect(() => {
    if (dntEnabled()) return
    const onHide = () => {
      // No new event type — just a final page_view ensures last_seen_at moves
      // forward so session duration on the dashboard is accurate.
      trackEvent('page_view', { beacon: true })
    }
    window.addEventListener('pagehide', onHide)
    return () => window.removeEventListener('pagehide', onHide)
  }, [])
}
