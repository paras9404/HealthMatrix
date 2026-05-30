import { useEffect, useMemo, useState } from 'react'
import {
  productGroupsAdminApi, brandsAdminApi, categoriesAdminApi,
} from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Modal from '../components/Modal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import Pagination from '../components/Pagination.jsx'

const TABS = [
  { id: 'groups', label: 'Existing groups' },
  { id: 'suggestions', label: 'Suggested matches' },
  { id: 'manual', label: 'Build manually' },
]

export default function ProductGroups() {
  const { can } = useAdminAuth()
  const [tab, setTab] = useState('groups')

  const [brands, setBrands] = useState([])
  const [categories, setCategories] = useState([])

  useEffect(() => {
    let cancelled = false
    Promise.all([
      brandsAdminApi.list({ per_page: 200 }),
      categoriesAdminApi.list(),
    ]).then(([b, c]) => {
      if (cancelled) return
      setBrands(b.items || [])
      setCategories(c.items || [])
    }).catch(() => { /* filters optional */ })
    return () => { cancelled = true }
  }, [])

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Product groups</h2>
          <div className="desc">
            Bundle sibling SKUs (different flavor or pack size of the same product line) so the public site shows them as one listing with a variant selector. Each variant keeps its own rating from each source.
          </div>
        </div>
      </div>

      <div className="admin-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`admin-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'groups' && (
        <GroupsTab brands={brands} categories={categories} canWrite={can.write} />
      )}
      {tab === 'suggestions' && (
        <SuggestionsTab brands={brands} categories={categories} canWrite={can.write} />
      )}
      {tab === 'manual' && (
        <ManualBuilderTab brands={brands} categories={categories} canWrite={can.write} />
      )}
    </>
  )
}

