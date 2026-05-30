import { useEffect, useMemo, useState } from 'react'
import { categoriesAdminApi, sourceImportApi } from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'

const SOURCE_PILL = {
  trustified: { label: 'Trustified', cls: 'blue' },
  labdoor: { label: 'Labdoor', cls: 'amber' },
  'unbox-health': { label: 'Unbox Health', cls: 'purple' },
}

const VERDICT_OPTIONS = [
  '', 'Pass', 'Fail', 'Expired', 'Certified', 'Upcoming',
  'Excellent', 'Good', 'Average', 'Poor',
]

const URL_HINT_BY_HOST = {
  'trustified.in': 'https://www.trustified.in/passandfail/<product-slug>',
  'labdoor.com': 'https://labdoor.com/review/<product-slug>',
  'unboxhealth.in': 'https://www.unboxhealth.in/explore/product/<slug>/<uuid>',
}

function detectSourceLabel(url) {
  if (!url) return null
  const u = url.toLowerCase()
  if (u.includes('trustified')) return SOURCE_PILL.trustified
  if (u.includes('labdoor.com')) return SOURCE_PILL.labdoor
  if (u.includes('unboxhealth')) return SOURCE_PILL['unbox-health']
  return null
}

const BULK_SOURCES = [
  { slug: 'unbox-health', name: 'Unbox Health',
    listing: 'https://www.unboxhealth.in/explore/products-list', cls: 'purple' },
  { slug: 'trustified', name: 'Trustified',
    listing: 'https://www.trustified.in/passandfail', cls: 'blue' },
  { slug: 'labdoor', name: 'Labdoor',
    listing: 'https://labdoor.com/rankings', cls: 'amber',
    note: 'Walks every category page — discovery may take 30–60 seconds.' },
]

