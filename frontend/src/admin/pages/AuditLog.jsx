import { useEffect, useState } from 'react'
import { auditApi } from '../services/adminApi.js'
import Modal from '../components/Modal.jsx'
import Pagination from '../components/Pagination.jsx'
import SortableHeader from '../components/SortableHeader.jsx'

const ACTIONS = ['', 'CREATE', 'UPDATE', 'DELETE', 'LOGIN', 'LOGIN_FAILED', 'LOGOUT']
const ENTITY_TYPES = ['', 'supplement', 'brand', 'category', 'source', 'rating', 'supplement_image', 'admin_user']

export default function AuditLog() {
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(50)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [filterAction, setFilterAction] = useState('')
  const [filterEntity, setFilterEntity] = useState('')
  const [filterUser, setFilterUser] = useState('')
  const [sort, setSort] = useState('created_at')
  const [dir, setDir] = useState('desc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState(null)

  useEffect(() => { load() /* eslint-disable-line */ }, [page, sort, dir])

  function onSort(col, nextDir) { setSort(col); setDir(nextDir); setPage(1) }

  async function load() {
    setLoading(true); setError('')
    try {
      const params = { page, per_page: perPage, sort, dir }
      if (filterAction) params.action = filterAction
      if (filterEntity) params.entity_type = filterEntity
      if (filterUser) params.username = filterUser
      const data = await auditApi.list(params)
      setItems(data.items || [])
      setTotal(data.total || 0)
      setTotalPages(data.total_pages || 0)
    } catch (e) { setError(e.userMessage || 'Failed to load') }
    finally { setLoading(false) }
  }

  function applyFilters(e) {
    e?.preventDefault()
    if (page !== 1) setPage(1); else load()
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Audit log</h2>
          <div className="desc">{total.toLocaleString()} events · all admin actions are recorded here</div>
        </div>
      </div>

      <form className="admin-filters" onSubmit={applyFilters}>
        <select className="admin-select" value={filterAction} onChange={(e) => setFilterAction(e.target.value)}>
          {ACTIONS.map((a) => <option key={a} value={a}>{a || 'All actions'}</option>)}
        </select>
        <select className="admin-select" value={filterEntity} onChange={(e) => setFilterEntity(e.target.value)}>
          {ENTITY_TYPES.map((t) => <option key={t} value={t}>{t || 'All entities'}</option>)}
        </select>
        <input className="admin-input" placeholder="Username" value={filterUser} onChange={(e) => setFilterUser(e.target.value)} />
        <button type="submit" className="admin-btn secondary">Apply</button>
        {(filterAction || filterEntity || filterUser) && (
          <button type="button" className="admin-btn ghost" onClick={() => {
            setFilterAction(''); setFilterEntity(''); setFilterUser(''); setPage(1)
          }}>Clear</button>
        )}
      </form>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortableHeader column="created_at" label="When" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <SortableHeader column="admin_username" label="User" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="action" label="Action" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="entity_type" label="Entity" sort={sort} dir={dir} onSort={onSort} />
              <th>Summary</th>
              <SortableHeader column="ip_address" label="IP" sort={sort} dir={dir} onSort={onSort} />
              <th style={{ textAlign: 'right' }}></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7" className="admin-loading">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="7" className="admin-empty">No events.</td></tr>
            ) : items.map((a) => (
              <tr key={a.id}>
                <td>{a.created_at ? new Date(a.created_at).toLocaleString() : '—'}</td>
                <td>{a.admin_username || '—'}</td>
                <td><ActionPill action={a.action} /></td>
                <td>{a.entity_type ? `${a.entity_type}${a.entity_id ? ` #${a.entity_id}` : ''}` : '—'}</td>
                <td className="wrap">{a.summary || '—'}</td>
                <td>{a.ip_address || '—'}</td>
                <td className="row-actions">
                  {a.changes && <button className="admin-btn ghost sm" onClick={() => setDetail(a)}>Details</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} total={total} onChange={setPage} />

      <Modal
        open={!!detail}
        title={detail ? `Event #${detail.id}` : ''}
        onClose={() => setDetail(null)}
        wide
      >
        {detail && (
          <>
            <p><strong>{detail.action}</strong> {detail.entity_type ? `· ${detail.entity_type}${detail.entity_id ? ` #${detail.entity_id}` : ''}` : ''}</p>
            <p className="text-secondary" style={{ fontSize: '0.85rem' }}>
              {detail.admin_username || 'system'} from {detail.ip_address || 'unknown'} ·{' '}
              {detail.created_at ? new Date(detail.created_at).toLocaleString() : ''}
            </p>
            {detail.user_agent && (
              <p className="text-secondary" style={{ fontSize: '0.78rem', wordBreak: 'break-word' }}>
                User-Agent: {detail.user_agent}
              </p>
            )}
            <h4 style={{ marginTop: 16, marginBottom: 8 }}>Changes</h4>
            <pre className="admin-json">{JSON.stringify(detail.changes, null, 2)}</pre>
          </>
        )}
      </Modal>
    </>
  )
}

function ActionPill({ action }) {
  let cls = ''
  if (action === 'CREATE') cls = 'green'
  else if (action === 'UPDATE') cls = 'blue'
  else if (action === 'DELETE' || action === 'LOGIN_FAILED') cls = 'red'
  else if (action === 'LOGIN' || action === 'LOGOUT') cls = ''
  return <span className={`admin-pill ${cls}`}>{action}</span>
}
