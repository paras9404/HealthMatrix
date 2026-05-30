import { useEffect, useMemo, useRef, useState } from 'react'
import {
  supplementsAdminApi, brandsAdminApi, categoriesAdminApi,
  sourcesAdminApi, ratingsAdminApi, imagesAdminApi,
} from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Modal from '../components/Modal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import Pagination from '../components/Pagination.jsx'
import SortableHeader from '../components/SortableHeader.jsx'

const FORM_OPTIONS = ['', 'Capsule', 'Tablet', 'Softgel', 'Powder', 'Liquid', 'Gummy', 'Drop', 'Other']
const PRICE_OPTIONS = ['', '$', '$$', '$$$', '$$$$']

const EMPTY = {
  name: '', slug: '', description: '', brand_id: '', category_id: '',
  ingredients: '', serving_size: '', form: '', price_range: '',
  dsld_id: '', upc: '',
  is_published: true, is_featured: false,
}

const EMPTY_RATING = {
  source_id: '', score: '', max_score: 100, verdict: '', summary: '',
  report_url: '', buy_url: '', tested_at: '',
  batch_no: '', tested_by: '', manufacturing_date: '', expiration_date: '',
}

const IMAGE_TYPES = ['main', 'ingredients', 'nutrition_facts', 'back', 'side', 'box', 'label', 'lifestyle', 'other']
const EMPTY_IMAGE_DRAFT = { url_input: '', image_type: 'main', alt_text: '' }

