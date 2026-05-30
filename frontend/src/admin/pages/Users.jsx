import { useEffect, useState } from 'react'
import { usersAdminApi } from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Modal from '../components/Modal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import SortableHeader from '../components/SortableHeader.jsx'

const ROLE_LABELS = {
  readonly: 'Read-only',
  editor: 'Editor (read + write, no delete)',
  superadmin: 'Superadmin (full access)',
}

const EMPTY_NEW = { username: '', email: '', password: '', role: 'readonly', is_active: true }

export default function Users() {
  const { user: me } = useAdminAuth()
  const [items, setItems] = useState([])
  const [sort, setSort] = useState('username')
  const [dir, setDir] = useState('asc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState(EMPTY_NEW)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [editForm, setEditForm] = useState({ email: '', role: '', is_active: true, password: '' })
  const [savingEdit, setSavingEdit] = useState(false)
  const [editError, setEditError] = useState('')

  const [confirmDel, setConfirmDel] = useState(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => { load() /* eslint-disable-line */ }, [sort, dir])

  async function load() {
    setLoading(true); setError('')
    try { setItems((await usersAdminApi.list({ sort, dir })).items || []) }
    catch (e) { setError(e.userMessage || 'Failed to load') }
    finally { setLoading(false) }
  }

  function onSort(col, nextDir) { setSort(col); setDir(nextDir) }

  async function onCreate(e) {
    e.preventDefault()
    setCreateError(''); setCreating(true)
    try {
      const payload = { ...createForm }
      if (!payload.email) payload.email = null
      await usersAdminApi.create(payload)
      setCreateOpen(false)
      setCreateForm(EMPTY_NEW)
      load()
    } catch (e) { setCreateError(e.userMessage || 'Create failed') }
    finally { setCreating(false) }
  }

  function openEdit(u) {
    setEditing(u)
    setEditForm({
      email: u.email || '', role: u.role,
      is_active: !!u.is_active, password: '',
    })
    setEditError(''); setEditOpen(true)
  }

  async function onSaveEdit(e) {
    e.preventDefault()
    setEditError(''); setSavingEdit(true)
    try {
      const payload = {}
      if (editForm.email !== (editing.email || '')) payload.email = editForm.email || null
      if (editForm.role !== editing.role) payload.role = editForm.role
      if (editForm.is_active !== editing.is_active) payload.is_active = editForm.is_active
      if (editForm.password) payload.password = editForm.password
      await usersAdminApi.update(editing.id, payload)
      setEditOpen(false); load()
    } catch (e) { setEditError(e.userMessage || 'Save failed') }
    finally { setSavingEdit(false) }
  }

  async function onDelete() {
    if (!confirmDel) return
    setDeleting(true)
    try { await usersAdminApi.remove(confirmDel.id); setConfirmDel(null); load() }
    catch (e) { setError(e.userMessage || 'Delete failed') }
    finally { setDeleting(false) }
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Admin users</h2>
          <div className="desc">Manage who has access to this panel and what they can do.</div>
        </div>
        <button className="admin-btn" onClick={() => setCreateOpen(true)}>+ New user</button>
      </div>

      <div className="admin-info-banner" style={{ marginBottom: 16 }}>
        <strong>Roles:</strong> Read-only (view) · Editor (create + edit, no delete) · Superadmin (everything, including managing users and viewing audit log).
      </div>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortableHeader column="username" label="Username" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="email" label="Email" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="role" label="Role" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="is_active" label="Status" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="last_login_at" label="Last login" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <SortableHeader column="created_at" label="Created" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7" className="admin-loading">Loading…</td></tr>
            ) : items.map((u) => (
              <tr key={u.id}>
                <td><strong>{u.username}</strong>{u.id === me?.id && <span className="admin-pill blue" style={{ marginLeft: 6 }}>you</span>}</td>
                <td>{u.email || '—'}</td>
                <td><RolePill role={u.role} /></td>
                <td><span className={`admin-pill ${u.is_active ? 'green' : 'red'}`}>{u.is_active ? 'active' : 'disabled'}</span></td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}</td>
                <td>{u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}</td>
                <td className="row-actions">
                  <button className="admin-btn secondary sm" onClick={() => openEdit(u)}>Edit</button>
                  {u.id !== me?.id && <button className="admin-btn danger sm" onClick={() => setConfirmDel(u)}>Delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal
        open={createOpen}
        title="New admin user"
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <button className="admin-btn secondary" onClick={() => setCreateOpen(false)} disabled={creating}>Cancel</button>
            <button className="admin-btn" onClick={onCreate} disabled={creating}>
              {creating ? 'Creating…' : 'Create user'}
            </button>
          </>
        }
      >
        {createError && <div className="admin-error-banner">{createError}</div>}
        <form onSubmit={onCreate} autoComplete="off">
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Username *</label>
              <input className="admin-input" value={createForm.username} onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })} required minLength={3} />
            </div>
            <div className="admin-form-group">
              <label>Email</label>
              <input className="admin-input" type="email" value={createForm.email} onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })} />
            </div>
          </div>
          <div className="admin-form-group">
            <label>Password * (min 8 chars)</label>
            <input className="admin-input" type="password" value={createForm.password} onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })} required minLength={8} autoComplete="new-password" />
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Role *</label>
              <select className="admin-select" value={createForm.role} onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}>
                {Object.entries(ROLE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </div>
            <div className="admin-form-group">
              <label>Status</label>
              <select className="admin-select" value={createForm.is_active ? 'yes' : 'no'} onChange={(e) => setCreateForm({ ...createForm, is_active: e.target.value === 'yes' })}>
                <option value="yes">Active</option>
                <option value="no">Disabled</option>
              </select>
            </div>
          </div>
        </form>
      </Modal>

      <Modal
        open={editOpen}
        title={editing ? `Edit '${editing.username}'` : ''}
        onClose={() => setEditOpen(false)}
        footer={
          <>
            <button className="admin-btn secondary" onClick={() => setEditOpen(false)} disabled={savingEdit}>Cancel</button>
            <button className="admin-btn" onClick={onSaveEdit} disabled={savingEdit}>
              {savingEdit ? 'Saving…' : 'Save changes'}
            </button>
          </>
        }
      >
        {editError && <div className="admin-error-banner">{editError}</div>}
        {editing && (
          <form onSubmit={onSaveEdit} autoComplete="off">
            <div className="admin-form-group">
              <label>Username</label>
              <input className="admin-input" value={editing.username} disabled readOnly />
            </div>
            <div className="admin-form-group">
              <label>Email</label>
              <input className="admin-input" type="email" value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} />
            </div>
            <div className="admin-row-2">
              <div className="admin-form-group">
                <label>Role</label>
                <select className="admin-select" value={editForm.role} onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}>
                  {Object.entries(ROLE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </div>
              <div className="admin-form-group">
                <label>Status</label>
                <select className="admin-select" value={editForm.is_active ? 'yes' : 'no'} onChange={(e) => setEditForm({ ...editForm, is_active: e.target.value === 'yes' })}>
                  <option value="yes">Active</option>
                  <option value="no">Disabled</option>
                </select>
              </div>
            </div>
            <div className="admin-form-group">
              <label>Reset password (leave blank to keep current)</label>
              <input className="admin-input" type="password" value={editForm.password} onChange={(e) => setEditForm({ ...editForm, password: e.target.value })} placeholder="min 8 chars" autoComplete="new-password" />
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog
        open={!!confirmDel}
        title={`Delete '${confirmDel?.username}'?`}
        message="This permanently removes the admin user. Audit log entries will be preserved (with the username as a snapshot)."
        onCancel={() => setConfirmDel(null)}
        onConfirm={onDelete}
        loading={deleting}
      />
    </>
  )
}

function RolePill({ role }) {
  const cls = role === 'superadmin' ? 'purple' : role === 'editor' ? 'blue' : ''
  return <span className={`admin-pill ${cls}`}>{role}</span>
}
