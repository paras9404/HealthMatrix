import { useEffect, useState } from 'react'
import { brandsAdminApi } from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Modal from '../components/Modal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import Pagination from '../components/Pagination.jsx'
import SortableHeader from '../components/SortableHeader.jsx'

const EMPTY = { name: '', slug: '', website_url: '', logo_url: '', description: '', country: '', is_active: true }

export default function Brands() {
  const { can } = useAdminAuth()
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [search, setSearch] = useState('')
  const [filterActive, setFilterActive] = useState('')
  const [sort, setSort] = useState('name')
  const [dir, setDir] = useState('asc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const [confirmDel, setConfirmDel] = useState(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => { load() /* eslint-disable-line */ }, [page, sort, dir])

  async function load() {
    setLoading(true)
    setError('')
    try {
      const params = { page, per_page: perPage, sort, dir }
      if (search) params.q = search
      if (filterActive) params.is_active = filterActive
      const data = await brandsAdminApi.list(params)
      setItems(data.items || [])
      setTotal(data.total || 0)
      setTotalPages(data.total_pages || 0)
    } catch (e) {
      setError(e.userMessage || 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  function applyFilters(e) {
    e?.preventDefault()
    if (page !== 1) setPage(1); else load()
  }

  function onSort(col, nextDir) {
    setSort(col); setDir(nextDir); setPage(1)
  }

  function openNew() { setEditing(null); setForm(EMPTY); setFormError(''); setEditOpen(true) }
  function openEdit(b) {
    setEditing(b)
    setForm({
      name: b.name || '', slug: b.slug || '',
      website_url: b.website_url || '', logo_url: b.logo_url || '',
      description: b.description || '', country: b.country || '',
      is_active: !!b.is_active,
    })
    setFormError(''); setEditOpen(true)
  }

  async function onSave(e) {
    e.preventDefault()
    setFormError(''); setSaving(true)
    try {
      const payload = { ...form }
      for (const k of ['website_url', 'logo_url', 'description', 'country']) {
        if (payload[k] === '') payload[k] = null
      }
      if (!editing && !payload.slug) delete payload.slug
      if (editing) await brandsAdminApi.update(editing.id, payload)
      else await brandsAdminApi.create(payload)
      setEditOpen(false); load()
    } catch (e) {
      setFormError(e.userMessage || 'Save failed')
    } finally { setSaving(false) }
  }

  async function onDelete() {
    if (!confirmDel) return
    setDeleting(true)
    try {
      await brandsAdminApi.remove(confirmDel.id)
      setConfirmDel(null); load()
    } catch (e) { setError(e.userMessage || 'Delete failed') }
    finally { setDeleting(false) }
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Brands</h2>
          <div className="desc">{total.toLocaleString()} total</div>
        </div>
        {can.write && <button className="admin-btn" onClick={openNew}>+ New brand</button>}
      </div>

      <form className="admin-filters" onSubmit={applyFilters}>
        <input className="admin-input grow" placeholder="Search name or slug…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="admin-select" value={filterActive} onChange={(e) => setFilterActive(e.target.value)}>
          <option value="">All</option>
          <option value="true">Active</option>
          <option value="false">Hidden</option>
        </select>
        <button type="submit" className="admin-btn secondary">Apply</button>
        {(search || filterActive) && (
          <button type="button" className="admin-btn ghost" onClick={() => { setSearch(''); setFilterActive(''); setPage(1) }}>Clear</button>
        )}
      </form>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortableHeader column="name" label="Name" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="slug" label="Slug" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="country" label="Country" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="is_active" label="Status" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="supplement_count" label="Supplements" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <th>Website</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7" className="admin-loading">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="7" className="admin-empty">No brands found.</td></tr>
            ) : items.map((b) => (
              <tr key={b.id}>
                <td className="wrap"><strong>{b.name}</strong></td>
                <td><code style={{ fontSize: '0.78rem' }}>{b.slug}</code></td>
                <td>{b.country || '—'}</td>
                <td>
                  <span className={`admin-pill ${b.is_active ? 'green' : 'red'}`}>{b.is_active ? 'active' : 'hidden'}</span>
                </td>
                <td>{b.supplement_count}</td>
                <td className="wrap">
                  {b.website_url ? <a href={b.website_url} target="_blank" rel="noopener noreferrer">{shortUrl(b.website_url)}</a> : '—'}
                </td>
                <td className="row-actions">
                  {can.write && <button className="admin-btn secondary sm" onClick={() => openEdit(b)}>Edit</button>}
                  {!can.write && <button className="admin-btn ghost sm" onClick={() => openEdit(b)}>View</button>}
                  {can.delete && <button className="admin-btn danger sm" onClick={() => setConfirmDel(b)}>Delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} total={total} onChange={setPage} />

      <Modal
        open={editOpen}
        title={editing ? `Edit '${editing.name}'` : 'New brand'}
        onClose={() => setEditOpen(false)}
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
          <div className="admin-form-group">
            <label>Name *</label>
            <input className="admin-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required disabled={!can.write} />
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Slug</label>
              <input className="admin-input" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })}
                placeholder={editing ? '' : 'auto-generated'} disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Country</label>
              <input className="admin-input" value={form.country || ''} onChange={(e) => setForm({ ...form, country: e.target.value })} disabled={!can.write} />
            </div>
          </div>
          <div className="admin-form-group">
            <label>Website URL</label>
            <input className="admin-input" type="url" value={form.website_url || ''} onChange={(e) => setForm({ ...form, website_url: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Logo URL</label>
            <input className="admin-input" type="url" value={form.logo_url || ''} onChange={(e) => setForm({ ...form, logo_url: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Description</label>
            <textarea className="admin-textarea" value={form.description || ''} onChange={(e) => setForm({ ...form, description: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Status</label>
            <select className="admin-select" value={form.is_active ? 'yes' : 'no'} onChange={(e) => setForm({ ...form, is_active: e.target.value === 'yes' })} disabled={!can.write}>
              <option value="yes">Active — visible on site</option>
              <option value="no">Hidden</option>
            </select>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!confirmDel}
        title={`Delete '${confirmDel?.name}'?`}
        message="This will fail if any supplements still reference this brand. Reassign them first."
        onCancel={() => setConfirmDel(null)}
        onConfirm={onDelete}
        loading={deleting}
      />
    </>
  )
}

function shortUrl(u) {
  try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u }
}