export default function SourceImport() {
  const { can } = useAdminAuth()
  const [url, setUrl] = useState('')
  const [scraping, setScraping] = useState(false)
  const [scrapeError, setScrapeError] = useState('')
  const [preview, setPreview] = useState(null)

  // Editable form fields, seeded from preview but admin-overridable.
  const [form, setForm] = useState(null)
  const [categories, setCategories] = useState([])
  const [loadingCats, setLoadingCats] = useState(false)

  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const [importError, setImportError] = useState('')
  const [importResult, setImportResult] = useState(null)

  // Bulk discovery + sync
  const [discoverSource, setDiscoverSource] = useState(null)   // 'unbox-health' | …
  const [discovering, setDiscovering] = useState(false)
  const [discoverError, setDiscoverError] = useState('')
  const [diff, setDiff] = useState(null)                         // discover() response
  const [missingExpanded, setMissingExpanded] = useState(false)
  const [bulkState, setBulkState] = useState(null)
  const [bulkStarting, setBulkStarting] = useState(false)
  const [bulkError, setBulkError] = useState('')

  useEffect(() => {
    setLoadingCats(true)
    categoriesAdminApi.list({ per_page: 200 })
      .then((data) => setCategories(data.items || []))
      .catch(() => {})
      .finally(() => setLoadingCats(false))
  }, [])

  // Pull current bulk worker state on mount so progress is visible if a worker
  // started in another tab is still running.
  useEffect(() => {
    sourceImportApi.bulkImportStatus().then(setBulkState).catch(() => {})
  }, [])

  // While a bulk import is running, poll status every 2s. Stops once the
  // worker reports `running: false`.
  useEffect(() => {
    if (!bulkState?.running) return
    let cancelled = false
    const tick = async () => {
      try {
        const data = await sourceImportApi.bulkImportStatus()
        if (cancelled) return
        setBulkState(data)
        // When the worker finishes, refresh the diff so the new "missing" count
        // reflects what just got imported.
        if (!data.running && discoverSource && data.source === discoverSource) {
          runDiscover(discoverSource).catch(() => {})
        }
      } catch (e) { /* ignore single-tick failures */ }
    }
    const id = setInterval(tick, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [bulkState?.running]) // eslint-disable-line react-hooks/exhaustive-deps

  async function runDiscover(sourceSlug) {
    setDiscoverSource(sourceSlug)
    setDiscovering(true)
    setDiscoverError('')
    setDiff(null)
    setMissingExpanded(false)
    try {
      const data = await sourceImportApi.discover(sourceSlug)
      setDiff(data)
    } catch (err) {
      setDiscoverError(err.userMessage || 'Discovery failed')
    } finally {
      setDiscovering(false)
    }
  }

  async function startBulkImport() {
    if (!diff || !diff.missing?.length) return
    setBulkStarting(true)
    setBulkError('')
    try {
      const data = await sourceImportApi.bulkImportStart(
        diff.source,
        diff.missing.map((m) => m.url),
      )
      if (!data.started) {
        setBulkError(data.message || 'Could not start.')
        if (data.state) setBulkState(data.state)
      } else {
        setBulkState(data.state || { running: true, total: data.total, done: 0 })
      }
    } catch (err) {
      setBulkError(err.userMessage || 'Failed to start bulk import')
    } finally {
      setBulkStarting(false)
    }
  }

  async function stopBulkImport() {
    try { await sourceImportApi.bulkImportStop() } catch (e) { /* ignore */ }
  }

  const detectedSource = useMemo(() => detectSourceLabel(url), [url])

  function resetAll() {
    setUrl('')
    setPreview(null)
    setForm(null)
    setScrapeError('')
    setImportError('')
    setImportMsg('')
    setImportResult(null)
  }

  async function fetchPreview(e) {
    e?.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return
    setScraping(true)
    setScrapeError('')
    setImportError('')
    setImportMsg('')
    setImportResult(null)
    setPreview(null)
    setForm(null)
    try {
      const data = await sourceImportApi.scrape(trimmed)
      setPreview(data)
      setForm({
        name: data.name || '',
        brand_name: data.brand || '',
        category_id: data.category_suggestion?.id || '',
        image_url: data.image_url || '',
        score: data.score == null ? '' : data.score,
        max_score: data.max_score || 100,
        verdict: data.verdict || '',
        summary: data.summary || '',
        report_url: data.report_url || trimmed,
        buy_url: data.buy_url || '',
        tested_at: data.tested_at || '',
        batch_no: data.batch_no || '',
        manufacturing_date: data.manufacturing_date || '',
        expiration_date: data.expiration_date || '',
        tested_by: data.tested_by || '',
      })
    } catch (err) {
      setScrapeError(err.userMessage || 'Failed to fetch the page')
    } finally {
      setScraping(false)
    }
  }

  function setField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function importNow() {
    if (!preview || !form) return
    if (!form.name.trim()) return setImportError('Product name is required.')
    if (!form.brand_name.trim()) return setImportError('Brand is required.')
    if (!form.category_id) return setImportError('Pick a category.')

    setImporting(true)
    setImportError('')
    setImportMsg('')
    try {
      const payload = {
        url: preview.url,
        source_slug: preview.source.slug,
        name: form.name.trim(),
        brand_name: form.brand_name.trim(),
        category_id: parseInt(form.category_id, 10),
        image_url: form.image_url || null,
        score: form.score === '' ? null : parseFloat(form.score),
        max_score: form.max_score ? parseFloat(form.max_score) : 100,
        verdict: form.verdict || null,
        summary: form.summary || null,
        report_url: form.report_url || preview.url,
        buy_url: form.buy_url || null,
        tested_at: form.tested_at || null,
        batch_no: form.batch_no || null,
        manufacturing_date: form.manufacturing_date || null,
        expiration_date: form.expiration_date || null,
        tested_by: form.tested_by || null,
      }
      const data = await sourceImportApi.importProduct(payload)
      setImportResult(data)
      const verb = data.supplement_created ? 'Created' : 'Updated'
      const ratingVerb = data.rating_created ? 'added rating' : 'updated rating'
      setImportMsg(`${verb} supplement and ${ratingVerb} from ${preview.source.name}.`)
      // Drop the just-processed URL from the bulk run's skipped list so the
      // admin sees their progress as they work through it. Match on the
      // preview URL since that's what the table buttons fed in.
      setBulkState((prev) => {
        if (!prev?.skipped_items?.length) return prev
        const next = prev.skipped_items.filter((item) => item.url !== preview.url)
        if (next.length === prev.skipped_items.length) return prev
        return { ...prev, skipped_items: next }
      })
    } catch (err) {
      setImportError(err.userMessage || 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Add product from source</h2>
          <div className="desc">
            Paste a Trustified, Labdoor, or Unbox Health product URL — we&rsquo;ll scrape the page,
            let you review the fields, and create or update the supplement + rating in one click.
          </div>
        </div>
      </div>

      {/* Bulk discover & sync per source */}
      <div className="admin-card" style={{ padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1rem' }}>Bulk sync from a source</h3>
            <div className="text-secondary" style={{ fontSize: '0.85rem', marginTop: 4 }}>
              Discover every product on the source&rsquo;s catalog page, see what&rsquo;s missing from our DB, then import the missing ones in one click.
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
          {BULK_SOURCES.map((s) => (
            <button
              key={s.slug}
              type="button"
              className={`admin-btn ${discoverSource === s.slug && diff ? '' : 'secondary'}`}
              onClick={() => runDiscover(s.slug)}
              disabled={discovering || bulkState?.running}
              title={s.note || `Catalog: ${s.listing}`}
            >
              {discovering && discoverSource === s.slug ? `Discovering ${s.name}…` : `Discover ${s.name}`}
            </button>
          ))}
          <a
            className="admin-btn ghost"
            href={(BULK_SOURCES.find((s) => s.slug === discoverSource)?.listing) || '#'}
            target="_blank"
            rel="noopener noreferrer"
            style={{ display: discoverSource ? 'inline-flex' : 'none', textDecoration: 'none' }}
          >
            Open catalog ↗
          </a>
        </div>

        {discoverError && <div className="admin-error-banner" style={{ marginTop: 10 }}>{discoverError}</div>}

        {diff && (
          <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
            <Stat label="Live products" value={diff.total_live} />
            <Stat label="Already in DB" value={diff.matched_in_db} hint={diff.matched_by_slug_only ? `${diff.matched_by_slug_only} via slug fallback` : null} />
            <Stat label="Missing (will import)" value={diff.missing_count} highlight={diff.missing_count > 0} />
            <Stat label="In DB, no longer live" value={diff.retired_count} muted />
          </div>
        )}

        {diff && diff.missing_count > 0 && (
          <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="admin-btn"
              onClick={startBulkImport}
              disabled={!can.write || bulkStarting || bulkState?.running}
            >
              {bulkStarting ? 'Starting…' : `Import ${diff.missing_count} missing product${diff.missing_count === 1 ? '' : 's'}`}
            </button>
            <button
              type="button"
              className="admin-btn ghost sm"
              onClick={() => setMissingExpanded((v) => !v)}
            >
              {missingExpanded ? 'Hide list' : 'Preview list'}
            </button>
            {!can.write && (
              <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                Read-only role — ask an editor to import.
              </span>
            )}
          </div>
        )}

        {diff && diff.missing_count === 0 && !bulkState?.running && (
          <div className="admin-info-banner" style={{ marginTop: 12 }}>
            Nothing new — every live product on {diff.source_name} is already in our DB.
          </div>
        )}

        {missingExpanded && diff?.missing?.length > 0 && (
          <div style={{
            marginTop: 10, maxHeight: 220, overflowY: 'auto',
            border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)',
            padding: 8, fontSize: '0.8rem', background: 'var(--color-surface-alt)',
          }}>
            {diff.missing.map((m, i) => (
              <div key={m.url} style={{ padding: '2px 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                <span className="text-secondary">{i + 1}.</span>{' '}
                <a href={m.url} target="_blank" rel="noopener noreferrer">{m.slug || m.url}</a>
              </div>
            ))}
          </div>
        )}

        {bulkError && <div className="admin-error-banner" style={{ marginTop: 10 }}>{bulkError}</div>}

        {bulkState?.running && (
          <div style={{ marginTop: 14, padding: 12, background: 'var(--color-surface-alt)', borderRadius: 'var(--radius-sm)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <strong>Importing from {bulkState.source} …</strong>
              <button type="button" className="admin-btn danger sm" onClick={stopBulkImport}>Stop</button>
            </div>
            <div className="iv-bulk-progress" style={{ marginTop: 8 }}>
              <div className="iv-bulk-progress-fill" style={{
                width: `${bulkState.total ? Math.round((bulkState.done / bulkState.total) * 100) : 0}%`,
              }} />
            </div>
            <div className="text-secondary" style={{ fontSize: '0.78rem', marginTop: 6 }}>
              {bulkState.done} / {bulkState.total} · {bulkState.new} new · {bulkState.updated} updated · {bulkState.skipped} skipped
              {bulkState.fetch_fail > 0 && <> · {bulkState.fetch_fail} fetch fails</>}
              {bulkState.errors?.length > 0 && <> · {bulkState.errors.length} errors</>}
              {bulkState.current?.slug && <> · now: <em>{bulkState.current.slug}</em></>}
            </div>
          </div>
        )}

        {bulkState && !bulkState.running && bulkState.finished_at && (
          <div className="admin-info-banner" style={{ marginTop: 10 }}>
            Last run on <strong>{bulkState.source}</strong>: {bulkState.done}/{bulkState.total} processed · {bulkState.new} new · {bulkState.updated} updated · {bulkState.skipped} skipped
            {bulkState.errors?.length > 0 && <> · {bulkState.errors.length} error(s)</>}
          </div>
        )}

        {/* Skipped products with details — admin can scroll the list and
            click "Process manually" to prefill the URL input below. */}
        {bulkState?.skipped_items?.length > 0 && (
          <details className="admin-card" style={{ marginTop: 10, padding: 12 }} open>
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
              Skipped products ({bulkState.skipped_items.length}) — click "Process manually" to handle each
            </summary>
            <div className="text-secondary" style={{ fontSize: '0.78rem', margin: '8px 0' }}>
              These products were skipped during import (usually because the source page didn't carry an explicit Brand). Use the buttons below to load each one in the manual-fetch panel and fill in the brand yourself.
            </div>
            <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid var(--admin-border)', borderRadius: 6 }}>
              <table className="admin-table" style={{ fontSize: '0.85rem' }}>
                <thead>
                  <tr>
                    <th style={{ width: 60 }}>#</th>
                    <th>Slug / name</th>
                    <th style={{ width: 130 }}>Reason</th>
                    <th style={{ width: 220 }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {bulkState.skipped_items.map((item, i) => (
                    <tr key={`${item.slug}-${i}`}>
                      <td className="text-secondary">{i + 1}</td>
                      <td>
                        <div><strong>{item.slug}</strong></div>
                        {item.name && item.name !== item.slug && (
                          <div className="text-secondary" style={{ fontSize: '0.78rem' }}>{item.name}</div>
                        )}
                      </td>
                      <td>
                        <span className="admin-pill amber">{item.reason}</span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="admin-btn secondary sm"
                          onClick={async () => {
                            // Prefill the URL, kick off the scrape immediately,
                            // then scroll the preview into view so the admin
                            // lands directly on the Review & import form.
                            setUrl(item.url)
                            setScraping(true)
                            setScrapeError(''); setImportError(''); setImportMsg('')
                            setImportResult(null); setPreview(null); setForm(null)
                            try {
                              const data = await sourceImportApi.scrape(item.url)
                              setPreview(data)
                              setForm({
                                name: data.name || '',
                                brand_name: data.brand || '',
                                category_id: data.category_suggestion?.id || '',
                                image_url: data.image_url || '',
                                score: data.score == null ? '' : data.score,
                                max_score: data.max_score || 100,
                                verdict: data.verdict || '',
                                summary: data.summary || '',
                                report_url: data.report_url || item.url,
                                buy_url: data.buy_url || '',
                                tested_at: data.tested_at || '',
                                batch_no: data.batch_no || '',
                                manufacturing_date: data.manufacturing_date || '',
                                expiration_date: data.expiration_date || '',
                                tested_by: data.tested_by || '',
                              })
                              setTimeout(() => {
                                document.querySelector('.iv-review-import, .admin-card form, [data-review-import]')
                                  ?.scrollIntoView({ block: 'start', behavior: 'smooth' })
                              }, 80)
                            } catch (err) {
                              setScrapeError(err.userMessage || 'Failed to fetch the page')
                            } finally {
                              setScraping(false)
                            }
                          }}
                        >
                          Process manually
                        </button>
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="admin-btn ghost sm"
                          style={{ marginLeft: 6, textDecoration: 'none' }}
                        >
                          Open ↗
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>

      {/* URL paste row */}
      <div className="admin-card" style={{ padding: 16, marginTop: 12 }}>
        <form onSubmit={fetchPreview} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            className="admin-input grow"
            style={{ flex: 1, minWidth: 280 }}
            placeholder="https://www.trustified.in/passandfail/… or labdoor.com/review/… or unboxhealth.in/explore/product/…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={scraping}
          />
          <button type="submit" className="admin-btn" disabled={scraping || !url.trim()}>
            {scraping ? 'Fetching…' : 'Fetch'}
          </button>
          {(preview || scrapeError) && (
            <button type="button" className="admin-btn ghost" onClick={resetAll}>Clear</button>
          )}
          {detectedSource && !preview && (
            <span className={`admin-pill ${detectedSource.cls}`}>{detectedSource.label}</span>
          )}
        </form>
        <div className="text-secondary" style={{ fontSize: '0.78rem', marginTop: 8 }}>
          Supported hosts: {Object.values(URL_HINT_BY_HOST).map((h, i) => (
            <code key={i} style={{ fontSize: '0.75rem', marginRight: 8 }}>{h}</code>
          ))}
        </div>
      </div>

      {scrapeError && <div className="admin-error-banner" style={{ marginTop: 12 }}>{scrapeError}</div>}

      {preview && form && (
        <div className="iv-shell" style={{ marginTop: 16 }}>
          {/* Left: scraped preview snapshot */}
          <div className="iv-list" style={{ maxHeight: 'none', padding: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <span className={`admin-pill ${SOURCE_PILL[preview.source.slug]?.cls || 'blue'}`}>
                {preview.source.name}
              </span>
              {preview.existing ? (
                <span className="admin-pill amber">Will update existing</span>
              ) : (
                <span className="admin-pill green">Will create new</span>
              )}
            </div>

            <div
              className="si-thumb-wrap"
              style={{ marginBottom: 12 }}
              onMouseEnter={(e) => {
                // Position the fixed-popup near the thumbnail. Prefer the
                // right side, fall back to left, then clamp into viewport.
                const wrap = e.currentTarget
                const popup = wrap.querySelector('.si-thumb-zoom')
                if (!popup) return
                const r = wrap.getBoundingClientRect()
                const w = popup.offsetWidth || 460
                const h = popup.offsetHeight || 460
                const m = 12
                let left = r.right + m
                if (left + w > window.innerWidth - m) {
                  // Try the left side instead.
                  if (r.left - m - w >= m) left = r.left - m - w
                  else left = Math.max(m, window.innerWidth - w - m)
                }
                let top = r.top
                if (top + h > window.innerHeight - m) top = Math.max(m, window.innerHeight - h - m)
                if (top < m) top = m
                popup.style.left = Math.round(left) + 'px'
                popup.style.top = Math.round(top) + 'px'
                popup.classList.add('is-hovered')
              }}
              onMouseLeave={(e) => {
                e.currentTarget.querySelector('.si-thumb-zoom')?.classList.remove('is-hovered')
              }}
            >
              <div className="iv-thumb large iv-thumb-current">
                {preview.image_url
                  ? <img src={preview.image_url} alt="" onError={(e) => { e.target.style.opacity = 0.3 }} />
                  : <span className="text-secondary" style={{ fontSize: '0.78rem' }}>no image</span>}
              </div>
              {preview.image_url && (
                <div className="si-thumb-zoom" aria-hidden="true">
                  <img src={preview.image_url} alt="" />
                </div>
              )}
            </div>

            <div style={{ fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div><strong>{preview.name || '—'}</strong></div>
              <div className="text-secondary">Brand: {preview.brand || '—'}</div>
              <div className="text-secondary">Source category: {preview.raw_category || '—'}</div>
              {preview.score != null && (
                <div>
                  Score:&nbsp;
                  <strong>{preview.score}</strong>
                  {preview.max_score ? ` / ${preview.max_score}` : ''}
                  {preview.grade ? ` · Grade ${preview.grade}` : ''}
                </div>
              )}
              {preview.verdict && <div>Verdict: <strong>{preview.verdict}</strong></div>}
              <div>
                <a href={preview.url} target="_blank" rel="noopener noreferrer">Open report ↗</a>
              </div>
              {preview.buy_url && (
                <div>
                  <a href={preview.buy_url} target="_blank" rel="noopener noreferrer">Buy URL ↗</a>
                </div>
              )}
            </div>

            {preview.existing && (
              <div className="admin-info-banner" style={{ marginTop: 12 }}>
                Existing supplement <strong>#{preview.existing.supplement_id}</strong> &mdash;{' '}
                <em>{preview.existing.supplement_name}</em>
                {preview.existing.rating_id ? ' (rating from this source already exists; values will be replaced)' : ' (no rating from this source yet)'}
              </div>
            )}
          </div>

          {/* Right: editable form */}
          <div className="iv-detail">
            <div className="iv-detail-head">
              <div style={{ flex: 1, minWidth: 0 }}>
                <h3 style={{ margin: 0 }}>Review &amp; import</h3>
                <div className="text-secondary" style={{ fontSize: '0.8rem' }}>
                  Edit anything before saving. Required: name, brand, category.
                </div>
                {(() => {
                  const missing = [
                    !form.name.trim() && 'name',
                    !form.brand_name.trim() && 'brand',
                    !form.category_id && 'category',
                  ].filter(Boolean)
                  if (missing.length === 0) return null
                  return (
                    <div className="text-secondary" style={{ fontSize: '0.78rem', color: '#c62828', marginTop: 4 }}>
                      Missing required: <strong>{missing.join(', ')}</strong>
                    </div>
                  )
                })()}
              </div>
              <div style={{ display: 'flex', gap: 8, flexShrink: 0, alignItems: 'center' }}>
                <button
                  type="button"
                  className="admin-btn"
                  onClick={importNow}
                  disabled={!can.write || importing}
                >
                  {importing
                    ? (preview.existing ? 'Updating…' : 'Creating…')
                    : (preview.existing ? 'Update supplement + rating' : 'Create supplement + rating')}
                </button>
                <button type="button" className="admin-btn ghost sm" onClick={resetAll} disabled={importing}>
                  Cancel
                </button>
              </div>
            </div>

            {importError && <div className="admin-error-banner" style={{ marginTop: 10 }}>{importError}</div>}
            {importMsg && (
              <div className="admin-info-banner" style={{ marginTop: 10 }}>
                {importMsg}
                {importResult?.supplement?.slug && (
                  <>
                    {' '}
                    <a href={`/supplement/${importResult.supplement.slug}`} target="_blank" rel="noopener noreferrer">
                      View on site ↗
                    </a>
                  </>
                )}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
              <div className="admin-form-group" style={{ gridColumn: '1 / -1' }}>
                <label>Product name <span style={{ color: '#c62828' }}>*</span></label>
                <input
                  className="admin-input"
                  value={form.name}
                  onChange={(e) => setField('name', e.target.value)}
                  style={!form.name.trim() ? { borderColor: '#c62828', boxShadow: '0 0 0 1px #c62828' } : undefined}
                />
              </div>

              <div className="admin-form-group">
                <label>Brand name <span style={{ color: '#c62828' }}>*</span></label>
                <input
                  className="admin-input"
                  value={form.brand_name}
                  onChange={(e) => setField('brand_name', e.target.value)}
                  style={!form.brand_name.trim() ? { borderColor: '#c62828', boxShadow: '0 0 0 1px #c62828' } : undefined}
                />
                <div className="text-secondary" style={{ fontSize: '0.75rem' }}>
                  New brands are auto-created on import.
                </div>
              </div>

              <div className="admin-form-group">
                <label>Category <span style={{ color: '#c62828' }}>*</span></label>
                <select
                  className="admin-select"
                  value={form.category_id}
                  onChange={(e) => setField('category_id', e.target.value)}
                  disabled={loadingCats}
                  style={!form.category_id ? { borderColor: '#c62828', boxShadow: '0 0 0 1px #c62828' } : undefined}
                >
                  <option value="">— pick one —</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                      {preview.category_suggestion?.id === c.id ? '  (suggested)' : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div className="admin-form-group">
                <label>Score</label>
                <input
                  className="admin-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={form.score}
                  onChange={(e) => setField('score', e.target.value)}
                />
              </div>

              <div className="admin-form-group">
                <label>Max score</label>
                <input
                  className="admin-input"
                  type="number"
                  step="0.01"
                  min="1"
                  value={form.max_score}
                  onChange={(e) => setField('max_score', e.target.value)}
                />
              </div>

              <div className="admin-form-group">
                <label>Verdict</label>
                <select
                  className="admin-select"
                  value={form.verdict}
                  onChange={(e) => setField('verdict', e.target.value)}
                >
                  {VERDICT_OPTIONS.map((v) => (
                    <option key={v} value={v}>{v || '— none —'}</option>
                  ))}
                </select>
              </div>

              <div className="admin-form-group">
                <label>Tested on</label>
                <input
                  className="admin-input"
                  type="date"
                  value={form.tested_at || ''}
                  onChange={(e) => setField('tested_at', e.target.value)}
                />
              </div>

              <div className="admin-form-group" style={{ gridColumn: '1 / -1' }}>
                <label>Summary</label>
                <textarea
                  className="admin-textarea"
                  rows={3}
                  value={form.summary}
                  onChange={(e) => setField('summary', e.target.value)}
                />
              </div>

              <div className="admin-form-group" style={{ gridColumn: '1 / -1' }}>
                <label>Report URL</label>
                <input
                  className="admin-input"
                  value={form.report_url}
                  onChange={(e) => setField('report_url', e.target.value)}
                />
              </div>

              <div className="admin-form-group" style={{ gridColumn: '1 / -1' }}>
                <label>Buy URL (affiliate)</label>
                <input
                  className="admin-input"
                  value={form.buy_url}
                  onChange={(e) => setField('buy_url', e.target.value)}
                  placeholder="optional"
                />
              </div>

              <div className="admin-form-group" style={{ gridColumn: '1 / -1' }}>
                <label>Image URL</label>
                <input
                  className="admin-input"
                  value={form.image_url}
                  onChange={(e) => setField('image_url', e.target.value)}
                  placeholder="optional — only used when the supplement has no images yet"
                />
              </div>

              <div className="admin-form-group">
                <label>Batch #</label>
                <input
                  className="admin-input"
                  value={form.batch_no}
                  onChange={(e) => setField('batch_no', e.target.value)}
                />
              </div>

              <div className="admin-form-group">
                <label>Tested by</label>
                <input
                  className="admin-input"
                  value={form.tested_by}
                  onChange={(e) => setField('tested_by', e.target.value)}
                />
              </div>

              <div className="admin-form-group">
                <label>Manufacturing date</label>
                <input
                  className="admin-input"
                  value={form.manufacturing_date}
                  onChange={(e) => setField('manufacturing_date', e.target.value)}
                  placeholder="raw string from report"
                />
              </div>

              <div className="admin-form-group">
                <label>Expiration date</label>
                <input
                  className="admin-input"
                  value={form.expiration_date}
                  onChange={(e) => setField('expiration_date', e.target.value)}
                  placeholder="raw string from report"
                />
              </div>
            </div>

            {!can.write && (
              <div className="text-secondary" style={{ fontSize: '0.8rem', marginTop: 14 }}>
                Read-only role — ask an editor to import.
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}

function Stat({ label, value, hint, highlight, muted }) {
  return (
    <div style={{
      padding: '10px 12px',
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-sm)',
      background: highlight ? 'var(--color-primary-soft)' : 'var(--color-surface-alt)',
      opacity: muted ? 0.75 : 1,
    }}>
      <div className="text-secondary" style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        {label}
      </div>
      <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: 2 }}>
        {value?.toLocaleString?.() ?? value}
      </div>
      {hint && <div className="text-secondary" style={{ fontSize: '0.72rem', marginTop: 2 }}>{hint}</div>}
    </div>
  )
}