// =====================================================================
// Tab 1 — existing groups
// =====================================================================
function GroupsTab({ brands, categories, canWrite }) {
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [search, setSearch] = useState('')
  const [filterBrand, setFilterBrand] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const [editing, setEditing] = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError('')
    const params = { page, per_page: perPage }
    if (search) params.q = search
    if (filterBrand) params.brand_id = filterBrand
    if (filterCategory) params.category_id = filterCategory
    productGroupsAdminApi.list(params)
      .then((data) => {
        if (cancelled) return
        setItems(data.items || [])
        setTotal(data.total || 0)
        setTotalPages(data.total_pages || 0)
      })
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [page, perPage, refreshKey])

  function applyFilters(e) {
    e?.preventDefault()
    if (page !== 1) setPage(1); else setRefreshKey((k) => k + 1)
  }
  function reload() { setRefreshKey((k) => k + 1) }

  async function onConfirmDelete() {
    if (!confirmDel) return
    setDeleting(true)
    try {
      await productGroupsAdminApi.remove(confirmDel.id)
      setConfirmDel(null)
      reload()
    } catch (e) {
      setError(e.userMessage || 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <form className="admin-filters" onSubmit={applyFilters}>
        <input
          className="admin-input grow"
          placeholder="Search by group name, slug, brand…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="admin-select" value={filterBrand} onChange={(e) => setFilterBrand(e.target.value)}>
          <option value="">All brands</option>
          {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select className="admin-select" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button type="submit" className="admin-btn secondary">Apply</button>
        {(search || filterBrand || filterCategory) && (
          <button type="button" className="admin-btn ghost" onClick={() => {
            setSearch(''); setFilterBrand(''); setFilterCategory(''); setPage(1)
          }}>Clear</button>
        )}
      </form>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Group name</th>
              <th>Brand</th>
              <th>Category</th>
              <th>Variants</th>
              <th>Sources</th>
              <th>Aggregate score</th>
              <th>Reviews</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="8" className="admin-loading">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="8" className="admin-empty">
                No product groups yet. Try the <strong>Suggested matches</strong> tab to spin one up from auto-detected siblings.
              </td></tr>
            ) : items.map((g) => (
              <tr key={g.id}>
                <td className="wrap">
                  <strong>{g.name}</strong>
                  <div className="text-secondary" style={{ fontSize: '0.75rem' }}>{g.slug}</div>
                </td>
                <td>{g.brand?.name || '—'}</td>
                <td>{g.category?.name || '—'}</td>
                <td>{g.member_count}</td>
                <td>
                  {(g.sources || []).length === 0
                    ? <span className="text-secondary">—</span>
                    : g.sources.map((s) => (
                        <span key={s} className="admin-pill blue" style={{ marginRight: 4 }}>{s}</span>
                      ))}
                </td>
                <td>{g.aggregate_score != null ? Math.round(g.aggregate_score) : '—'}</td>
                <td>{g.aggregate_review_count}</td>
                <td className="row-actions">
                  {g.primary_slug && (
                    <a
                      className="admin-btn ghost sm"
                      href={`/supplement/${g.primary_slug}`}
                      target="_blank"
                      rel="noreferrer"
                      title="Open the public product page in a new tab"
                    >
                      View on site ↗
                    </a>
                  )}
                  <button className="admin-btn secondary sm" onClick={() => setEditing(g)}>
                    {canWrite ? 'Manage' : 'View'}
                  </button>
                  {canWrite && <button className="admin-btn danger sm" onClick={() => setConfirmDel(g)}>Ungroup</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} total={total} onChange={setPage} />

      <GroupEditorModal
        groupId={editing?.id}
        open={!!editing}
        canWrite={canWrite}
        onClose={() => setEditing(null)}
        onChanged={() => { reload() }}
      />

      <ConfirmDialog
        open={!!confirmDel}
        title={`Ungroup '${confirmDel?.name}'?`}
        message="This deletes the group wrapper. The supplement rows (variants) keep all their data — they just become standalone listings again."
        confirmLabel="Ungroup"
        onCancel={() => setConfirmDel(null)}
        onConfirm={onConfirmDelete}
        loading={deleting}
      />
    </>
  )
}

// =====================================================================
// Group editor modal — rename, change primary, manage members
// =====================================================================
function GroupEditorModal({ groupId, open, canWrite, onClose, onChanged }) {
  const [group, setGroup] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [primary, setPrimary] = useState('')
  const [variantLabels, setVariantLabels] = useState({}) // supp_id -> label

  // Member-add panel state
  const [showAdd, setShowAdd] = useState(false)
  const [pickerSearch, setPickerSearch] = useState('')
  const [pickerItems, setPickerItems] = useState([])
  const [pickerLoading, setPickerLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [pickerSelected, setPickerSelected] = useState(new Set())

  useEffect(() => {
    if (!open || !groupId) return
    let cancelled = false
    setLoading(true); setError('')
    productGroupsAdminApi.get(groupId)
      .then((g) => {
        if (cancelled) return
        setGroup(g)
        setName(g.name || '')
        setDescription(g.description || '')
        setPrimary(g.primary_supplement_id || '')
        const labelMap = {}
        for (const m of g.members || []) labelMap[m.id] = m.variant_label || ''
        setVariantLabels(labelMap)
      })
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load group'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [open, groupId])

  // Reload picker results when its search box changes (only while it's open).
  useEffect(() => {
    if (!showAdd || !group) return
    let cancelled = false
    setPickerLoading(true)
    productGroupsAdminApi.ungrouped({
      q: pickerSearch || undefined,
      brand_id: group.brand_id,
      category_id: group.category_id,
      per_page: 30,
    })
      .then((d) => !cancelled && setPickerItems(d.items || []))
      .catch(() => !cancelled && setPickerItems([]))
      .finally(() => !cancelled && setPickerLoading(false))
    return () => { cancelled = true }
  }, [pickerSearch, showAdd, group])

  async function reload() {
    if (!groupId) return
    const g = await productGroupsAdminApi.get(groupId)
    setGroup(g)
    onChanged?.()
  }

  async function onSaveMeta() {
    if (!group) return
    setSaving(true); setError('')
    try {
      const patch = {}
      if (name !== group.name) patch.name = name
      if ((description || '') !== (group.description || '')) patch.description = description
      const newPrimary = primary === '' ? null : parseInt(primary, 10)
      if (newPrimary !== group.primary_supplement_id) patch.primary_supplement_id = newPrimary
      if (Object.keys(patch).length) {
        await productGroupsAdminApi.update(group.id, patch)
      }
      // Persist any edited variant labels in parallel.
      const labelOps = []
      for (const m of group.members || []) {
        const next = (variantLabels[m.id] || '').trim()
        const prev = (m.variant_label || '').trim()
        if (next !== prev) {
          labelOps.push(productGroupsAdminApi.setVariantLabel(group.id, m.id, next || null))
        }
      }
      if (labelOps.length) await Promise.all(labelOps)
      await reload()
    } catch (e) {
      setError(e.userMessage || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function onRemoveMember(suppId) {
    if (!group) return
    setError('')
    try {
      const res = await productGroupsAdminApi.removeMember(group.id, suppId)
      if (res?.group_deleted) {
        // Last member removed — group was auto-deleted server-side, close modal.
        onChanged?.()
        onClose?.()
        return
      }
      await reload()
    } catch (e) {
      setError(e.userMessage || 'Remove failed')
    }
  }

  async function onAddSelected() {
    if (!group || pickerSelected.size === 0) return
    setAdding(true); setError('')
    try {
      await productGroupsAdminApi.addMembers(group.id, [...pickerSelected])
      setPickerSelected(new Set())
      setShowAdd(false)
      setPickerSearch('')
      await reload()
    } catch (e) {
      setError(e.userMessage || 'Add failed')
    } finally {
      setAdding(false)
    }
  }

  function togglePick(id) {
    setPickerSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  return (
    <Modal
      open={open}
      title={group ? `Manage '${group.name}'` : 'Loading…'}
      onClose={onClose}
      wide
      footer={
        <>
          {group?.primary_slug && (
            <a
              className="admin-btn ghost"
              href={`/supplement/${group.primary_slug}`}
              target="_blank"
              rel="noreferrer"
              title="Open the public product page in a new tab"
              style={{ marginRight: 'auto' }}
            >
              View on site ↗
            </a>
          )}
          <button className="admin-btn secondary" onClick={onClose}>Close</button>
          {canWrite && (
            <button className="admin-btn" onClick={onSaveMeta} disabled={saving || loading || !group}>
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          )}
        </>
      }
    >
      {loading && <div className="admin-loading">Loading…</div>}
      {error && <div className="admin-error-banner">{error}</div>}
      {!loading && group && (
        <>
          <div className="admin-form-group">
            <label>Group name</label>
            <input className="admin-input" value={name} onChange={(e) => setName(e.target.value)} disabled={!canWrite} />
            <small className="text-secondary">Used as the canonical product name when the public site collapses variants into one card.</small>
          </div>
          <div className="admin-form-group">
            <label>Description (optional)</label>
            <textarea className="admin-textarea" value={description}
              onChange={(e) => setDescription(e.target.value)} disabled={!canWrite}
              placeholder="Override description shown on the grouped product card. Leave blank to use each variant's own description." />
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Brand</label>
              <input className="admin-input" value={group.brand?.name || ''} disabled />
            </div>
            <div className="admin-form-group">
              <label>Category</label>
              <input className="admin-input" value={group.category?.name || ''} disabled />
            </div>
          </div>
          <div className="admin-form-group">
            <label>Primary variant</label>
            <select className="admin-select" value={primary || ''}
              onChange={(e) => setPrimary(e.target.value)} disabled={!canWrite}>
              <option value="">— Pick automatically (most ratings) —</option>
              {(group.members || []).map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
            <small className="text-secondary">The primary variant's image and slug are used as the group's default on the public site.</small>
          </div>

          <div className="admin-section-divider">
            <h4>Variants ({group.member_count})</h4>
            <p className="desc">Each variant is its own database row with its own ratings. Edit the short variant label that distinguishes them (e.g., flavor + pack size).</p>
          </div>

          <div className="pg-variant-list">
            {(group.members || []).map((m) => (
              <div key={m.id} className={`pg-variant-card ${m.is_primary ? 'is-primary' : ''}`}>
                <div className="pg-variant-thumb">
                  {m.image
                    ? <img src={m.image} alt="" onError={(e) => { e.target.style.display = 'none' }} />
                    : <div className="pg-variant-thumb-fallback">no image</div>}
                </div>
                <div className="pg-variant-body">
                  <div className="pg-variant-head">
                    <strong>{m.name}</strong>
                    {m.is_primary && <span className="admin-pill blue" style={{ marginLeft: 6 }}>primary</span>}
                    {!m.is_published && <span className="admin-pill red" style={{ marginLeft: 6 }}>hidden</span>}
                  </div>
                  <div className="text-secondary" style={{ fontSize: '0.75rem' }}>{m.slug}</div>
                  <div className="admin-form-group" style={{ marginTop: 6, marginBottom: 4 }}>
                    <label>Variant label</label>
                    <input
                      className="admin-input"
                      value={variantLabels[m.id] ?? ''}
                      onChange={(e) => setVariantLabels((prev) => ({ ...prev, [m.id]: e.target.value }))}
                      placeholder="e.g., 4Kg Double Rich Chocolate"
                      disabled={!canWrite}
                    />
                  </div>
                  <div className="pg-variant-meta">
                    <span>Score: <strong>{m.aggregate_score != null ? Math.round(m.aggregate_score) : '—'}</strong></span>
                    <span>Reviews: <strong>{m.review_count}</strong></span>
                    {(m.ratings || []).map((r) => (
                      <span key={r.id} className="admin-pill blue" title={`${r.source?.name}: ${r.score ?? '—'}/${r.max_score ?? 100}`}>
                        {r.source?.name}: {r.score != null ? Math.round((r.score / (r.max_score || 100)) * 100) : '—'}
                      </span>
                    ))}
                  </div>
                </div>
                {canWrite && (
                  <button type="button" className="admin-btn danger sm" onClick={() => onRemoveMember(m.id)}>
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>

          {canWrite && (
            <div style={{ marginTop: 12 }}>
              {!showAdd ? (
                <button type="button" className="admin-btn secondary" onClick={() => setShowAdd(true)}>
                  + Add another variant
                </button>
              ) : (
                <div className="pg-add-panel">
                  <div className="admin-form-group">
                    <label>Search supplements (same brand &amp; category)</label>
                    <input className="admin-input" placeholder="Search by name…" value={pickerSearch}
                      onChange={(e) => setPickerSearch(e.target.value)} />
                  </div>
                  <div className="pg-picker">
                    {pickerLoading ? (
                      <div className="admin-loading">Searching…</div>
                    ) : pickerItems.length === 0 ? (
                      <div className="admin-empty">
                        No matching ungrouped supplements in <strong>{group.brand?.name}</strong> / <strong>{group.category?.name}</strong>.
                      </div>
                    ) : pickerItems.map((s) => (
                      <label key={s.id} className="pg-picker-row">
                        <input
                          type="checkbox"
                          checked={pickerSelected.has(s.id)}
                          onChange={() => togglePick(s.id)}
                        />
                        <span className="pg-picker-thumb">
                          {s.image ? <img src={s.image} alt="" onError={(e) => { e.target.style.display = 'none' }} />
                                   : <span className="pg-variant-thumb-fallback">no image</span>}
                        </span>
                        <span className="pg-picker-text">
                          <strong>{s.name}</strong>
                          <small className="text-secondary">{s.slug}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                    <button type="button" className="admin-btn"
                      onClick={onAddSelected} disabled={adding || pickerSelected.size === 0}>
                      {adding ? 'Adding…' : `Add ${pickerSelected.size || ''} variant${pickerSelected.size === 1 ? '' : 's'}`}
                    </button>
                    <button type="button" className="admin-btn secondary"
                      onClick={() => { setShowAdd(false); setPickerSelected(new Set()); setPickerSearch('') }}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Modal>
  )
}

// =====================================================================
// Tab 2 — auto-detected suggestions
// =====================================================================
function SuggestionsTab({ canWrite }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(null) // suggestion currently being turned into a group
  const [createName, setCreateName] = useState('')
  const [createPrimary, setCreatePrimary] = useState('')
  const [saving, setSaving] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [threshold, setThreshold] = useState(0.5)
  const [dismissed, setDismissed] = useState(new Set())

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError('')
    productGroupsAdminApi.suggestions({ threshold, max_groups: 200 })
      .then((d) => {
        if (cancelled) return
        setItems(d.items || [])
        setTotal(d.total || 0)
      })
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load suggestions'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [refreshKey, threshold])

  function suggestionKey(s) {
    return s.members.map((m) => m.id).sort((a, b) => a - b).join(',')
  }
  const visibleItems = useMemo(
    () => items.filter((s) => !dismissed.has(suggestionKey(s))),
    [items, dismissed],
  )

  function startCreate(s) {
    setCreating(s)
    // Default name = the longest member name (usually most descriptive). Admin can edit.
    const longest = [...s.members].sort((a, b) => (b.name?.length || 0) - (a.name?.length || 0))[0]
    setCreateName(longest?.name || '')
    setCreatePrimary(longest?.id || '')
  }

  async function confirmCreate() {
    if (!creating) return
    setSaving(true); setError('')
    try {
      await productGroupsAdminApi.create({
        name: createName.trim(),
        member_ids: creating.members.map((m) => m.id),
        primary_supplement_id: createPrimary ? parseInt(createPrimary, 10) : null,
      })
      setCreating(null)
      setRefreshKey((k) => k + 1)
    } catch (e) {
      setError(e.userMessage || 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  function dismiss(s) {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(suggestionKey(s))
      return next
    })
  }

  return (
    <>
      <div className="admin-filters">
        <label className="admin-inline-label">
          Similarity threshold:
          <input
            type="range" min="0.3" max="0.9" step="0.05"
            value={threshold}
            onChange={(e) => setThreshold(parseFloat(e.target.value))}
            style={{ marginLeft: 8, marginRight: 8 }}
          />
          <strong>{threshold.toFixed(2)}</strong>
        </label>
        <button type="button" className="admin-btn secondary"
          onClick={() => setRefreshKey((k) => k + 1)} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh suggestions'}
        </button>
        <span className="text-secondary" style={{ alignSelf: 'center' }}>
          {total} candidate group{total === 1 ? '' : 's'} ({dismissed.size} dismissed this session)
        </span>
      </div>

      {error && <div className="admin-error-banner">{error}</div>}

      {loading ? (
        <div className="admin-loading">Scanning catalog…</div>
      ) : visibleItems.length === 0 ? (
        <div className="admin-empty">
          No suggestions at this threshold. Try lowering it or check the <strong>Existing groups</strong> tab.
        </div>
      ) : (
        <div className="pg-suggestion-list">
          {visibleItems.map((s) => {
            const key = suggestionKey(s)
            return (
              <div key={key} className="pg-suggestion-card">
                <div className="pg-suggestion-head">
                  <div>
                    <strong>{s.brand?.name || '?'}</strong>
                    <span className="text-secondary" style={{ margin: '0 6px' }}>·</span>
                    <span>{s.category?.name || '?'}</span>
                  </div>
                  <div className="pg-suggestion-meta">
                    <span className={`admin-pill ${s.weakest_similarity >= 0.7 ? 'green' : s.weakest_similarity >= 0.5 ? 'amber' : 'red'}`}>
                      Match score {Math.round((s.weakest_similarity || 0) * 100)}%
                    </span>
                    <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                      {s.members.length} variants
                    </span>
                  </div>
                </div>
                <div className="pg-suggestion-members">
                  {s.members.map((m) => (
                    <div key={m.id} className="pg-suggestion-member">
                      <div className="pg-variant-thumb">
                        {m.image ? <img src={m.image} alt="" onError={(e) => { e.target.style.display = 'none' }} />
                                 : <div className="pg-variant-thumb-fallback">no image</div>}
                      </div>
                      <div>
                        <div>{m.name}</div>
                        <div className="text-secondary" style={{ fontSize: '0.75rem' }}>
                          {m.review_count} review{m.review_count === 1 ? '' : 's'}
                          {m.aggregate_score != null && <> · score {Math.round(m.aggregate_score)}</>}
                          {(m.sources || []).length > 0 && <> · sources: {m.sources.join(', ')}</>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="pg-suggestion-actions">
                  {canWrite && (
                    <button className="admin-btn" onClick={() => startCreate(s)}>
                      Group these
                    </button>
                  )}
                  <button className="admin-btn ghost" onClick={() => dismiss(s)}>
                    Dismiss
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <Modal
        open={!!creating}
        title="Create product group"
        onClose={() => !saving && setCreating(null)}
        footer={
          <>
            <button className="admin-btn secondary" onClick={() => setCreating(null)} disabled={saving}>Cancel</button>
            <button className="admin-btn" onClick={confirmCreate} disabled={saving || !createName.trim()}>
              {saving ? 'Creating…' : 'Create group'}
            </button>
          </>
        }
      >
        {creating && (
          <>
            <div className="admin-form-group">
              <label>Canonical group name</label>
              <input className="admin-input" value={createName} onChange={(e) => setCreateName(e.target.value)} required />
              <small className="text-secondary">Shown as the title on the public listing. The pre-fill is the longest variant name — trim flavor/size details.</small>
            </div>
            <div className="admin-form-group">
              <label>Primary variant</label>
              <select className="admin-select" value={createPrimary || ''}
                onChange={(e) => setCreatePrimary(e.target.value)}>
                <option value="">— Pick automatically (most ratings) —</option>
                {creating.members.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
            <div className="text-secondary" style={{ fontSize: '0.85rem' }}>
              {creating.members.length} variants will join this group. You can add or remove members afterwards.
            </div>
          </>
        )}
      </Modal>
    </>
  )
}

// =====================================================================
// Tab 3 — manual builder
// =====================================================================
function ManualBuilderTab({ brands, categories, canWrite }) {
  const [brand, setBrand] = useState('')
  const [category, setCategory] = useState('')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState(new Map()) // id -> supplement
  const [name, setName] = useState('')
  const [primary, setPrimary] = useState('')
  const [saving, setSaving] = useState(false)
  const [createdId, setCreatedId] = useState(null)

  useEffect(() => {
    if (!brand && !category && !search) {
      setItems([])
      return
    }
    let cancelled = false
    setLoading(true); setError('')
    productGroupsAdminApi.ungrouped({
      brand_id: brand || undefined,
      category_id: category || undefined,
      q: search || undefined,
      per_page: 100,
    })
      .then((d) => !cancelled && setItems(d.items || []))
      .catch((e) => !cancelled && setError(e.userMessage || 'Failed to load'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [brand, category, search])

  // Picked items must agree on brand + category. Surface the conflict so the user sees why.
  const pickedList = [...picked.values()]
  const brandIds = new Set(pickedList.map((s) => s.brand_id))
  const categoryIds = new Set(pickedList.map((s) => s.category_id))
  const compatError = brandIds.size > 1
    ? 'Selected supplements span multiple brands — a group can only contain one brand.'
    : categoryIds.size > 1
      ? 'Selected supplements span multiple categories — a group can only contain one category.'
      : null

  function toggle(s) {
    setPicked((prev) => {
      const next = new Map(prev)
      if (next.has(s.id)) next.delete(s.id); else next.set(s.id, s)
      return next
    })
  }
  function clearPicks() {
    setPicked(new Map())
    setName('')
    setPrimary('')
  }

  async function onCreate(e) {
    e.preventDefault()
    if (compatError) { setError(compatError); return }
    if (pickedList.length < 1) return
    setSaving(true); setError('')
    try {
      const result = await productGroupsAdminApi.create({
        name: name.trim(),
        member_ids: pickedList.map((s) => s.id),
        primary_supplement_id: primary ? parseInt(primary, 10) : null,
      })
      setCreatedId(result.id)
      clearPicks()
    } catch (err) {
      setError(err.userMessage || 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="admin-filters">
        <select className="admin-select" value={brand} onChange={(e) => setBrand(e.target.value)}>
          <option value="">All brands</option>
          {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select className="admin-select" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <input
          className="admin-input grow"
          placeholder="Search by name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {(brand || category || search) && (
          <button type="button" className="admin-btn ghost" onClick={() => { setBrand(''); setCategory(''); setSearch('') }}>
            Clear
          </button>
        )}
      </div>

      {error && <div className="admin-error-banner">{error}</div>}
      {createdId && <div className="admin-info-banner">Group created (#{createdId}). Switch to <strong>Existing groups</strong> to manage it.</div>}

      <div className="pg-manual-grid">
        <div>
          <div className="text-secondary" style={{ marginBottom: 8 }}>
            Pick the supplements that should be variants of the same product line. They must share brand and category.
          </div>
          {loading ? (
            <div className="admin-loading">Loading…</div>
          ) : items.length === 0 ? (
            <div className="admin-empty">
              {brand || category || search
                ? 'No ungrouped supplements match those filters.'
                : 'Pick a brand or type a search term to start.'}
            </div>
          ) : (
            <div className="pg-picker">
              {items.map((s) => (
                <label key={s.id} className="pg-picker-row">
                  <input
                    type="checkbox"
                    checked={picked.has(s.id)}
                    onChange={() => toggle(s)}
                  />
                  <span className="pg-picker-thumb">
                    {s.image ? <img src={s.image} alt="" onError={(e) => { e.target.style.display = 'none' }} />
                             : <span className="pg-variant-thumb-fallback">no image</span>}
                  </span>
                  <span className="pg-picker-text">
                    <strong>{s.name}</strong>
                    <small className="text-secondary">{s.brand?.name} · {s.category?.name}</small>
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>

        <form onSubmit={onCreate} className="pg-manual-pane">
          <h4 style={{ marginTop: 0 }}>Selected variants ({pickedList.length})</h4>
          {pickedList.length === 0 ? (
            <div className="admin-empty">No variants picked yet.</div>
          ) : (
            <ul className="pg-picked-list">
              {pickedList.map((s) => (
                <li key={s.id}>
                  <span>{s.name}</span>
                  <button type="button" className="admin-btn ghost sm" onClick={() => toggle(s)}>×</button>
                </li>
              ))}
            </ul>
          )}

          {compatError && <div className="admin-error-banner">{compatError}</div>}

          <div className="admin-form-group">
            <label>Group name</label>
            <input className="admin-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Canonical product line name" required />
          </div>
          <div className="admin-form-group">
            <label>Primary variant</label>
            <select className="admin-select" value={primary || ''} onChange={(e) => setPrimary(e.target.value)}>
              <option value="">— Pick automatically (most ratings) —</option>
              {pickedList.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button type="submit" className="admin-btn"
              disabled={!canWrite || saving || pickedList.length === 0 || !!compatError || !name.trim()}>
              {saving ? 'Creating…' : 'Create group'}
            </button>
            {pickedList.length > 0 && (
              <button type="button" className="admin-btn secondary" onClick={clearPicks} disabled={saving}>
                Clear
              </button>
            )}
          </div>
        </form>
      </div>
    </>
  )
}
