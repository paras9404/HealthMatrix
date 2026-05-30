import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { analyticsApi } from '../services/adminApi.js'
import Sparkline from '../components/charts/Sparkline.jsx'
import BarRow from '../components/charts/BarRow.jsx'
import Modal from '../components/Modal.jsx'

const RANGES = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
]

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'pages', label: 'Pages & content' },
  { value: 'searches', label: 'Searches & referrers' },
  { value: 'live', label: 'Live' },
  { value: 'sessions', label: 'Sessions' },
]

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '—'
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

function formatBucket(iso, range) {
  if (!iso) return ''
  const d = new Date(iso)
  if (range === '24h') {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatRelative(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 30) return 'just now'
  if (diff < 60) return `${Math.round(diff)}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return d.toLocaleString()
}

export default function Analytics() {
  const [tab, setTab] = useState('overview')
  const [range, setRange] = useState('7d')

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Analytics</h2>
          <div className="desc">Anonymous visitor activity. Bot traffic excluded by default.</div>
        </div>
        <div className="admin-range-pills">
          {RANGES.map((r) => (
            <button
              key={r.value}
              className={`admin-range-pill ${r.value === range ? 'active' : ''}`}
              onClick={() => setRange(r.value)}
              type="button"
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="admin-analytics-tabs">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            className={`admin-analytics-tab ${t.value === tab ? 'active' : ''}`}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab range={range} />}
      {tab === 'pages' && <PagesTab range={range} />}
      {tab === 'searches' && <SearchesTab range={range} />}
      {tab === 'live' && <LiveTab />}
      {tab === 'sessions' && <SessionsTab range={range} />}
    </>
  )
}

// -------------------- Overview tab --------------------

function OverviewTab({ range }) {
  const [data, setData] = useState(null)
  const [series, setSeries] = useState(null)
  const [devices, setDevices] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      analyticsApi.overview(),
      analyticsApi.timeseries(range),
      analyticsApi.devices(range),
    ])
      .then(([o, ts, dv]) => {
        if (cancelled) return
        setData(o)
        setSeries(ts)
        setDevices(dv)
      })
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [range])

  if (loading) return <div className="admin-loading">Loading…</div>
  if (error) return <div className="admin-error-banner">{error}</div>
  if (!data || !series) return null

  const wow = data.page_views_wow_pct
  const wowText = wow == null ? null : `${wow > 0 ? '+' : ''}${wow}% WoW`
  const wowColor = wow == null ? '' : wow >= 0 ? '#16a34a' : '#dc2626'

  return (
    <>
      <div className="admin-stat-grid">
        <div className="admin-stat">
          <div className="lbl"><span className="admin-active-dot" />Active now</div>
          <div className="num">{data.active_now}</div>
          <div className="sub">last 5 minutes</div>
        </div>
        <Stat label="Visitors today" num={data.today.visitors} sub={`${data.today.sessions} sessions · ${data.today.page_views} views`} />
        <Stat label="DAU" num={data.dau} sub="unique visitors · 24h" />
        <Stat label="WAU" num={data.wau} sub="unique visitors · 7d" />
        <Stat label="MAU" num={data.mau} sub="unique visitors · 30d" />
        <Stat
          label="Page views (7d)"
          num={data.page_views_week}
          sub={wowText}
          subStyle={{ color: wowColor }}
        />
        <Stat label="Avg. session" num={formatDuration(data.avg_session_seconds)} sub={`${data.avg_pages_per_session} pages/session`} />
        <Stat label="Bounce rate" num={`${data.bounce_rate_pct}%`} sub={`Bots: ${data.bot_share_pct}% of traffic`} />
      </div>

      <div className="admin-card">
        <div className="admin-page-header" style={{ marginBottom: 8 }}>
          <h3>Traffic over time</h3>
          <span className="text-secondary" style={{ fontSize: '0.85rem' }}>
            page views, {range}
          </span>
        </div>
        <Sparkline
          points={series.series}
          valueKey="page_views"
          formatLabel={(b) => formatBucket(b, range)}
        />
      </div>

      <div className="admin-analytics-grid">
        <div className="admin-card">
          <div className="admin-page-header" style={{ marginBottom: 8 }}>
            <h3>Devices</h3>
          </div>
          <BarRow items={devices?.device_type || []} labelKey="label" valueKey="count" />
        </div>
        <div className="admin-card">
          <div className="admin-page-header" style={{ marginBottom: 8 }}>
            <h3>Browsers</h3>
          </div>
          <BarRow items={(devices?.browser || []).slice(0, 6)} labelKey="label" valueKey="count" />
        </div>
      </div>
    </>
  )
}

function Stat({ label, num, sub, subStyle }) {
  return (
    <div className="admin-stat">
      <div className="lbl">{label}</div>
      <div className="num">{typeof num === 'number' ? num.toLocaleString() : num}</div>
      {sub && <div className="sub" style={subStyle}>{sub}</div>}
    </div>
  )
}

// -------------------- Pages tab --------------------

function PagesTab({ range }) {
  const [pages, setPages] = useState(null)
  const [supps, setSupps] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      analyticsApi.topPages(range, 15),
      analyticsApi.topSupplements(range, 15),
    ])
      .then(([p, s]) => {
        if (cancelled) return
        setPages(p)
        setSupps(s)
      })
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [range])

  if (loading) return <div className="admin-loading">Loading…</div>
  if (error) return <div className="admin-error-banner">{error}</div>

  return (
    <div className="admin-analytics-grid">
      <div className="admin-card">
        <div className="admin-page-header" style={{ marginBottom: 8 }}>
          <h3>Top pages</h3>
          <span className="text-secondary" style={{ fontSize: '0.85rem' }}>by page views</span>
        </div>
        <BarRow
          items={pages?.items || []}
          labelKey="path"
          valueKey="views"
          renderLabel={(it) => (
            <a href={it.path} target="_blank" rel="noopener noreferrer">{it.path}</a>
          )}
        />
      </div>
      <div className="admin-card">
        <div className="admin-page-header" style={{ marginBottom: 8 }}>
          <h3>Top supplements</h3>
          <span className="text-secondary" style={{ fontSize: '0.85rem' }}>by detail-page views</span>
        </div>
        <BarRow
          items={supps?.items || []}
          valueKey="views"
          renderLabel={(it) =>
            it.found ? (
              <a href={`/supplement/${it.slug}`} target="_blank" rel="noopener noreferrer">
                {it.brand ? `${it.brand} — ${it.name}` : it.name}
              </a>
            ) : (
              <span title="Slug no longer in catalog">{it.slug}</span>
            )
          }
        />
      </div>
    </div>
  )
}

// -------------------- Searches tab --------------------

function SearchesTab({ range }) {
  const [searches, setSearches] = useState(null)
  const [refs, setRefs] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      analyticsApi.topSearches(range, 25),
      analyticsApi.topReferrers(range, 15),
    ])
      .then(([s, r]) => {
        if (cancelled) return
        setSearches(s)
        setRefs(r)
      })
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [range])

  if (loading) return <div className="admin-loading">Loading…</div>
  if (error) return <div className="admin-error-banner">{error}</div>

  return (
    <div className="admin-analytics-grid">
      <div className="admin-card">
        <div className="admin-page-header" style={{ marginBottom: 8 }}>
          <h3>Top searches</h3>
          <span className="text-secondary" style={{ fontSize: '0.85rem' }}>what visitors are looking for</span>
        </div>
        <BarRow
          items={searches?.items || []}
          labelKey="query"
          valueKey="count"
          renderLabel={(it) => (
            <a href={`/browse?q=${encodeURIComponent(it.query)}`} target="_blank" rel="noopener noreferrer">
              {it.query}
            </a>
          )}
          emptyText="No searches in this range."
        />
      </div>
      <div className="admin-card">
        <div className="admin-page-header" style={{ marginBottom: 8 }}>
          <h3>Top referrers</h3>
          <span className="text-secondary" style={{ fontSize: '0.85rem' }}>where visitors come from</span>
        </div>
        <BarRow
          items={refs?.items || []}
          labelKey="domain"
          valueKey="sessions"
          emptyText="No external referrers yet."
        />
      </div>
    </div>
  )
}

// -------------------- Live tab --------------------

function LiveTab() {
  const [data, setData] = useState(null)
  const [events, setEvents] = useState(null)
  const [error, setError] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)

  useEffect(() => {
    let cancelled = false
    let timer = null
    const tick = async () => {
      try {
        const [a, ev] = await Promise.all([
          analyticsApi.activeNow(),
          analyticsApi.recentEvents(50),
        ])
        if (!cancelled) {
          setData(a)
          setEvents(ev)
          setError('')
        }
      } catch (e) {
        if (!cancelled) setError(e.userMessage || 'Failed to load')
      }
    }
    tick()
    if (autoRefresh) {
      timer = setInterval(tick, 10_000)
    }
    return () => { cancelled = true; if (timer) clearInterval(timer) }
  }, [autoRefresh])

  if (error && !data) return <div className="admin-error-banner">{error}</div>

  return (
    <>
      <div className="admin-stat-grid">
        <div className="admin-stat">
          <div className="lbl"><span className="admin-active-dot" />Active visitors</div>
          <div className="num">{data?.active_visitors ?? '…'}</div>
          <div className="sub">last 5 minutes · {data?.active_sessions ?? 0} sessions</div>
        </div>
        <div className="admin-stat" style={{ gridColumn: 'span 3' }}>
          <div className="lbl">Currently viewing</div>
          <div style={{ marginTop: 8 }}>
            <BarRow
              items={data?.current_pages || []}
              labelKey="path"
              valueKey="viewers"
              renderLabel={(it) => <span>{it.path}</span>}
              emptyText="No active visitors right now."
            />
          </div>
        </div>
      </div>

      <div className="admin-card">
        <div className="admin-page-header" style={{ marginBottom: 8 }}>
          <h3>Recent events</h3>
          <label style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto-refresh (10s)
          </label>
        </div>
        <div className="admin-event-list">
          {(events?.items || []).map((ev) => (
            <div className="admin-event-row" key={ev.id}>
              <span className={`badge ${ev.event_type}`}>{ev.event_type.replace('_', ' ')}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {ev.event_type === 'search'
                    ? <>“<strong>{ev.query}</strong>”</>
                    : ev.path || (ev.entity_id ? `${ev.entity_type} ${ev.entity_id}` : '—')}
                </div>
                <div className="meta">
                  {ev.device_type || 'unknown'}
                  {ev.browser ? ` · ${ev.browser}` : ''}
                  {ev.referrer_domain ? ` · from ${ev.referrer_domain}` : ''}
                  {' · '}{formatRelative(ev.occurred_at)}
                </div>
              </div>
              <div style={{ fontSize: 11, color: '#888' }}>#{ev.id}</div>
            </div>
          ))}
          {events && events.items.length === 0 && (
            <div className="admin-empty">No events yet.</div>
          )}
        </div>
      </div>
    </>
  )
}

// -------------------- Sessions tab --------------------

function SessionsTab({ range }) {
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    analyticsApi.sessions({ range, page, per_page: 25 })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [range, page])

  async function openDetail(sess) {
    setDetail({ session: sess, events: null })
    setDetailLoading(true)
    try {
      const d = await analyticsApi.sessionDetail(sess.session_uuid)
      setDetail(d)
    } catch (e) {
      setDetail({ session: sess, events: [], error: e.userMessage })
    } finally {
      setDetailLoading(false)
    }
  }

  if (loading) return <div className="admin-loading">Loading…</div>
  if (error) return <div className="admin-error-banner">{error}</div>

  return (
    <>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Started</th>
              <th>Visitor</th>
              <th>Pages</th>
              <th>Duration</th>
              <th>Device</th>
              <th>Referrer</th>
              <th>Entry</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(data?.items || []).map((s) => (
              <tr key={s.id}>
                <td>{new Date(s.started_at).toLocaleString()}</td>
                <td title={s.visitor_id} style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                  {s.visitor_id.slice(0, 8)}…
                </td>
                <td>{s.page_view_count}</td>
                <td>{formatDuration(s.duration_seconds)}</td>
                <td>{s.device_type || '—'}{s.browser ? ` · ${s.browser}` : ''}</td>
                <td>{s.referrer_domain || '—'}</td>
                <td className="wrap">{s.entry_path || '—'}</td>
                <td className="row-actions">
                  <button className="admin-btn ghost sm" onClick={() => openDetail(s)}>View</button>
                </td>
              </tr>
            ))}
            {data?.items?.length === 0 && (
              <tr><td colSpan="8" className="admin-empty">No sessions in this range.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="admin-pagination" style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="text-secondary" style={{ fontSize: '0.85rem' }}>
          {data?.total || 0} sessions
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            className="admin-btn ghost sm"
            disabled={page === 1}
            onClick={() => setPage(page - 1)}
          >← Prev</button>
          <span style={{ alignSelf: 'center', fontSize: '0.85rem' }}>
            Page {data?.page || 1} of {data?.total_pages || 1}
          </span>
          <button
            className="admin-btn ghost sm"
            disabled={!data || page >= (data.total_pages || 1)}
            onClick={() => setPage(page + 1)}
          >Next →</button>
        </div>
      </div>

      <Modal
        open={!!detail}
        title={detail ? `Session ${detail.session.session_uuid.slice(0, 8)}…` : ''}
        onClose={() => setDetail(null)}
        wide
      >
        {detail && (
          <>
            <p className="text-secondary" style={{ fontSize: '0.85rem' }}>
              Visitor <code>{detail.session.visitor_id}</code><br />
              {detail.session.device_type} · {detail.session.browser} · {detail.session.os}<br />
              {formatDuration(detail.session.duration_seconds)} · {detail.session.page_view_count} page views<br />
              Referrer: {detail.session.referrer_domain || 'direct'}
            </p>
            <h4 style={{ marginTop: 16, marginBottom: 8 }}>Journey</h4>
            {detailLoading ? <div className="admin-loading">Loading events…</div> : (
              <div className="admin-event-list" style={{ maxHeight: 360 }}>
                {(detail.events || []).map((ev) => (
                  <div className="admin-event-row" key={ev.id}>
                    <span className={`badge ${ev.event_type}`}>{ev.event_type}</span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {ev.event_type === 'search' ? `“${ev.query}”` : ev.path || '—'}
                      </div>
                      <div className="meta">{new Date(ev.occurred_at).toLocaleTimeString()}</div>
                    </div>
                    <div></div>
                  </div>
                ))}
                {(!detail.events || detail.events.length === 0) && (
                  <div className="admin-empty">No events recorded for this session.</div>
                )}
              </div>
            )}
          </>
        )}
      </Modal>
    </>
  )
}