export default function Supplements() {
  const { can } = useAdminAuth()
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [search, setSearch] = useState('')
  const [filterBrand, setFilterBrand] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterPublished, setFilterPublished] = useState('')
  const [sort, setSort] = useState('created_at')
  const [dir, setDir] = useState('desc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [brands, setBrands] = useState([])
  const [categories, setCategories] = useState([])
  const [sources, setSources] = useState([])

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null) // null=new, object=edit
  const [form, setForm] = useState(EMPTY)
  const [ratings, setRatings] = useState([]) // each: {_lid, id?, _deleted?, ...rating fields}
  const [images, setImages] = useState([]) // each: {_lid, id?, _legacy?, _new?, _deleted?, _dirty?, url, image_url?, image_path?, image_type, alt_text, display_order}
  const [imageDraft, setImageDraft] = useState(EMPTY_IMAGE_DRAFT)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [showAdvancedFor, setShowAdvancedFor] = useState({}) // _lid -> bool
  const localIdRef = useRef(0)

  const [confirmDel, setConfirmDel] = useState(null) // supplement object
  const [deleting, setDeleting] = useState(false)
  const [refreshingPriceId, setRefreshingPriceId] = useState(null)
  const [priceFlash, setPriceFlash] = useState(null) // { id, previous, price }
  const [bulkPriceOpen, setBulkPriceOpen] = useState(false)
  const [bulkPriceState, setBulkPriceState] = useState(null) // server status payload
  const [bulkPriceStarting, setBulkPriceStarting] = useState(false)
  const [bulkPriceError, setBulkPriceError] = useState('')
  const [bulkScope, setBulkScope] = useState({ scoped: false, staleOnly: false, concurrency: 4 })
  const sourceMap = useMemo(() => Object.fromEntries(sources.map((s) => [s.id, s])), [sources])

  function newLocalId() { localIdRef.current += 1; return `tmp-${localIdRef.current}` }

  // Lookup brand + category names for the table.
  const brandMap = useMemo(() => Object.fromEntries(brands.map((b) => [b.id, b.name])), [brands])
  const categoryMap = useMemo(() => Object.fromEntries(categories.map((c) => [c.id, c.name])), [categories])

  useEffect(() => { loadFilters() }, [])
  useEffect(() => { load() /* eslint-disable-line */ }, [page, sort, dir])

  function onSort(col, nextDir) { setSort(col); setDir(nextDir); setPage(1) }

  async function loadFilters() {
    try {
      const [b, c, s] = await Promise.all([
        brandsAdminApi.list({ per_page: 200 }),
        categoriesAdminApi.list(),
        sourcesAdminApi.list({ per_page: 200 }),
      ])
      setBrands(b.items || [])
      setCategories(c.items || [])
      setSources((s.items || []).filter((src) => src.is_active !== false))
    } catch (e) {
      // Silently fail — filters are optional. Errors will surface on load().
    }
  }

  async function load() {
    setLoading(true)
    setError('')
    try {
      const params = { page, per_page: perPage, sort, dir }
      if (search) params.q = search
      if (filterBrand) params.brand_id = filterBrand
      if (filterCategory) params.category_id = filterCategory
      if (filterPublished) params.is_published = filterPublished
      const data = await supplementsAdminApi.list(params)
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

  function openNew() {
    setEditing(null)
    setForm({ ...EMPTY, brand_id: brands[0]?.id || '', category_id: categories[0]?.id || '' })
    setRatings([])
    setImages([])
    setImageDraft(EMPTY_IMAGE_DRAFT)
    setShowAdvancedFor({})
    setFormError('')
    setEditOpen(true)
  }

  async function openEdit(s) {
    setEditing(s)
    setForm({
      name: s.name || '',
      slug: s.slug || '',
      description: s.description || '',
      brand_id: s.brand_id || s.brand?.id || '',
      category_id: s.category_id || s.category?.id || '',
      ingredients: s.ingredients || '',
      serving_size: s.serving_size || '',
      form: s.form || '',
      price_range: s.price_range || '',
      dsld_id: s.dsld_id || '',
      upc: s.upc || '',
      is_published: !!s.is_published,
      is_featured: !!s.is_featured,
    })
    setRatings([])
    setImages([])
    setImageDraft(EMPTY_IMAGE_DRAFT)
    setShowAdvancedFor({})
    setFormError('')
    setEditOpen(true)
    // Pull full record to get ratings + images (list endpoint omits them).
    setLoadingDetail(true)
    try {
      const full = await supplementsAdminApi.get(s.id)
      const ratingList = (full.ratings || []).map((r) => ({
        _lid: newLocalId(),
        id: r.id,
        source_id: r.source?.id || r.source_id || '',
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
      }))
      setRatings(ratingList)

      // Build the images list. The gallery() property returns a virtual entry
      // with id=null when only the legacy single image exists — surface that
      // as a "primary (legacy)" card we can migrate or drop on save.
      const imgList = (full.images || []).map((img, idx) => {
        const isLegacy = img.id == null
        return {
          _lid: newLocalId(),
          id: img.id,
          _legacy: isLegacy,
          url: img.url,
          image_url: isLegacy ? (full.image_url || null) : null,
          image_path: isLegacy ? (full.image_path || null) : null,
          image_source: img.source || null,
          image_type: img.type || 'main',
          alt_text: img.alt || '',
          display_order: img.order ?? idx,
        }
      })
      setImages(imgList)
    } catch (e) {
      setFormError(e.userMessage || 'Failed to load existing data')
    } finally {
      setLoadingDetail(false)
    }
  }

  function imagePreviewUrl(img) {
    if (img.url) return img.url
    if (img.image_url) return img.image_url
    if (img.image_path) return `/static/images/supplements/${img.image_path}`
    return null
  }
  function parseUrlInput(val) {
    const trimmed = (val || '').trim()
    if (!trimmed) return { image_url: null, image_path: null }
    if (/^https?:\/\//i.test(trimmed)) return { image_url: trimmed, image_path: null }
    return { image_path: trimmed, image_url: null }
  }
  function addImage() {
    const { image_url, image_path } = parseUrlInput(imageDraft.url_input)
    if (!image_url && !image_path) {
      setFormError('Image URL or filename is required to add an image.')
      return
    }
    const previewUrl = image_url || `/static/images/supplements/${image_path}`
    setImages((prev) => [...prev, {
      _lid: newLocalId(), _new: true,
      url: previewUrl,
      image_url, image_path,
      image_type: imageDraft.image_type,
      alt_text: imageDraft.alt_text,
      display_order: prev.filter((i) => !i._deleted).length,
    }])
    setImageDraft(EMPTY_IMAGE_DRAFT)
    setFormError('')
  }
  function removeImage(lid) {
    setImages((prev) => prev.flatMap((img) => {
      if (img._lid !== lid) return [img]
      if (img._new) return [] // unsaved — drop entirely
      return [{ ...img, _deleted: true }]
    }))
  }
  function undoRemoveImage(lid) {
    setImages((prev) => prev.map((img) => (img._lid === lid ? { ...img, _deleted: false } : img)))
  }
  function updateImage(lid, patch) {
    setImages((prev) => prev.map((img) => {
      if (img._lid !== lid) return img
      const dirty = img.id && !img._legacy ? true : img._dirty
      return { ...img, ...patch, _dirty: dirty }
    }))
  }

  function addRating() {
    setRatings((prev) => [...prev, { _lid: newLocalId(), ...EMPTY_RATING }])
  }
  function updateRating(lid, patch) {
    setRatings((prev) => prev.map((r) => (r._lid === lid ? { ...r, ...patch } : r)))
  }
  function removeRating(lid) {
    setRatings((prev) => prev.flatMap((r) => {
      if (r._lid !== lid) return [r]
      // If unsaved (no DB id), drop. If saved, mark for deletion.
      return r.id ? [{ ...r, _deleted: true }] : []
    }))
  }
  function undoRemoveRating(lid) {
    setRatings((prev) => prev.map((r) => (r._lid === lid ? { ...r, _deleted: false } : r)))
  }
  function toggleAdvanced(lid) {
    setShowAdvancedFor((prev) => ({ ...prev, [lid]: !prev[lid] }))
  }

  function ratingPayload(r) {
    const p = {
      source_id: parseInt(r.source_id, 10),
      report_url: r.report_url.trim(),
      max_score: parseFloat(r.max_score) || 100,
    }
    p.score = r.score === '' || r.score == null ? null : parseFloat(r.score)
    for (const k of ['verdict', 'summary', 'buy_url', 'batch_no', 'tested_by', 'manufacturing_date', 'expiration_date']) {
      p[k] = r[k] === '' ? null : r[k]
    }
    p.tested_at = r.tested_at === '' ? null : r.tested_at
    return p
  }

  function validateRatings() {
    const seen = new Set()
    for (const r of ratings) {
      if (r._deleted) continue
      // Skip entirely-empty rows so users aren't punished for an extra "+ Add" click.
      const isEmpty = !r.source_id && !r.report_url && r.score === '' && !r.verdict && !r.summary
      if (isEmpty) continue
      if (!r.source_id) return 'Each source rating needs a source selected.'
      if (!r.report_url || !r.report_url.trim()) {
        const name = sourceMap[r.source_id]?.name || `source ${r.source_id}`
        return `Report URL is required for the ${name} rating.`
      }
      const sid = String(r.source_id)
      if (seen.has(sid)) {
        const name = sourceMap[r.source_id]?.name || `source ${r.source_id}`
        return `Duplicate rating for ${name} — only one rating per source is allowed.`
      }
      seen.add(sid)
    }
    return null
  }

  async function onSave(e) {
    e.preventDefault()
    setFormError('')

    const ratingError = validateRatings()
    if (ratingError) { setFormError(ratingError); return }

    setSaving(true)
    try {
      const payload = { ...form }
      // Coerce IDs to integers.
      if (payload.brand_id) payload.brand_id = parseInt(payload.brand_id, 10)
      if (payload.category_id) payload.category_id = parseInt(payload.category_id, 10)
      // Strip empty optional fields so backend doesn't store empty strings.
      for (const k of ['form', 'price_range', 'dsld_id', 'upc', 'description', 'ingredients', 'serving_size']) {
        if (payload[k] === '') payload[k] = null
      }
      // Don't send slug on create unless user provided one.
      if (!editing && !payload.slug) delete payload.slug

      // Decide whether to clear the legacy single-image fields on the supplement.
      // - Deleted legacy → clear.
      // - Kept legacy with new gallery entries also added → migrate (clear legacy + push it as a new gallery row so it stays visible).
      const legacyEntry = images.find((img) => img._legacy)
      const willAddGallery = images.some((img) => img._new && !img._deleted)
      const migrateLegacy = legacyEntry && !legacyEntry._deleted && willAddGallery
      const clearLegacy = legacyEntry && (legacyEntry._deleted || migrateLegacy)
      if (clearLegacy) {
        payload.image_url = null
        payload.image_path = null
      }

      let suppId
      if (editing) {
        const updated = await supplementsAdminApi.update(editing.id, payload)
        suppId = updated.id || editing.id
      } else {
        const created = await supplementsAdminApi.create(payload)
        suppId = created.id
      }

      // Stage image ops: deletes for removed gallery rows, creates for new ones,
      // patches for existing rows whose metadata changed.
      const imageOps = []
      for (const img of images) {
        if (img._legacy) {
          if (migrateLegacy) {
            imageOps.push(imagesAdminApi.create({
              supplement_id: suppId,
              image_url: img.image_url || null,
              image_path: img.image_path || null,
              image_source: img.image_source || null,
              image_type: img.image_type || 'main',
              alt_text: img.alt_text || null,
              display_order: 0,
            }))
          }
          continue
        }
        if (img._deleted) {
          if (img.id) imageOps.push(imagesAdminApi.remove(img.id))
          continue
        }
        if (img._new) {
          imageOps.push(imagesAdminApi.create({
            supplement_id: suppId,
            image_url: img.image_url || null,
            image_path: img.image_path || null,
            image_type: img.image_type || 'main',
            alt_text: img.alt_text || null,
            display_order: img.display_order ?? 0,
          }))
          continue
        }
        if (img._dirty && img.id) {
          imageOps.push(imagesAdminApi.update(img.id, {
            image_type: img.image_type || 'main',
            alt_text: img.alt_text || null,
            display_order: img.display_order ?? 0,
          }))
        }
      }

      // Diff and persist ratings. Run in parallel — backend enforces uniqueness per source.
      const ratingOps = []
      for (const r of ratings) {
        if (r._deleted) {
          if (r.id) ratingOps.push(ratingsAdminApi.remove(r.id))
          continue
        }
        const isEmpty = !r.source_id && !r.report_url && r.score === '' && !r.verdict && !r.summary
        if (isEmpty) continue
        const body = { ...ratingPayload(r), supplement_id: suppId }
        if (r.id) {
          ratingOps.push(ratingsAdminApi.update(r.id, body))
        } else {
          ratingOps.push(ratingsAdminApi.create(body))
        }
      }

      const results = await Promise.allSettled([...imageOps, ...ratingOps])
      const failed = results.filter((res) => res.status === 'rejected')
      if (failed.length) {
        const first = failed[0].reason?.userMessage || 'A change failed to save'
        // Supplement itself succeeded — keep modal open so the user can retry the failing piece.
        setFormError(`Supplement saved, but ${failed.length} related change(s) failed. ${first}`)
        load()
        return
      }

      setEditOpen(false)
      load()
    } catch (e) {
      setFormError(e.userMessage || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function onDelete() {
    if (!confirmDel) return
    setDeleting(true)
    try {
      await supplementsAdminApi.remove(confirmDel.id)
      setConfirmDel(null)
      load()
    } catch (e) {
      setError(e.userMessage || 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  async function onRefreshPrice(s) {
    setRefreshingPriceId(s.id)
    setError('')
    try {
      const data = await supplementsAdminApi.refreshPrice(s.id)
      // Patch the in-memory row so the change is visible without a full reload.
      setItems((prev) => prev.map((row) => (
        row.id === s.id
          ? { ...row, amazon_data: { ...(row.amazon_data || {}), price: data.price, price_fetched_at: data.fetched_at } }
          : row
      )))
      setPriceFlash({ id: s.id, previous: data.previous_price, price: data.price })
      // Auto-dismiss the inline note after a few seconds.
      setTimeout(() => {
        setPriceFlash((cur) => (cur && cur.id === s.id ? null : cur))
      }, 6000)
    } catch (e) {
      setError(e.userMessage || 'Failed to refresh price')
    } finally {
      setRefreshingPriceId(null)
    }
  }

  // Initial peek: if a bulk job is already running (admin reloaded the page
  // while one was in flight), surface its state so the panel can be reopened.
  useEffect(() => {
    supplementsAdminApi.bulkRefreshPriceStatus()
      .then((s) => { if (s && s.running) { setBulkPriceState(s); setBulkPriceOpen(true) } })
      .catch(() => {})
  }, [])

  // Poll status while the panel is open and a job is active.
  useEffect(() => {
    if (!bulkPriceOpen) return
    if (bulkPriceState && !bulkPriceState.running) return
    const iv = setInterval(async () => {
      try {
        const s = await supplementsAdminApi.bulkRefreshPriceStatus()
        setBulkPriceState(s)
        if (!s.running) clearInterval(iv)
      } catch (e) {
        // Swallow — UI keeps last state until next tick or the user closes.
      }
    }, 2000)
    return () => clearInterval(iv)
  }, [bulkPriceOpen, bulkPriceState?.running])

  // When a bulk run finishes, refresh the table so the new prices reflect
  // anywhere they're shown (the table itself doesn't render price today, but
  // the score/review columns can still drift if the search index re-syncs).
  useEffect(() => {
    if (!bulkPriceState) return
    if (bulkPriceState.running) return
    if (!bulkPriceState.finished_at) return
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bulkPriceState?.finished_at])

  async function startBulkRefresh() {
    setBulkPriceError('')
    setBulkPriceStarting(true)
    try {
      const body = { stale_only: bulkScope.staleOnly, concurrency: bulkScope.concurrency }
      if (bulkScope.scoped) {
        if (filterBrand) body.brand_id = Number(filterBrand)
        if (filterCategory) body.category_id = Number(filterCategory)
      }
      const res = await supplementsAdminApi.bulkRefreshPriceStart(body)
      if (res.started === false) {
        setBulkPriceError(res.message || 'Could not start')
        if (res.state) setBulkPriceState(res.state)
        return
      }
      setBulkPriceState(res.state)
    } catch (e) {
      setBulkPriceError(e.userMessage || 'Failed to start bulk refresh')
    } finally {
      setBulkPriceStarting(false)
    }
  }

  async function stopBulkRefresh() {
    try {
      await supplementsAdminApi.bulkRefreshPriceStop()
    } catch (e) {
      setBulkPriceError(e.userMessage || 'Failed to stop')
    }
  }

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Supplements</h2>
          <div className="desc">{total.toLocaleString()} total · use filters to narrow down</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {can.write && (
            <button className="admin-btn secondary" onClick={() => setBulkPriceOpen(true)}>
              {bulkPriceState?.running ? `Prices: ${bulkPriceState.done}/${bulkPriceState.total}` : 'Bulk refresh prices'}
            </button>
          )}
          {can.write && <button className="admin-btn" onClick={openNew}>+ New supplement</button>}
        </div>
      </div>

      <form className="admin-filters" onSubmit={applyFilters}>
        <input
          className="admin-input grow"
          placeholder="Search name, slug, brand, UPC…"
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
        <select className="admin-select" value={filterPublished} onChange={(e) => setFilterPublished(e.target.value)}>
          <option value="">All</option>
          <option value="true">Published</option>
          <option value="false">Hidden</option>
        </select>
        <button type="submit" className="admin-btn secondary">Apply</button>
        {(search || filterBrand || filterCategory || filterPublished) && (
          <button type="button" className="admin-btn ghost" onClick={() => {
            setSearch(''); setFilterBrand(''); setFilterCategory(''); setFilterPublished('')
            setPage(1)
          }}>Clear</button>
        )}
      </form>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortableHeader column="name" label="Name" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="brand" label="Brand" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="category" label="Category" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="is_published" label="Status" sort={sort} dir={dir} onSort={onSort} />
              <SortableHeader column="score" label="Score" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <SortableHeader column="review_count" label="Reviews" sort={sort} dir={dir} onSort={onSort} defaultDir="desc" />
              <th>Amazon</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="8" className="admin-loading">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="8" className="admin-empty">No supplements found.</td></tr>
            ) : items.map((s) => (
              <tr key={s.id}>
                <td className="wrap">
                  <strong>{s.name}</strong>
                  <div className="text-secondary" style={{ fontSize: '0.75rem' }}>{s.slug}</div>
                </td>
                <td>{s.brand?.name || brandMap[s.brand_id] || '—'}</td>
                <td>{s.category?.name || categoryMap[s.category_id] || '—'}</td>
                <td>
                  <span className={`admin-pill ${s.is_published ? 'green' : 'red'}`}>
                    {s.is_published ? 'published' : 'hidden'}
                  </span>
                  {s.is_featured && <span className="admin-pill amber" style={{ marginLeft: 4 }}>featured</span>}
                </td>
                <td>{s.aggregate_score != null ? Math.round(s.aggregate_score) : '—'}</td>
                <td>{s.review_count}</td>
                <td>
                  {s.amazon_url ? (
                    <a
                      href={s.amazon_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="admin-amazon-link"
                      onClick={(e) => e.stopPropagation()}
                      title={s.amazon_url}
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                        <polyline points="15 3 21 3 21 9" />
                        <line x1="10" y1="14" x2="21" y2="3" />
                      </svg>
                      <span>{s.amazon_asin || 'View'}</span>
                    </a>
                  ) : (
                    <span className="text-secondary">—</span>
                  )}
                </td>
                <td className="row-actions">
                  <div className="row-actions-inner">
                    {can.write && s.amazon_url && (
                      <button
                        type="button"
                        className={`admin-icon-btn${refreshingPriceId === s.id ? ' is-loading' : ''}${priceFlash && priceFlash.id === s.id ? ' is-flash' : ''}`}
                        onClick={() => onRefreshPrice(s)}
                        disabled={refreshingPriceId === s.id}
                        title={
                          priceFlash && priceFlash.id === s.id && priceFlash.previous && priceFlash.previous !== priceFlash.price
                            ? `Updated: ${priceFlash.previous} → ${priceFlash.price}`
                            : 'Refresh price from Amazon'
                        }
                        aria-label="Refresh price from Amazon"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <polyline points="23 4 23 10 17 10" />
                          <polyline points="1 20 1 14 7 14" />
                          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                        </svg>
                      </button>
                    )}
                    {can.write && <button className="admin-btn secondary sm" onClick={() => openEdit(s)}>Edit</button>}
                    {can.delete && <button className="admin-btn danger sm" onClick={() => setConfirmDel(s)}>Delete</button>}
                    {!can.write && <button className="admin-btn ghost sm" onClick={() => openEdit(s)}>View</button>}
                  </div>
                  {priceFlash && priceFlash.id === s.id && (
                    <div className="text-secondary" style={{ fontSize: '0.72rem', marginTop: 4, textAlign: 'right' }}>
                      {priceFlash.previous && priceFlash.previous !== priceFlash.price
                        ? `${priceFlash.previous} → ${priceFlash.price}`
                        : `Price: ${priceFlash.price}`}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination page={page} totalPages={totalPages} total={total} onChange={setPage} />

      <Modal
        open={editOpen}
        title={editing ? `Edit '${editing.name}'` : 'New supplement'}
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
        {!can.write && <div className="admin-info-banner">Read-only view — your role doesn't allow edits.</div>}
        {formError && <div className="admin-error-banner">{formError}</div>}
        <form onSubmit={onSave} autoComplete="off">
          <div className="admin-form-group">
            <label>Name *</label>
            <input className="admin-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required disabled={!can.write} />
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Slug</label>
              <input className="admin-input" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })}
                placeholder={editing ? '' : 'auto-generated from name'}
                disabled={!can.write} />
            </div>
            <div className="admin-form-group">
              <label>UPC</label>
              <input className="admin-input" value={form.upc || ''} onChange={(e) => setForm({ ...form, upc: e.target.value })} disabled={!can.write} />
            </div>
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Brand *</label>
              <select className="admin-select" value={form.brand_id} onChange={(e) => setForm({ ...form, brand_id: e.target.value })} required disabled={!can.write}>
                <option value="">— Select brand —</option>
                {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div className="admin-form-group">
              <label>Category *</label>
              <select className="admin-select" value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })} required disabled={!can.write}>
                <option value="">— Select category —</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          </div>
          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Form</label>
              <select className="admin-select" value={form.form || ''} onChange={(e) => setForm({ ...form, form: e.target.value })} disabled={!can.write}>
                {FORM_OPTIONS.map((f) => <option key={f} value={f}>{f || '—'}</option>)}
              </select>
            </div>
            <div className="admin-form-group">
              <label>Price range</label>
              <select className="admin-select" value={form.price_range || ''} onChange={(e) => setForm({ ...form, price_range: e.target.value })} disabled={!can.write}>
                {PRICE_OPTIONS.map((p) => <option key={p} value={p}>{p || '—'}</option>)}
              </select>
            </div>
          </div>
          <div className="admin-form-group">
            <label>Serving size</label>
            <input className="admin-input" value={form.serving_size || ''} onChange={(e) => setForm({ ...form, serving_size: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Description</label>
            <textarea className="admin-textarea" value={form.description || ''} onChange={(e) => setForm({ ...form, description: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-form-group">
            <label>Ingredients</label>
            <textarea className="admin-textarea" value={form.ingredients || ''} onChange={(e) => setForm({ ...form, ingredients: e.target.value })} disabled={!can.write} />
          </div>
          <div className="admin-section-divider">
            <h4>Product images</h4>
            <p className="desc">
              Hero shot, ingredients panel, nutrition facts, back of pack… Shown as a gallery on the product page. Changes apply when you click {editing ? 'Save changes' : 'Create'}.
            </p>
          </div>

          {loadingDetail && editing ? (
            <div className="admin-loading">Loading existing images…</div>
          ) : (
            <div className="image-gallery-editor">
              {images.filter((i) => !i._deleted || i.id).length === 0 && (
                <div className="rating-empty">No images yet. Add one below.</div>
              )}

              <div className="image-grid">
                {images.map((img) => {
                  const preview = imagePreviewUrl(img)
                  if (img._deleted) {
                    return (
                      <div key={img._lid} className="image-card removed">
                        <div className="image-thumb">
                          {preview ? <img src={preview} alt="" /> : <div className="image-thumb-fallback">no preview</div>}
                        </div>
                        <div className="image-card-body">
                          <span className="admin-pill red">Will be deleted on save</span>
                          {can.write && (
                            <button type="button" className="admin-btn ghost sm" onClick={() => undoRemoveImage(img._lid)}>
                              Undo
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  }
                  return (
                    <div key={img._lid} className="image-card">
                      <div className="image-thumb">
                        {preview ? (
                          <img
                            src={preview}
                            alt={img.alt_text || ''}
                            onError={(e) => { e.target.outerHTML = '<div class="image-thumb-fallback">image failed to load</div>' }}
                          />
                        ) : (
                          <div className="image-thumb-fallback">no preview</div>
                        )}
                      </div>
                      <div className="image-card-body">
                        <div className="image-pill-row">
                          {img._legacy && <span className="admin-pill amber">primary (legacy)</span>}
                          {img._new && <span className="admin-pill amber">new</span>}
                          {img.id && !img._legacy && <span className="admin-pill blue">saved</span>}
                          {img._dirty && <span className="admin-pill purple">edited</span>}
                        </div>
                        <select
                          className="admin-select"
                          value={img.image_type}
                          onChange={(e) => updateImage(img._lid, { image_type: e.target.value })}
                          disabled={!can.write || img._legacy}
                        >
                          {IMAGE_TYPES.map((t) => (
                            <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                          ))}
                        </select>
                        <input
                          className="admin-input"
                          placeholder="Alt text (optional)"
                          value={img.alt_text}
                          onChange={(e) => updateImage(img._lid, { alt_text: e.target.value })}
                          disabled={!can.write || img._legacy}
                        />
                        {img._legacy && (
                          <small className="text-secondary">
                            Legacy single image. Add new images below to migrate this into the gallery on save, or remove it.
                          </small>
                        )}
                        {can.write && (
                          <button type="button" className="admin-btn danger sm" onClick={() => removeImage(img._lid)}>
                            Remove
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {can.write && (
                <div className="image-add-panel">
                  <strong>Add an image</strong>
                  <input
                    className="admin-input"
                    placeholder="https://… or local-filename.jpg"
                    value={imageDraft.url_input}
                    onChange={(e) => setImageDraft({ ...imageDraft, url_input: e.target.value })}
                  />
                  {imageDraft.url_input.trim() && (
                    <div className="image-draft-preview">
                      <img
                        src={parseUrlInput(imageDraft.url_input).image_url
                          || `/static/images/supplements/${parseUrlInput(imageDraft.url_input).image_path}`}
                        alt="preview"
                        onError={(e) => { e.target.style.display = 'none' }}
                      />
                    </div>
                  )}
                  <div className="admin-row-2">
                    <select
                      className="admin-select"
                      value={imageDraft.image_type}
                      onChange={(e) => setImageDraft({ ...imageDraft, image_type: e.target.value })}
                    >
                      {IMAGE_TYPES.map((t) => (
                        <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                    <input
                      className="admin-input"
                      placeholder="Alt text (optional)"
                      value={imageDraft.alt_text}
                      onChange={(e) => setImageDraft({ ...imageDraft, alt_text: e.target.value })}
                    />
                  </div>
                  <button type="button" className="admin-btn secondary" onClick={addImage} disabled={!imageDraft.url_input.trim()}>
                    + Add image
                  </button>
                </div>
              )}
            </div>
          )}

          <div className="admin-row-2">
            <div className="admin-form-group">
              <label>Published</label>
              <select className="admin-select" value={form.is_published ? 'yes' : 'no'} onChange={(e) => setForm({ ...form, is_published: e.target.value === 'yes' })} disabled={!can.write}>
                <option value="yes">Yes — visible on site</option>
                <option value="no">No — hidden</option>
              </select>
            </div>
            <div className="admin-form-group">
              <label>Featured</label>
              <select className="admin-select" value={form.is_featured ? 'yes' : 'no'} onChange={(e) => setForm({ ...form, is_featured: e.target.value === 'yes' })} disabled={!can.write}>
                <option value="no">No</option>
                <option value="yes">Yes — front-page</option>
              </select>
            </div>
          </div>

          <div className="admin-section-divider">
            <h4>Source ratings</h4>
            <p className="desc">
              One rating per testing source (Labdoor, Trustified, NSF…). Shown on the product page as the per-source breakdown.
            </p>
          </div>

          {loadingDetail ? (
            <div className="admin-loading">Loading existing ratings…</div>
          ) : (
            <div className="rating-cards">
              {ratings.length === 0 && (
                <div className="rating-empty">No source ratings yet. Add one below.</div>
              )}
              {ratings.map((r) => {
                const src = sourceMap[r.source_id]
                const advanced = !!showAdvancedFor[r._lid]
                if (r._deleted) {
                  return (
                    <div key={r._lid} className="rating-card removed">
                      <div className="rating-card-head">
                        <strong>{src?.name || 'Source rating'}</strong>
                        <span className="admin-pill red">Will be deleted on save</span>
                        <button type="button" className="admin-btn ghost sm" onClick={() => undoRemoveRating(r._lid)} disabled={!can.write}>
                          Undo
                        </button>
                      </div>
                    </div>
                  )
                }
                return (
                  <div key={r._lid} className="rating-card">
                    <div className="rating-card-head">
                      <strong>
                        {src?.name || 'New rating'}
                        {r.id && <span className="admin-pill blue" style={{ marginLeft: 8 }}>saved</span>}
                        {!r.id && <span className="admin-pill amber" style={{ marginLeft: 8 }}>new</span>}
                      </strong>
                      {can.write && (
                        <button type="button" className="admin-btn danger sm" onClick={() => removeRating(r._lid)}>
                          Remove
                        </button>
                      )}
                    </div>
                    <div className="admin-row-2">
                      <div className="admin-form-group">
                        <label>Source *</label>
                        <select
                          className="admin-select"
                          value={r.source_id || ''}
                          onChange={(e) => updateRating(r._lid, { source_id: e.target.value ? parseInt(e.target.value, 10) : '' })}
                          disabled={!can.write || !!r.id}
                          required
                        >
                          <option value="">— Select source —</option>
                          {sources.map((s) => (
                            <option key={s.id} value={s.id}>{s.name}{s.is_verified ? ' ✓' : ''}</option>
                          ))}
                        </select>
                        {r.id && <small className="text-secondary">Source can't be changed after saving — delete and re-add to swap.</small>}
                      </div>
                      <div className="admin-form-group">
                        <label>Score / Max</label>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <input
                            className="admin-input"
                            type="number"
                            step="0.01"
                            placeholder="score"
                            value={r.score}
                            onChange={(e) => updateRating(r._lid, { score: e.target.value })}
                            disabled={!can.write}
                          />
                          <input
                            className="admin-input"
                            type="number"
                            step="0.01"
                            placeholder="max"
                            value={r.max_score}
                            onChange={(e) => updateRating(r._lid, { max_score: e.target.value })}
                            disabled={!can.write}
                            style={{ maxWidth: 90 }}
                          />
                        </div>
                      </div>
                    </div>
                    <div className="admin-row-2">
                      <div className="admin-form-group">
                        <label>Verdict</label>
                        <input className="admin-input" value={r.verdict} placeholder="Pass / Fail / Excellent…"
                          onChange={(e) => updateRating(r._lid, { verdict: e.target.value })} disabled={!can.write} />
                      </div>
                      <div className="admin-form-group">
                        <label>Tested on</label>
                        <input className="admin-input" type="date" value={r.tested_at}
                          onChange={(e) => updateRating(r._lid, { tested_at: e.target.value })} disabled={!can.write} />
                      </div>
                    </div>
                    <div className="admin-form-group">
                      <label>Report URL *</label>
                      <input className="admin-input" type="url" value={r.report_url} placeholder="https://…"
                        onChange={(e) => updateRating(r._lid, { report_url: e.target.value })} disabled={!can.write} required />
                    </div>
                    <div className="admin-form-group">
                      <label>Buy URL</label>
                      <input className="admin-input" type="url" value={r.buy_url} placeholder="https://…"
                        onChange={(e) => updateRating(r._lid, { buy_url: e.target.value })} disabled={!can.write} />
                    </div>
                    <div className="admin-form-group">
                      <label>Summary</label>
                      <textarea className="admin-textarea" value={r.summary} rows={2}
                        onChange={(e) => updateRating(r._lid, { summary: e.target.value })} disabled={!can.write} />
                    </div>
                    <button type="button" className="admin-btn ghost sm" onClick={() => toggleAdvanced(r._lid)}>
                      {advanced ? '− Hide batch / lab details' : '+ Add batch / lab details'}
                    </button>
                    {advanced && (
                      <>
                        <div className="admin-row-2" style={{ marginTop: 10 }}>
                          <div className="admin-form-group">
                            <label>Batch number</label>
                            <input className="admin-input" value={r.batch_no}
                              onChange={(e) => updateRating(r._lid, { batch_no: e.target.value })} disabled={!can.write} />
                          </div>
                          <div className="admin-form-group">
                            <label>Tested by (lab)</label>
                            <input className="admin-input" value={r.tested_by} placeholder="Eurofins, NSF…"
                              onChange={(e) => updateRating(r._lid, { tested_by: e.target.value })} disabled={!can.write} />
                          </div>
                        </div>
                        <div className="admin-row-2">
                          <div className="admin-form-group">
                            <label>Manufacturing date</label>
                            <input className="admin-input" value={r.manufacturing_date} placeholder="raw text from label"
                              onChange={(e) => updateRating(r._lid, { manufacturing_date: e.target.value })} disabled={!can.write} />
                          </div>
                          <div className="admin-form-group">
                            <label>Expiration date</label>
                            <input className="admin-input" value={r.expiration_date} placeholder="raw text from label"
                              onChange={(e) => updateRating(r._lid, { expiration_date: e.target.value })} disabled={!can.write} />
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                )
              })}

              {can.write && (
                <button type="button" className="admin-btn secondary" onClick={addRating} disabled={sources.length === 0}>
                  + Add source rating
                </button>
              )}
              {sources.length === 0 && (
                <div className="text-secondary" style={{ fontSize: '0.8rem', marginTop: 6 }}>
                  No active sources defined. Add one in <strong>Sources</strong> first.
                </div>
              )}
            </div>
          )}
        </form>
      </Modal>

      <ConfirmDialog
        open={!!confirmDel}
        title={`Delete '${confirmDel?.name}'?`}
        message="This permanently deletes the supplement and all its ratings and images. This cannot be undone."
        onCancel={() => setConfirmDel(null)}
        onConfirm={onDelete}
        loading={deleting}
      />

      <Modal
        open={bulkPriceOpen}
        title={bulkPriceState && !bulkPriceState.running && bulkPriceState.finished_at
          ? 'Bulk price refresh — done'
          : 'Bulk refresh Amazon prices'}
        onClose={() => setBulkPriceOpen(false)}
        footer={
          <>
            <button className="admin-btn secondary" onClick={() => setBulkPriceOpen(false)} disabled={bulkPriceState?.running}>
              {bulkPriceState?.running ? 'Running…' : 'Close'}
            </button>
            {bulkPriceState?.running ? (
              <button className="admin-btn danger" onClick={stopBulkRefresh}>Stop</button>
            ) : (
              <button className="admin-btn" onClick={startBulkRefresh} disabled={bulkPriceStarting}>
                {bulkPriceStarting ? 'Starting…' : 'Start refresh'}
              </button>
            )}
          </>
        }
      >
        {bulkPriceError && <div className="admin-error-banner">{bulkPriceError}</div>}
        <p className="desc">
          Re-scrapes the saved Amazon listing for every supplement with an{' '}
          <code>amazon_url</code> and updates only the price. Other product fields are left alone.
        </p>

        {!bulkPriceState?.running && (
          <div className="admin-form-group">
            <label>
              <input
                type="checkbox"
                checked={bulkScope.scoped}
                onChange={(e) => setBulkScope({ ...bulkScope, scoped: e.target.checked })}
                disabled={!filterBrand && !filterCategory}
              />
              {' '}Limit to current filters
              {(filterBrand || filterCategory) ? (
                <span className="text-secondary" style={{ marginLeft: 6, fontSize: '0.8rem' }}>
                  ({[
                    filterBrand && (brandMap[filterBrand] || `brand #${filterBrand}`),
                    filterCategory && (categoryMap[filterCategory] || `category #${filterCategory}`),
                  ].filter(Boolean).join(' · ')})
                </span>
              ) : (
                <span className="text-secondary" style={{ marginLeft: 6, fontSize: '0.8rem' }}>
                  (apply a brand/category filter first to enable)
                </span>
              )}
            </label>
            <label style={{ display: 'block', marginTop: 8 }}>
              <input
                type="checkbox"
                checked={bulkScope.staleOnly}
                onChange={(e) => setBulkScope({ ...bulkScope, staleOnly: e.target.checked })}
              />
              {' '}Only refresh prices older than 24h
            </label>
            <label style={{ display: 'block', marginTop: 10 }}>
              Parallel workers:&nbsp;
              <select
                className="admin-select"
                value={bulkScope.concurrency}
                onChange={(e) => setBulkScope({ ...bulkScope, concurrency: Number(e.target.value) })}
                style={{ width: 'auto', display: 'inline-block' }}
              >
                <option value={1}>1 (safest, slowest)</option>
                <option value={2}>2</option>
                <option value={3}>3</option>
                <option value={4}>4 (default)</option>
                <option value={6}>6</option>
                <option value={8}>8 (fastest, risk CAPTCHA)</option>
              </select>
              <span className="text-secondary" style={{ marginLeft: 8, fontSize: '0.8rem' }}>
                Amazon may rate-limit if too aggressive.
              </span>
            </label>
          </div>
        )}

        {bulkPriceState && (
          <div style={{ marginTop: 12 }}>
            {!bulkPriceState.running && bulkPriceState.finished_at && (
              <BulkPriceSummary state={bulkPriceState} />
            )}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <strong>{bulkPriceState.done} / {bulkPriceState.total}</strong>
              <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                {bulkPriceState.running
                  ? `running… ${bulkPriceState.concurrency || 1}× parallel`
                  : bulkPriceState.finished_at ? 'finished' : 'idle'}
              </span>
            </div>
            <div style={{ height: 8, background: 'var(--color-surface-2, #eee)', borderRadius: 4, marginTop: 6, overflow: 'hidden' }}>
              <div
                style={{
                  width: `${bulkPriceState.total ? Math.round((bulkPriceState.done / bulkPriceState.total) * 100) : 0}%`,
                  height: '100%',
                  background: 'var(--color-primary, #0F766E)',
                  transition: 'width 250ms ease',
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 10, fontSize: '0.85rem' }}>
              <span><span className="admin-pill green">{bulkPriceState.updated}</span> updated</span>
              <span><span className="admin-pill blue">{bulkPriceState.unchanged}</span> unchanged</span>
              <span><span className="admin-pill amber">{bulkPriceState.skipped_no_price}</span> no price</span>
              <span><span className="admin-pill red">{bulkPriceState.errors?.length || 0}</span> errors</span>
            </div>
            {bulkPriceState.current && bulkPriceState.running && (
              <div className="text-secondary" style={{ fontSize: '0.8rem', marginTop: 8 }}>
                Now: {bulkPriceState.current.name}
              </div>
            )}
            {bulkPriceState.errors?.length > 0 && (
              <details style={{ marginTop: 10 }} open={!bulkPriceState.running && bulkPriceState.errors.length > 0}>
                <summary>Errors ({bulkPriceState.errors.length})</summary>
                <ul style={{ fontSize: '0.8rem', maxHeight: 200, overflow: 'auto', marginTop: 6 }}>
                  {bulkPriceState.errors.slice(-25).map((e, i) => (
                    <li key={`${e.id}-${i}`}>
                      <strong>{e.name || `#${e.id}`}</strong>: {e.error}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </Modal>
    </>
  )
}

function BulkPriceSummary({ state }) {
  const total = state.total || 0
  const done = state.done || 0
  const updated = state.updated || 0
  const unchanged = state.unchanged || 0
  const skipped = state.skipped_no_price || 0
  const errors = state.errors?.length || 0
  const stopped = done < total

  const duration = (() => {
    if (!state.started_at || !state.finished_at) return null
    const start = Date.parse(state.started_at)
    const end = Date.parse(state.finished_at)
    if (Number.isNaN(start) || Number.isNaN(end)) return null
    const ms = Math.max(0, end - start)
    const sec = Math.round(ms / 1000)
    if (sec < 60) return `${sec}s`
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return s ? `${m}m ${s}s` : `${m}m`
  })()

  // Tone: green when every row updated cleanly; amber when there were
  // soft-failures (no-price / errors) but at least one update landed; red
  // when nothing changed and the run was all errors.
  let tone = 'green'
  let headline = `Refreshed ${updated} ${updated === 1 ? 'price' : 'prices'}`
  if (errors > 0 || skipped > 0) tone = 'amber'
  if (updated === 0 && (errors > 0 || skipped > 0)) {
    tone = 'red'
    headline = errors > 0 ? `All ${errors} ${errors === 1 ? 'attempt' : 'attempts'} failed` : 'No prices updated'
  } else if (updated === 0 && unchanged === total && total > 0) {
    tone = 'blue'
    headline = 'Every price was already up to date'
  }
  if (stopped) headline += ' (stopped early)'

  const palette = {
    green: { bg: 'rgba(16, 122, 90, 0.10)', border: 'rgba(16, 122, 90, 0.35)', text: '#0F766E' },
    blue:  { bg: 'rgba(37, 99, 235, 0.10)',  border: 'rgba(37, 99, 235, 0.35)', text: '#1D4ED8' },
    amber: { bg: 'rgba(217, 119, 6, 0.10)',  border: 'rgba(217, 119, 6, 0.35)', text: '#B45309' },
    red:   { bg: 'rgba(220, 38, 38, 0.10)',  border: 'rgba(220, 38, 38, 0.35)', text: '#B91C1C' },
  }[tone]

  const successRate = total > 0 ? Math.round(((updated + unchanged) / total) * 100) : 0

  return (
    <div
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        color: palette.text,
        padding: '12px 14px',
        borderRadius: 6,
        marginBottom: 12,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
        <strong style={{ fontSize: '0.95rem' }}>{headline}</strong>
        {duration && (
          <span style={{ fontSize: '0.8rem', opacity: 0.8 }}>in {duration}</span>
        )}
      </div>
      <div style={{ marginTop: 6, fontSize: '0.85rem', color: 'var(--color-text, #1f2937)' }}>
        Processed <strong>{done}</strong> of <strong>{total}</strong>
        {total > 0 && <> · {successRate}% success</>}
        {stopped && <> · run stopped before completion</>}
      </div>
      <ul style={{ margin: '8px 0 0 0', padding: 0, listStyle: 'none', display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: '0.85rem', color: 'var(--color-text, #1f2937)' }}>
        <li><strong>{updated}</strong> price{updated === 1 ? '' : 's'} changed</li>
        <li><strong>{unchanged}</strong> already current</li>
        {skipped > 0 && <li><strong>{skipped}</strong> had no price on Amazon</li>}
        {errors > 0 && <li style={{ color: '#B91C1C' }}><strong>{errors}</strong> failed</li>}
      </ul>
    </div>
  )
}
