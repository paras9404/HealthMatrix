import { useEffect, useState } from 'react'
import { sourcesAdminApi } from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Modal from '../components/Modal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import SortableHeader from '../components/SortableHeader.jsx'

const EMPTY = {
  name: '', slug: '', website_url: '', logo_url: '', description: '',
  rating_scale: '0-100', is_verified: false, is_active: true, sort_order: 0,
}

export default function Sources() {
  const { can } = useAdminAuth()
  const [items, setItems] = useState([])
  const [sort, setSort] = useState('')
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

  useEffect(() => { load() /* eslint-disable-line */ }, [sort, dir])

  async function load() {
    setLoading(true); setError('')
    try {
      const params = sort ? { sort, dir } : {}
      const data = await sourcesAdminApi.list(params)
      setItems(data.items || [])
    } catch (e) { setError(e.userMessage || 'Failed to load') }
    finally { setLoading(false) }
  }

  function onSort(col, nextDir) { setSort(col); setDir(nextDir) }

  function openNew() { setEditing(null); setForm({ ...EMPTY, sort_order: items.length + 1 }); setFormError(''); setEditOpen(true) }
  function openEdit(s) {
    setEditing(s)
    setForm({
      name: s.name || '', slug: s.slug || '',
      website_url: s.website_url || '', logo_url: s.logo_url || '',
      description: s.description || '', rating_scale: s.rating_scale || '0-100',
      is_verified: !!s.is_verified, is_active: !!s.is_active,
      sort_order: s.sort_order ?? 0,
    })
    setFormError(''); setEditOpen(true)
  }

  async function onSave(e) {
    e.preventDefault()
    setFormError(''); setSaving(true)
    try {
      const payload = { ...form }
      payload.sort_order = parseInt(payload.sort_order, 10) || 0
      for (const k of ['logo_url', 'description']) {
        if (payload[k] === '') payload[k] = null
      }
      if (!editing && !payload.slug) delete payload.slug
      if (editing) await sourcesAdminApi.update(editing.id, payload)
      else await sourcesAdminApi.create(payload)
      setEditOpen(false); load()
    } catch (e) { setFormError(e.userMessage || 'Save failed') }
    finally { setSaving(false) }
  }

  async function onDelete() {
    if (!confirmDel) return
    setDeleting(true)
    try { await sourcesAdminApi.remove(confirmDel.id); setConfirmDel(null); load() }
    catch (e) { setError(e.userMessage || 'Delete failed') }
    finally { setDeleting(false) }
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Sources</h2>
          <div className="desc">{items.length} total · testing/rating platforms</div>
        </div>
        {can.write && <button className="admin-btn" onClick={openNew}>+ New source</button>}
      </div>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortableHeader column="sort_order" label="#" sort={sort} dir={dir} onSort={onSort} style={{ width: 40 }} />
              <SortableHeader column="name" label="Name" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="rating_scale" label="Scale" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="is_verified" label="Verified" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="is_active" label="Status" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="supplement_count" label="Supplements" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <th>Website</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="8" className="admin-loading">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="8" className="admin-empty">No sources.</td></tr>
            ) : items.map((s) => (
              <tr key={s.id}>
                <td>{s.sort_order}</td>
                <td className="wrap"><strong>{s.name}</strong>
                  <div className="text-secondary" style={{ fontSize: '0.75rem' }}>{s.slug}</div>
                </td>
                <td>{s.rating_scale}</td>
                <td>{s.is_verified ? <span className="admin-pill blue">verified</span> : '—'}</td>
                <td><span className={`admin-pill ${s.is_active ? 'green' : 'red'}`}>{s.is_active ? 'active' : 'hidden'}</span></td>
                <td>{s.supplement_count}</td>
                <td className="wrap">
                  {s.website_url ? <a href={s.website_url} target="_blank" rel="noopener noreferrer">{shortUrl(s.website_url)}</a> : '—'}
                </td>
                <td className="row-actions">
                  {can.write && <button className="admin-btn secondary sm" onClick={() => openEdit(s)}>Edit</button>}
                  {!can.write && <button className="admin-btn ghost sm" onClick={() => openEdit(s)}>View</button>}
                  {can.delete && <button className="admin-btn danger sm" onClick={() => setConfirmDel(s)}>Delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal
        open={editOpen}
        title={editing ? `Edit '${editing.name}'` : 'New source'}
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
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Name *</label>
              <input className="admin-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Slug</label>
              <input className="admin-input" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} placeholder={editing ? '' : 'auto-generated'} disabled={!can.write} />
            </div>
          </div>
          <div className="admin-form-group">
            <label>Website URL *</label>
            <input className="admin-input" type="url" value={form.website_url || ''} onChange={(e) => setForm({ ...form, website_url: e.target.value })} required disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Logo URL</label>
            <input className="admin-input" type="url" value={form.logo_url || ''} onChange={(e) => setForm({ ...form, logo_url: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Description</label>
            <textarea className="admin-textarea" value={form.description || ''} onChange={(e) => setForm({ ...form, description: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Rating scale</label>
              <input className="admin-input" value={form.rating_scale} onChange={(e) => setForm({ ...form, rating_scale: e.target.value })} placeholder="0-100, Pass/Fail, …" disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Sort order</label>
              <input className="admin-input" type="number" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: e.target.value })} disabled={!can.write} />
            </div>
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Verified lab</label>
              <select className="admin-select" value={form.is_verified ? 'yes' : 'no'} onChange={(e) => setForm({ ...form, is_verified: e.target.value === 'yes' })} disabled={!can.write}>
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
            </div>
            <div className="admin-form-group">
              <label>Status</label>
              <select className="admin-select" value={form.is_active ? 'yes' : 'no'} onChange={(e) => setForm({ ...form, is_active: e.target.value === 'yes' })} disabled={!can.write}>
                <option value="yes">Active</option>
                <option value="no">Hidden</option>
              </select>
            </div>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!confirmDel}
        title={`Delete '${confirmDel?.name}'?`}
        message="This will fail if any ratings reference this source. Deactivate the source instead to hide it without losing data."
        onCancel={() => setConfirmDel(null)}
        onConfirm={onDelete}
        loading={deleting}
      />
    </>
  )
}

function shortUrl(u) { try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u } }
