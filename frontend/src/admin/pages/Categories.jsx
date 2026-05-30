import { useEffect, useState } from 'react'
import { categoriesAdminApi } from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Modal from '../components/Modal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import SortableHeader from '../components/SortableHeader.jsx'

const EMPTY = { name: '', slug: '', description: '', icon: '', sort_order: 0, is_active: true }

export default function Categories() {
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
      const data = await categoriesAdminApi.list(params)
      setItems(data.items || [])
    } catch (e) { setError(e.userMessage || 'Failed to load') }
    finally { setLoading(false) }
  }

  function onSort(col, nextDir) { setSort(col); setDir(nextDir) }

  function openNew() { setEditing(null); setForm({ ...EMPTY, sort_order: items.length + 1 }); setFormError(''); setEditOpen(true) }
  function openEdit(c) {
    setEditing(c)
    setForm({
      name: c.name || '', slug: c.slug || '',
      description: c.description || '', icon: c.icon || '',
      sort_order: c.sort_order ?? 0, is_active: !!c.is_active,
    })
    setFormError(''); setEditOpen(true)
  }

  async function onSave(e) {
    e.preventDefault()
    setFormError(''); setSaving(true)
    try {
      const payload = { ...form }
      payload.sort_order = parseInt(payload.sort_order, 10) || 0
      for (const k of ['description', 'icon']) {
        if (payload[k] === '') payload[k] = null
      }
      if (!editing && !payload.slug) delete payload.slug
      if (editing) await categoriesAdminApi.update(editing.id, payload)
      else await categoriesAdminApi.create(payload)
      setEditOpen(false); load()
    } catch (e) { setFormError(e.userMessage || 'Save failed') }
    finally { setSaving(false) }
  }

  async function onDelete() {
    if (!confirmDel) return
    setDeleting(true)
    try { await categoriesAdminApi.remove(confirmDel.id); setConfirmDel(null); load() }
    catch (e) { setError(e.userMessage || 'Delete failed') }
    finally { setDeleting(false) }
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Categories</h2>
          <div className="desc">{items.length} total · drives navigation and filtering</div>
        </div>
        {can.write && <button className="admin-btn" onClick={openNew}>+ New category</button>}
      </div>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortableHeader column="sort_order" label="#" sort={sort} dir={dir} onSort={onSort} style={{ width: 40 }} />
              <SortableHeader column="name" label="Name" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="slug" label="Slug" sort={sort} dir={dir} onSort={onSort} />
              <th>Icon</th>
              <SortableHeader column="is_active" label="Status" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="supplement_count" label="Supplements" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7" className="admin-loading">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="7" className="admin-empty">No categories.</td></tr>
            ) : items.map((c) => (
              <tr key={c.id}>
                <td>{c.sort_order}</td>
                <td className="wrap"><strong>{c.name}</strong>
                  {c.description && <div className="text-secondary" style={{ fontSize: '0.78rem' }}>{c.description}</div>}
                </td>
                <td><code style={{ fontSize: '0.78rem' }}>{c.slug}</code></td>
                <td>{c.icon || '—'}</td>
                <td><span className={`admin-pill ${c.is_active ? 'green' : 'red'}`}>{c.is_active ? 'active' : 'hidden'}</span></td>
                <td>{c.supplement_count}</td>
                <td className="row-actions">
                  {can.write && <button className="admin-btn secondary sm" onClick={() => openEdit(c)}>Edit</button>}
                  {!can.write && <button className="admin-btn ghost sm" onClick={() => openEdit(c)}>View</button>}
                  {can.delete && <button className="admin-btn danger sm" onClick={() => setConfirmDel(c)}>Delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal
        open={editOpen}
        title={editing ? `Edit '${editing.name}'` : 'New category'}
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
              <input className="admin-input" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} placeholder={editing ? '' : 'auto-generated'} disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>Icon (key)</label>
              <input className="admin-input" value={form.icon || ''} onChange={(e) => setForm({ ...form, icon: e.target.value })} placeholder="vitamin, fish, dumbbell…" disabled={!can.write} />
            </div>
          </div>
          <div className="admin-form-group">
            <label>Description</label>
            <textarea className="admin-textarea" value={form.description || ''} onChange={(e) => setForm({ ...form, description: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Sort order</label>
              <input className="admin-input" type="number" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: e.target.value })} disabled={!can.write} />
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
        message="This will fail if supplements still reference this category."
        onCancel={() => setConfirmDel(null)}
        onConfirm={onDelete}
        loading={deleting}
      />
    </>
  )
}
