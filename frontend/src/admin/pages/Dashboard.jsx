import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { dashboardApi, analyticsApi } from '../services/adminApi.js'
import Sparkline from '../components/charts/Sparkline.jsx'

const ACTION_BADGE = {
  CREATE: 'create', UPDATE: 'update', DELETE: 'delete',
  LOGIN: 'login', LOGOUT: 'login', LOGIN_FAILED: 'delete',
}

function formatRelative(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  if (diff < 7 * 86400) return `${Math.round(diff / 86400)}d ago`
  return d.toLocaleDateString()
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [feed, setFeed] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [rateLimits, setRateLimits] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const [s, a, an, rl] = await Promise.all([
          dashboardApi.stats(),
          dashboardApi.recentActivity(),
          // Analytics is best-effort — don't fail the dashboard if the table is empty.
          analyticsApi.overview().catch(() => null),
          analyticsApi.rateLimits('7d').catch(() => null),
        ])
        if (!cancelled) {
          setStats(s)
          setFeed(a.items || [])
          setAnalytics(an)
          setRateLimits(rl)
        }
      } catch (e) {
        if (!cancelled) setError(e.userMessage || 'Failed to load dashboard')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  if (loading) return <div className="admin-loading">Loading dashboard…</div>
  if (error) return <div className="admin-error-banner">{error}</div>
  if (!stats) return null

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Overview</h2>
          <div className="desc">All counts and recent activity across the catalog.</div>
        </div>
      </div>

      {analytics && (
        <div className="admin-stat-grid" style={{ marginBottom: 12 }}>
          <Link to="/admin/analytics" style={{ textDecoration: 'none', color: 'inherit' }}>
            <div className="admin-stat">
              <div className="lbl"><span className="admin-active-dot" />Active now</div>
              <div className="num">{analytics.active_now}</div>
              <div className="sub">last 5 minutes</div>
            </div>
          </Link>
          <Link to="/admin/analytics" style={{ textDecoration: 'none', color: 'inherit' }}>
            <div className="admin-stat">
              <div className="lbl">Visitors today</div>
              <div className="num">{analytics.today.visitors.toLocaleString()}</div>
              <div className="sub">{analytics.today.page_views} page views</div>
            </div>
          </Link>
          <Link to="/admin/analytics" style={{ textDecoration: 'none', color: 'inherit' }}>
            <div className="admin-stat">
              <div className="lbl">Visitors this week</div>
              <div className="num">{analytics.wau.toLocaleString()}</div>
              <div className="sub">
                {analytics.page_views_wow_pct == null
                  ? `${analytics.page_views_week} views`
                  : `${analytics.page_views_wow_pct > 0 ? '+' : ''}${analytics.page_views_wow_pct}% WoW`}
              </div>
            </div>
          </Link>
          <Link to="/admin/analytics" style={{ textDecoration: 'none', color: 'inherit' }}>
            <div className="admin-stat">
              <div className="lbl">Avg session</div>
              <div className="num">
                {analytics.avg_session_seconds < 60
                  ? `${analytics.avg_session_seconds}s`
                  : `${Math.round(analytics.avg_session_seconds / 60)}m`}
              </div>
              <div className="sub">{analytics.avg_pages_per_session} pages/session</div>
            </div>
          </Link>
          {rateLimits && (
            <Link to="/admin/analytics" style={{ textDecoration: 'none', color: 'inherit' }}>
              <div className="admin-stat">
                <div className="lbl">
                  {rateLimits.spike_last_5m > 0 && (
                    <span className="admin-active-dot" style={{ background: '#dc2626' }} />
                  )}
                  Rate limits (7d)
                </div>
                <div className="num" style={rateLimits.total > 0 ? { color: '#dc2626' } : undefined}>
                  {rateLimits.total.toLocaleString()}
                </div>
                <div className="sub">
                  {rateLimits.spike_last_5m > 0
                    ? `${rateLimits.spike_last_5m} in last 5m`
                    : 'no recent spike'}
                </div>
              </div>
            </Link>
          )}
        </div>
      )}

      {rateLimits && rateLimits.total > 0 && (
        <div className="admin-card" style={{ marginBottom: 12 }}>
          <div className="admin-page-header" style={{ marginBottom: 8 }}>
            <h3>HTTP 429 rejections (last 7 days)</h3>
            <span className="text-secondary" style={{ fontSize: '0.85rem' }}>
              {rateLimits.top_paths[0]
                ? `top path: ${rateLimits.top_paths[0].path} (${rateLimits.top_paths[0].hits})`
                : ''}
            </span>
          </div>
          <Sparkline
            points={rateLimits.series}
            valueKey="hits"
            color="#dc2626"
            height={100}
            formatLabel={(b) => new Date(b).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
          />
        </div>
      )}

      <div className="admin-stat-grid">
        <Stat label="Supplements" num={stats.supplements.total}
              sub={`${stats.supplements.published} published · ${stats.supplements.unpublished} hidden`}
              link="/admin/supplements" />
        <Stat label="Featured" num={stats.supplements.featured} sub="hero / front page" />
        <Stat label="Unrated" num={stats.supplements.unrated}
              sub="no rating from any active source" />
        <Stat label="New this week" num={stats.supplements.new_this_week} sub="last 7 days" />
        <Stat label="Brands" num={stats.brands.total}
              sub={`${stats.brands.active} active · ${stats.brands.inactive} hidden`}
              link="/admin/brands" />
        <Stat label="Categories" num={stats.categories.total}
              sub={`${stats.categories.active} active`}
              link="/admin/categories" />
        <Stat label="Sources" num={stats.sources.total}
              sub={`${stats.sources.active} active`}
              link="/admin/sources" />
        <Stat label="Ratings" num={stats.ratings.total}
              sub={`${stats.images.total} images`}
              link="/admin/ratings" />
      </div>

      <div className="admin-card">
        <div className="admin-page-header" style={{ marginBottom: 8 }}>
          <h3>Recent activity</h3>
          <span className="text-secondary" style={{ fontSize: '0.85rem' }}>
            {stats.activity.audit_events_this_week} events this week
          </span>
        </div>

        {feed.length === 0 ? (
          <div className="admin-empty"><div className="ico">·</div><p>No activity yet.</p></div>
        ) : (
          <div className="admin-feed">
            {feed.map((it) => (
              <div className="admin-feed-item" key={it.id}>
                <div className={`badge ${ACTION_BADGE[it.action] || 'login'}`}>
                  {it.action.charAt(0)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="text">{it.summary || `${it.action} ${it.entity_type || ''}`}</div>
                  <div className="meta">
                    {it.admin_username || 'system'} · {formatRelative(it.created_at)}
                    {it.entity_type ? ` · ${it.entity_type}${it.entity_id ? ` #${it.entity_id}` : ''}` : ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

function Stat({ label, num, sub, link }) {
  const body = (
    <div className="admin-stat">
      <div className="lbl">{label}</div>
      <div className="num">{num?.toLocaleString?.() ?? num}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
  return link ? <Link to={link} style={{ textDecoration: 'none', color: 'inherit' }}>{body}</Link> : body
}
