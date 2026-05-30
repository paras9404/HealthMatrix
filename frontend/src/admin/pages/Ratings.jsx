import { useEffect, useMemo, useState } from 'react'
import {
  ratingsAdminApi, sourcesAdminApi, supplementsAdminApi,
} from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Modal from '../components/Modal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import Pagination from '../components/Pagination.jsx'
import SortableHeader from '../components/SortableHeader.jsx'

const EMPTY = {
  supplement_id: '', source_id: '', score: '', max_score: 100,
  verdict: '', summary: '', report_url: '', buy_url: '',
  tested_at: '', batch_no: '', tested_by: '',
  manufacturing_date: '', expiration_date: '',
}

export default function Ratings() {
  const { can } = useAdminAuth()
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [filterSource, setFilterSource] = useState('')
  const [sort, setSort] = useState('created_at')
  const [dir, setDir] = useState('desc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [sources, setSources] = useState([])
  const [supplementSearch, setSupplementSearch] = useState('')
  const [supplementResults, setSupplementResults] = useState([])

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const [confirmDel, setConfirmDel] = useState(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    sourcesAdminApi.list().then((d) => setSources(d.items || [])).catch(() => {})
  }, [])
  useEffect(() => { load() /* eslint-disable-line */ }, [page, filterSource, sort, dir])

  const sourceMap = useMemo(() => Object.fromEntries(sources.map((s) => [s.id, s])), [sources])

  function onSort(col, nextDir) { setSort(col); setDir(nextDir); setPage(1) }

  async function load() {
    setLoading(true); setError('')
    try {
      const params = { page, per_page: perPage, sort, dir }
      if (filterSource) params.source_id = filterSource
      const data = await ratingsAdminApi.list(params)
      setItems(data.items || [])
      setTotal(data.total || 0)
      setTotalPages(data.total_pages || 0)
    } catch (e) { setError(e.userMessage || 'Failed to load') }
    finally { setLoading(false) }
  }

  // Search supplements when typing in the modal.
  useEffect(() => {
    if (!editOpen) return
    if (!supplementSearch.trim()) { setSupplementResults([]); return }
    const t = setTimeout(async () => {
      try {
        const data = await supplementsAdminApi.list({ q: supplementSearch.trim(), per_page: 10 })
        setSupplementResults(data.items || [])
      } catch { setSupplementResults([]) }
    }, 200)
    return () => clearTimeout(t)
  }, [supplementSearch, editOpen])

  function openNew() { setEditing(null); setForm(EMPTY); setSupplementSearch(''); setFormError(''); setEditOpen(true) }
  function openEdit(r) {
    setEditing(r)
    setForm({
      supplement_id: r.supplement_id || r.supplement?.id || '',
      source_id: r.source_id || r.source?.id || '',
      score: r.score ?? '',
      max_score: r.max_score ?? 100,
      verdict: r.verdict || '',
      summary: r.summary || '',
      report_url: r.report_url || '',
      buy_url: r.buy_url || '',
      tested_at: r.tested_at ? r.tested_at.slice(0, 10) : '',
      batch_no: r.batch_no || '',
      tested_by: r.tested_by || '',
      manufacturing_date: r.manufacturing_date || '',
      expiration_date: r.expiration_date || '',
    })
    setSupplementSearch(r.supplement?.name || '')
    setFormError(''); setEditOpen(true)
  }

  function pickSupplement(s) {
    setForm({ ...form, supplement_id: s.id })
    setSupplementSearch(`${s.name} (${s.brand?.name || ''})`)
    setSupplementResults([])
  }

  async function onSave(e) {
    e.preventDefault()
    setFormError(''); setSaving(true)
    try {
      const payload = { ...form }
      if (payload.supplement_id) payload.supplement_id = parseInt(payload.supplement_id, 10)
      if (payload.source_id) payload.source_id = parseInt(payload.source_id, 10)
      payload.score = payload.score === '' ? null : parseFloat(payload.score)
      payload.max_score = parseFloat(payload.max_score) || 100
      for (const k of ['verdict', 'summary', 'buy_url', 'batch_no', 'tested_by', 'manufacturing_date', 'expiration_date']) {
        if (payload[k] === '') payload[k] = null
      }
      if (payload.tested_at === '') payload.tested_at = null

      if (editing) await ratingsAdminApi.update(editing.id, payload)
      else await ratingsAdminApi.create(payload)
      setEditOpen(false); load()
    } catch (e) { setFormError(e.userMessage || 'Save failed') }
    finally { setSaving(false) }
  }

  async function onDelete() {
    if (!confirmDel) return
    setDeleting(true)
    try { await ratingsAdminApi.remove(confirmDel.id); setConfirmDel(null); load() }
    catch (e) { setError(e.userMessage || 'Delete failed') }
    finally { setDeleting(false) }
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Ratings</h2>
          <div className="desc">{total.toLocaleString()} total scores from {sources.length} sources</div>
        </div>
        {can.write && <button className="admin-btn" onClick={openNew}>+ New rating</button>}
      </div>

      <div className="admin-filters">
        <select className="admin-select" value={filterSource} onChange={(e) => { setFilterSource(e.target.value); setPage(1) }}>
          <option value="">All sources</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        {filterSource && <button className="admin-btn ghost" onClick={() => { setFilterSource(''); setPage(1) }}>Clear</button>}
      </div>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortableHeader column="supplement" label="Supplement" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="source" label="Source" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="score" label="Score" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <SortableHeader column="verdict" label="Verdict" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="tested_at" label="Tested" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <th>Report</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7" className="admin-loading">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="7" className="admin-empty">No ratings.</td></tr>
            ) : items.map((r) => (
              <tr key={r.id}>
                <td className="wrap">{r.supplement ? <strong>{r.supplement.name}</strong> : `#${r.supplement_id}`}</td>
                <td>{r.source?.name || sourceMap[r.source_id]?.name || `#${r.source_id}`}</td>
                <td>
                  {r.score != null ? `${r.score} / ${r.max_score}` : '—'}
                  {r.normalized_score != null && (
                    <div className="text-secondary" style={{ fontSize: '0.75rem' }}>
                      {r.normalized_score.toFixed(1)}%
                    </div>
                  )}
                </td>
                <td>{r.verdict || '—'}</td>
                <td>{r.tested_at ? new Date(r.tested_at).toLocaleDateString() : '—'}</td>
                <td className="wrap">
                  {r.report_url ? <a href={r.report_url} target="_blank" rel="noopener noreferrer">view</a> : '—'}
                </td>
                <td className="row-actions">
                  {can.write && <button className="admin-btn secondary sm" onClick={() => openEdit(r)}>Edit</button>}
                  {!can.write && <button className="admin-btn ghost sm" onClick={() => openEdit(r)}>View</button>}
                  {can.delete && <button className="admin-btn danger sm" onClick={() => setConfirmDel(r)}>Delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} total={total} onChange={setPage} />

      <Modal
        open={editOpen}
        title={editing ? `Edit rating #${editing.id}` : 'New rating'}
        onClose={() => setEditOpen(false)}
        wide
        footer={
          <>
            <button className="admin-btn secondary" onClick={() => setEditOpen(false)} disabled={saving}>Cancel</button>
            {can.write && (
              <button className="admin-btn" onClick={onSave} disabled={saving}>
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Create'}
              </button>
            )}
          </>
        }
      >
        {!can.write && <div className="admin-info-banner">Read-only view.</div>}
        {formError && <div className="admin-error-banner">{formError}</div>}
        <form onSubmit={onSave}>
          <div className="admin-form-group" style={{ position: 'relative' }}>
            <label>Supplement *</label>
            <input
              className="admin-input"
              value={supplementSearch}
              onChange={(e) => { setSupplementSearch(e.target.value); setForm({ ...form, supplement_id: '' }) }}
              placeholder="Type to search…"
              disabled={!can.write || !!editing}
              required
            />
            {form.supplement_id && (
              <small style={{ color: 'var(--color-text-secondary)' }}>Selected: ID {form.supplement_id}</small>
            )}
            {supplementResults.length > 0 && (
              <div style={{
                position: 'absolute', top: '100%', left: 0, right: 0,
                background: 'white', border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)', zIndex: 10, maxHeight: 240, overflowY: 'auto',
                boxShadow: 'var(--shadow-md)',
              }}>
                {supplementResults.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    style={{
                      display: 'block', width: '100%', padding: '8px 12px',
                      textAlign: 'left', borderBottom: '1px solid var(--color-border)',
                      background: 'transparent', cursor: 'pointer', color: 'inherit',
                    }}
                    onClick={() => pickSupplement(s)}
                  >
                    <strong>{s.name}</strong>
                    <div className="text-secondary" style={{ fontSize: '0.78rem' }}>
                      {s.brand?.name || ''}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="admin-form-group">
            <label>Source *</label>
            <select className="admin-select" value={form.source_id} onChange={(e) => setForm({ ...form, source_id: e.target.value })} required disabled={!can.write || !!editing}>
              <option value="">— Select source —</option>
              {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Score</label>
              <input className="admin-input" type="number" step="0.01" value={form.score} onChange={(e) => setForm({ ...form, score: e.target.value })} disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Max score</label>
              <input className="admin-input" type="number" step="0.01" value={form.max_score} onChange={(e) => setForm({ ...form, max_score: e.target.value })} disabled={!can.write} />
            </div>
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Verdict</label>
              <input className="admin-input" value={form.verdict} onChange={(e) => setForm({ ...form, verdict: e.target.value })} placeholder="Pass / Fail / Excellent…" disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Tested on</label>
              <input className="admin-input" type="date" value={form.tested_at} onChange={(e) => setForm({ ...form, tested_at: e.target.value })} disabled={!can.write} />
            </div>
          </div>
          <div className="admin-form-group">
            <label>Report URL *</label>
            <input className="admin-input" type="url" value={form.report_url} onChange={(e) => setForm({ ...form, report_url: e.target.value })} required disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Buy URL</label>
            <input className="admin-input" type="url" value={form.buy_url} onChange={(e) => setForm({ ...form, buy_url: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Summary</label>
            <textarea className="admin-textarea" value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Batch number</label>
              <input className="admin-input" value={form.batch_no} onChange={(e) => setForm({ ...form, batch_no: e.target.value })} disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Tested by (lab)</label>
              <input className="admin-input" value={form.tested_by} onChange={(e) => setForm({ ...form, tested_by: e.target.value })} disabled={!can.write} />
            </div>
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Manufacturing date</label>
              <input className="admin-input" value={form.manufacturing_date} onChange={(e) => setForm({ ...form, manufacturing_date: e.target.value })} placeholder="raw text from label" disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Expiration date</label>
              <input className="admin-input" value={form.expiration_date} onChange={(e) => setForm({ ...form, expiration_date: e.target.value })} placeholder="raw text from label" disabled={!can.write} />
            </div>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!confirmDel}
        title={`Delete rating #${confirmDel?.id}?`}
        message="This permanently removes the rating. This cannot be undone."
        onCancel={() => setConfirmDel(null)}
        onConfirm={onDelete}
        loading={deleting}
      />
    </>
  )
}
