import { useEffect, useMemo, useRef, useState } from 'react'
import { imageValidationApi, imagesAdminApi, supplementsAdminApi } from '../services/adminApi.js'
import { useAdminAuth } from '../AdminAuth.jsx'
import Pagination from '../components/Pagination.jsx'

const FILTERS = [
  { value: 'needs_review', label: 'Needs review (≤1 image)' },
  { value: 'no_images', label: 'No images' },
  { value: 'single_image', label: 'Single image only' },
  { value: 'all', label: 'All products' },
]

const VALIDATED_KEY = 'hm_image_validation_done_v1'
const HIDE_DONE_KEY = 'hm_image_validation_hide_done_v1'

function loadValidated() {
  try { return new Set(JSON.parse(localStorage.getItem(VALIDATED_KEY) || '[]')) }
  catch { return new Set() }
}
function saveValidated(set) {
  localStorage.setItem(VALIDATED_KEY, JSON.stringify([...set]))
}
function loadHideDone() {
  return localStorage.getItem(HIDE_DONE_KEY) === '1'
}

export default function ImageValidation() {
  const { can } = useAdminAuth()
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(20)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [filter, setFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('') // '' = all sources
  const [sourceOptions, setSourceOptions] = useState([])
  const [search, setSearch] = useState('')
  const [pendingSearch, setPendingSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [validated, setValidated] = useState(loadValidated)
  const [hideDone, setHideDone] = useState(loadHideDone)

  // Right-panel state for the currently-selected product.
  const [selected, setSelected] = useState(null)
  const [selectedDetail, setSelectedDetail] = useState(null) // full record (images + amazon_data + ...)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [amazonUrl, setAmazonUrl] = useState('')
  const [scrapeData, setScrapeData] = useState(null)
  const [scraping, setScraping] = useState(false)
  const [scrapeError, setScrapeError] = useState('')
  const [picked, setPicked] = useState(new Set()) // url strings selected for import
  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const [autoSearching, setAutoSearching] = useState(false)
  const [autoCandidates, setAutoCandidates] = useState(null) // null=not run, []=ran with no matches
  const [autoSearchError, setAutoSearchError] = useState('')
  const [autoFromCache, setAutoFromCache] = useState(false)
  const [autoSearchedAt, setAutoSearchedAt] = useState(null)

  // Inline product-name editing in the right panel. The draft seeds whenever
  // the selected product changes; a Save action PATCHes the supplement and
  // optionally flips the validated flag in one click.
  const [nameDraft, setNameDraft] = useState('')
  const [savingName, setSavingName] = useState(false)
  const [nameSaveMsg, setNameSaveMsg] = useState('')

  useEffect(() => {
    setNameDraft(selectedDetail?.name || selected?.name || '')
    setNameSaveMsg('')
  }, [selected?.id, selectedDetail?.name])

  // Bulk search state (server-driven via polling).
  const [bulkState, setBulkState] = useState(null)
  const [bulkStarting, setBulkStarting] = useState(false)
  const [bulkError, setBulkError] = useState('')

  // Bulk resolve Labdoor → Amazon state (separate worker on the backend).
  const [labdoorState, setLabdoorState] = useState(null)
  const [labdoorStarting, setLabdoorStarting] = useState(false)
  const [labdoorError, setLabdoorError] = useState('')

  // Bulk resolve Trustified → Amazon state.
  const [trustifiedState, setTrustifiedState] = useState(null)
  const [trustifiedStarting, setTrustifiedStarting] = useState(false)
  const [trustifiedError, setTrustifiedError] = useState('')

  // Bulk auto-import — for products with any verified Amazon URL, scrape
  // Amazon and replace gallery + save info without manual review.
  const [autoImportState, setAutoImportState] = useState(null)
  const [autoImportStarting, setAutoImportStarting] = useState(false)
  const [autoImportError, setAutoImportError] = useState('')

  // Zoomed image lightbox (Current images + side-by-side compare share it).
  const [zoom, setZoom] = useState(null) // { url, alt } | null

  // The hover preview floats next to the hovered candidate card. We compute
  // its position on hover so it stays inside the viewport regardless of where
  // the card sits — purely-CSS absolute positioning would clip when a card is
  // near the right or bottom edge of the viewport.
  const candidateGridRef = useRef(null)
  function positionHoverPreview(e) {
    const card = e.currentTarget
    const preview = card.querySelector(':scope > .iv-candidate-hover')
    if (!preview) return
    const cardRect = card.getBoundingClientRect()
    const previewW = preview.offsetWidth || 320
    const previewH = preview.offsetHeight || 360
    const margin = 10
    // Horizontal: prefer the right side of the card, fall back to the left
    // when there isn't enough room. If neither side fits, clamp to viewport.
    const spaceRight = window.innerWidth - cardRect.right - margin
    const spaceLeft = cardRect.left - margin
    let left
    if (spaceRight >= previewW) {
      left = cardRect.right + margin
    } else if (spaceLeft >= previewW) {
      left = cardRect.left - previewW - margin
    } else {
      left = Math.max(margin, Math.min(window.innerWidth - previewW - margin, cardRect.left))
    }
    // Vertical: align with the card top, then clamp into the viewport.
    let top = cardRect.top
    if (top + previewH > window.innerHeight - margin) {
      top = Math.max(margin, window.innerHeight - previewH - margin)
    }
    if (top < margin) top = margin
    preview.style.left = `${Math.round(left)}px`
    preview.style.top = `${Math.round(top)}px`
  }

  useEffect(() => {
    if (!zoom) return
    const onKey = (e) => { if (e.key === 'Escape') setZoom(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [zoom])

  useEffect(() => { load() /* eslint-disable-line */ }, [page, filter, sourceFilter, search, hideDone])

  // The server's `hide_done` filter and the client-side `validated` set don't
  // always agree (admins mark items via the UI faster than they hit the
  // backend's auto-validation criteria). When that gap leaves a page entirely
  // hidden, auto-advance instead of stranding the admin on an empty page.
  useEffect(() => {
    if (loading || !hideDone) return
    if (items.length === 0) return
    const visibleCount = items.filter((p) => !validated.has(p.id)).length
    if (visibleCount === 0 && page < totalPages) {
      setPage((p) => p + 1)
    }
  }, [items, validated, hideDone, loading, page, totalPages])

  // Fetch the source dropdown options once. We only show sources that actually
  // have rated supplements, so the admin doesn't pick a slug with zero results.
  useEffect(() => {
    imageValidationApi.listSources()
      .then((data) => setSourceOptions(data.sources || []))
      .catch(() => {})
  }, [])

  async function load() {
    setLoading(true); setError('')
    try {
      const params = { page, per_page: perPage, filter }
      if (search) params.q = search
      if (sourceFilter) params.source = sourceFilter
      if (hideDone) params.hide_done = '1'
      const data = await imageValidationApi.listProducts(params)
      const items = data.items || []
      setItems(items)
      setTotal(data.total || 0)
      setTotalPages(data.total_pages || 0)
      // Auto-mark anything that's already fully imported as validated.
      // "Fully imported" = has a linked Amazon URL AND at least 2 gallery
      // images. Both conditions combined mean the admin already completed
      // the Amazon-fetch + import flow for this product, even if it
      // happened before the auto-validation feature shipped.
      const autoValidIds = items
        .filter((p) => p.amazon_url && (p.image_count || 0) >= 2)
        .map((p) => p.id)
      mergeValidated(autoValidIds)
    } catch (e) { setError(e.userMessage || 'Failed to load') }
    finally { setLoading(false) }
  }

  function applySearch(e) {
    e?.preventDefault()
    if (page !== 1) setPage(1)
    setSearch(pendingSearch.trim())
  }

  async function selectProduct(p) {
    setSelected(p)
    setSelectedDetail(null)
    setAmazonUrl('')
    setScrapeData(null)
    setScrapeError('')
    setPicked(new Set())
    setImportMsg('')
    setAutoCandidates(null)
    setAutoSearchError('')
    setAutoFromCache(false)
    setAutoSearchedAt(null)

    // Fetch the full supplement record so we can render the gallery, the
    // already-linked Amazon listing, and its stored info — the list endpoint
    // only carries the first image and basic fields.
    setLoadingDetail(true)
    try {
      const full = await supplementsAdminApi.get(p.id)
      setSelectedDetail(full)
    } catch (e) {
      // Non-fatal — page still functions with the list-row data.
    } finally {
      setLoadingDetail(false)
    }

    // If candidates are cached for this product, fetch them immediately so
    // the admin sees them without clicking Auto-find.
    if (p.amazon_candidates_count != null) {
      try {
        const data = await imageValidationApi.autoSearch(p.id)
        setAutoCandidates(data.candidates || [])
        setAutoFromCache(!!data.from_cache)
        setAutoSearchedAt(data.searched_at || null)
      } catch (e) {
        setAutoSearchError('')
      }
    }
  }

  async function runAutoSearch(force = false) {
    if (!selected) return
    setAutoSearching(true); setAutoSearchError(''); setAutoCandidates(null)
    try {
      const data = await imageValidationApi.autoSearch(selected.id, { force })
      setAutoCandidates(data.candidates || [])
      setAutoFromCache(!!data.from_cache)
      setAutoSearchedAt(data.searched_at || null)
    } catch (e) {
      setAutoSearchError(e.userMessage || 'Auto-search failed')
    } finally {
      setAutoSearching(false)
    }
  }

  // -------- Bulk auto-find --------

  // Poll the bulk job status when one is running. Stops polling once finished.
  useEffect(() => {
    if (!bulkState?.running) return
    let cancelled = false
    const tick = async () => {
      try {
        const data = await imageValidationApi.bulkSearchStatus()
        if (cancelled) return
        setBulkState(data)
        // When the worker finishes, refresh the list so candidate counts show.
        if (!data.running) load()
      } catch (e) { /* ignore single-tick failures */ }
    }
    const id = setInterval(tick, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [bulkState?.running]) // eslint-disable-line

  async function startBulkSearch(force = false) {
    setBulkStarting(true); setBulkError('')
    try {
      const data = await imageValidationApi.bulkSearchStart({ force, filter, source: sourceFilter || undefined })
      if (!data.started) {
        setBulkError(data.message || 'Could not start.')
        if (data.state) setBulkState(data.state)
      } else {
        setBulkState(data.state || { running: true, total: data.total, done: 0 })
      }
    } catch (e) {
      setBulkError(e.userMessage || 'Failed to start bulk search')
    } finally {
      setBulkStarting(false)
    }
  }

  async function stopBulkSearch() {
    try { await imageValidationApi.bulkSearchStop() } catch (e) { /* ignore */ }
  }

  // -------- Bulk resolve Labdoor → Amazon --------
  useEffect(() => {
    if (!labdoorState?.running) return
    let cancelled = false
    const tick = async () => {
      try {
        const data = await imageValidationApi.bulkResolveLabdoorStatus()
        if (cancelled) return
        setLabdoorState(data)
        if (!data.running) load()
      } catch (e) { /* ignore */ }
    }
    const id = setInterval(tick, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [labdoorState?.running]) // eslint-disable-line

  async function startLabdoorResolve(force = false) {
    setLabdoorStarting(true); setLabdoorError('')
    try {
      const data = await imageValidationApi.bulkResolveLabdoorStart({ force })
      if (!data.started) {
        setLabdoorError(data.message || 'Could not start.')
        if (data.state) setLabdoorState(data.state)
      } else {
        setLabdoorState(data.state || { running: true, total: data.total, done: 0 })
      }
    } catch (e) {
      setLabdoorError(e.userMessage || 'Failed to start Labdoor resolve')
    } finally {
      setLabdoorStarting(false)
    }
  }

  async function stopLabdoorResolve() {
    try { await imageValidationApi.bulkResolveLabdoorStop() } catch (e) { /* ignore */ }
  }

  // -------- Bulk resolve Trustified → Amazon --------
  useEffect(() => {
    if (!trustifiedState?.running) return
    let cancelled = false
    const tick = async () => {
      try {
        const data = await imageValidationApi.bulkResolveTrustifiedStatus()
        if (cancelled) return
        setTrustifiedState(data)
        if (!data.running) load()
      } catch (e) { /* ignore */ }
    }
    const id = setInterval(tick, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [trustifiedState?.running]) // eslint-disable-line

  async function startTrustifiedResolve(force = false) {
    setTrustifiedStarting(true); setTrustifiedError('')
    try {
      const data = await imageValidationApi.bulkResolveTrustifiedStart({ force })
      if (!data.started) {
        setTrustifiedError(data.message || 'Could not start.')
        if (data.state) setTrustifiedState(data.state)
      } else {
        setTrustifiedState(data.state || { running: true, total: data.total, done: 0 })
      }
    } catch (e) {
      setTrustifiedError(e.userMessage || 'Failed to start Trustified resolve')
    } finally {
      setTrustifiedStarting(false)
    }
  }

  async function stopTrustifiedResolve() {
    try { await imageValidationApi.bulkResolveTrustifiedStop() } catch (e) { /* ignore */ }
  }

  // -------- Bulk auto-import (verified URLs → replace gallery) --------
  useEffect(() => {
    if (!autoImportState?.running) return
    let cancelled = false
    const tick = async () => {
      try {
        const data = await imageValidationApi.bulkAutoImportStatus()
        if (cancelled) return
        setAutoImportState(data)
        // Auto-mark every successfully imported product as validated. We do
        // this on every tick (not just on finish) so progress is visible as
        // the worker advances — the merge is idempotent so duplicates are
        // a no-op.
        mergeValidated(data.imported_ids)
        if (!data.running) load()
      } catch (e) { /* ignore */ }
    }
    const id = setInterval(tick, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [autoImportState?.running]) // eslint-disable-line

  async function startAutoImport(force = false) {
    setAutoImportStarting(true); setAutoImportError('')
    try {
      const data = await imageValidationApi.bulkAutoImportStart({ force })
      if (!data.started) {
        setAutoImportError(data.message || 'Could not start.')
        if (data.state) setAutoImportState(data.state)
      } else {
        setAutoImportState(data.state || { running: true, total: data.total, done: 0 })
      }
    } catch (e) {
      setAutoImportError(e.userMessage || 'Failed to start auto-import')
    } finally {
      setAutoImportStarting(false)
    }
  }

  async function stopAutoImport() {
    try { await imageValidationApi.bulkAutoImportStop() } catch (e) { /* ignore */ }
  }

  // On mount: pull current bulk status once so we show progress if a worker
  // started in another tab is still running. Also re-applies any imported_ids
  // the worker accumulated while this tab was closed — so admins returning to
  // the page see those products marked done.
  useEffect(() => {
    imageValidationApi.bulkSearchStatus().then(setBulkState).catch(() => {})
    imageValidationApi.bulkResolveLabdoorStatus().then(setLabdoorState).catch(() => {})
    imageValidationApi.bulkResolveTrustifiedStatus().then(setTrustifiedState).catch(() => {})
    imageValidationApi.bulkAutoImportStatus().then((data) => {
      setAutoImportState(data)
      mergeValidated(data?.imported_ids)
    }).catch(() => {})
  }, []) // eslint-disable-line

  function pickCandidate(c) {
    // Drop the candidate's URL into the manual-paste input and trigger the
    // same scrape flow — single source of truth for "fetch a product page".
    setAmazonUrl(c.url)
    // fetchAmazon reads from state; setState is async so call it via a tiny delay.
    setTimeout(() => {
      // Inline call instead of fetchAmazon() — that closure has stale amazonUrl.
      ;(async () => {
        setScraping(true); setScrapeError(''); setScrapeData(null); setPicked(new Set())
        try {
          const data = await imageValidationApi.scrapeAmazon(c.url)
          setScrapeData(data)
          setPicked(new Set((data.images || []).map((i) => i.url)))
        } catch (e) {
          setScrapeError(e.userMessage || 'Failed to fetch the Amazon page')
        } finally {
          setScraping(false)
        }
      })()
    }, 0)
  }

  function amazonSearchUrl(name, brand) {
    const q = [brand, name].filter(Boolean).join(' ')
    return `https://www.amazon.in/s?k=${encodeURIComponent(q)}`
  }

  async function fetchAmazon() {
    if (!amazonUrl.trim()) return
    setScraping(true); setScrapeError(''); setScrapeData(null); setPicked(new Set())
    try {
      const data = await imageValidationApi.scrapeAmazon(amazonUrl.trim())
      setScrapeData(data)
      // Pre-select all images by default — admin can deselect any that don't match.
      setPicked(new Set((data.images || []).map((i) => i.url)))
    } catch (e) {
      setScrapeError(e.userMessage || 'Failed to fetch the Amazon page')
    } finally {
      setScraping(false)
    }
  }

  function togglePick(url) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  async function importSelected() {
    if (!selected || !scrapeData || picked.size === 0) return
    setImporting(true); setImportMsg('')
    try {
      // 1. Build the supplement patch. We also clear the legacy single-image
      //    fields here — the gallery is being fully replaced with Amazon's
      //    images, so the old single image shouldn't linger.
      const amazonPatch = {
        amazon_url: scrapeData.url || null,
        amazon_asin: scrapeData.asin || null,
        amazon_data: {
          title: scrapeData.title || null,
          brand: scrapeData.brand || null,
          price: scrapeData.price || null,
          specs: scrapeData.specs || {},
          about: scrapeData.about || [],
          fetched_at: new Date().toISOString(),
        },
        image_url: null,
        image_path: null,
      }
      if (scrapeData.title) {
        amazonPatch.name = scrapeData.title
      }

      // Existing gallery image IDs — we'll delete these AFTER the new ones
      // succeed (Phase 2) so a partial-create failure doesn't leave the
      // product image-less.
      const existingImageIds = (selectedDetail?.images || [])
        .map((i) => i.id)
        .filter((id) => id != null)

      // 2. Phase 1: create new images + patch supplement in parallel.
      const urls = (scrapeData.images || []).filter((i) => picked.has(i.url)).map((i) => i.url)
      const imageOps = urls.map((u, idx) => imagesAdminApi.create({
        supplement_id: selected.id,
        image_url: u,
        image_type: idx === 0 ? 'main' : 'other',
        alt_text: scrapeData.title || selected.name,
        display_order: idx,
      }))
      const phase1 = await Promise.allSettled([
        supplementsAdminApi.update(selected.id, amazonPatch),
        ...imageOps,
      ])
      const [patchResult, ...imageResults] = phase1
      const failedImages = imageResults.filter((r) => r.status === 'rejected')
      const patchOk = patchResult.status === 'fulfilled'

      if (failedImages.length || !patchOk) {
        // Bail before the destructive delete — user keeps the old gallery.
        const parts = []
        if (!patchOk) parts.push(`Amazon info save failed: ${patchResult.reason?.userMessage || 'unknown'}`)
        if (failedImages.length) parts.push(`${failedImages.length} of ${imageResults.length} image(s) failed: ${failedImages[0].reason?.userMessage || ''}`)
        parts.push('Old gallery preserved.')
        setImportMsg(parts.join(' · '))
        return
      }

      // 3. Phase 2: delete the previous gallery rows now that the new ones
      //    are safely persisted.
      let deleteFailures = 0
      if (existingImageIds.length > 0) {
        const phase2 = await Promise.allSettled(
          existingImageIds.map((id) => imagesAdminApi.remove(id))
        )
        deleteFailures = phase2.filter((r) => r.status === 'rejected').length
      }

      const renamed = amazonPatch.name && amazonPatch.name !== selected.name
      const baseMsg = `Replaced gallery with ${imageResults.length} Amazon image${imageResults.length === 1 ? '' : 's'}${renamed ? ', renamed to Amazon title,' : ''} + saved Amazon info ✓`
      if (deleteFailures > 0) {
        setImportMsg(`${baseMsg} (note: ${deleteFailures} old image(s) couldn't be deleted — they'll still show until removed manually)`)
      } else {
        setImportMsg(baseMsg)
      }

      markValidated(selected.id)
      setSelected((prev) => prev && {
        ...prev,
        amazon_url: amazonPatch.amazon_url,
        amazon_asin: amazonPatch.amazon_asin,
        name: amazonPatch.name || prev.name,
      })
      // Refresh the full detail so the Linked panel + gallery reflect the
      // replaced state without requiring a manual re-click.
      try {
        const refreshed = await supplementsAdminApi.get(selected.id)
        setSelectedDetail(refreshed)
      } catch (e) { /* non-fatal */ }
      load()
    } catch (e) {
      setImportMsg(`Import failed: ${e.userMessage || 'unknown error'}`)
    } finally {
      setImporting(false)
    }
  }

  function markValidated(id) {
    const next = new Set(validated)
    next.add(id)
    setValidated(next)
    saveValidated(next)
  }

  // Save the edited product name. If `andValidate` is true, flip the validated
  // flag in the same click — common admin flow is "fix the name, mark done".
  async function saveProductName({ andValidate = false } = {}) {
    if (!selected) return
    const trimmed = nameDraft.trim()
    if (!trimmed) {
      setNameSaveMsg('Name cannot be empty')
      return
    }
    const currentName = selectedDetail?.name || selected.name
    const changed = trimmed !== currentName
    if (!changed && !andValidate) {
      setNameSaveMsg('No changes to save')
      return
    }
    setSavingName(true)
    setNameSaveMsg('')
    try {
      if (changed) {
        await supplementsAdminApi.update(selected.id, { name: trimmed })
        setSelected((prev) => prev ? { ...prev, name: trimmed } : prev)
        setSelectedDetail((prev) => prev ? { ...prev, name: trimmed } : prev)
        setItems((prev) => prev.map((it) => it.id === selected.id ? { ...it, name: trimmed } : it))
      }
      if (andValidate) markValidated(selected.id)
      setNameSaveMsg(
        changed && andValidate ? 'Saved & marked validated ✓'
        : changed ? 'Saved ✓'
        : 'Marked validated ✓',
      )
    } catch (e) {
      setNameSaveMsg(e?.response?.data?.error || e?.message || 'Save failed')
    } finally {
      setSavingName(false)
    }
  }
  function unmarkValidated(id) {
    const next = new Set(validated)
    next.delete(id)
    setValidated(next)
    saveValidated(next)
  }
  // Bulk-merge a list of supplement IDs (e.g. from the auto-import worker's
  // `imported_ids`) into the validated set in one localStorage write. No-op
  // when nothing new — avoids extra renders.
  function mergeValidated(ids) {
    if (!ids?.length) return
    setValidated((prev) => {
      const next = new Set(prev)
      let added = false
      for (const id of ids) {
        if (id != null && !next.has(id)) {
          next.add(id)
          added = true
        }
      }
      if (!added) return prev
      saveValidated(next)
      return next
    })
  }

  const filterLabel = useMemo(
    () => FILTERS.find((f) => f.value === filter)?.label || '',
    [filter],
  )

  return (
    <>
      <div className="admin-page-header">
        <div>
          <h2>Image validation <span className="admin-pill amber" style={{ verticalAlign: 'middle' }}>temporary tool</span></h2>
          <div className="desc">
            Find each product on Amazon, copy the listing URL, and import the gallery images to enrich your catalog.
            Validated marks are stored in this browser only.
          </div>
        </div>
      </div>

      {/* Bulk auto-find banner — surfaces job status above everything else. */}
      <div className="iv-bulk-bar">
        <div className="iv-bulk-bar-text">
          <strong>Bulk Auto-find on Amazon</strong>
          <div className="text-secondary" style={{ fontSize: '0.8rem' }}>
            Pre-fetches Amazon candidates for every product in the current filter so the queue opens instantly. Cached results persist in the database — re-runs benefit from it.
          </div>
        </div>
        <div className="iv-bulk-bar-actions">
          {bulkState?.running ? (
            <>
              <div className="iv-bulk-progress">
                <div
                  className="iv-bulk-progress-fill"
                  style={{ width: `${bulkState.total ? Math.round((bulkState.done / bulkState.total) * 100) : 0}%` }}
                />
              </div>
              <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                {bulkState.done} / {bulkState.total} · {bulkState.matched} matched · {bulkState.skipped_no_match} no-match
                {bulkState.current && <> · now: <em>{bulkState.current.name?.slice(0, 40)}…</em></>}
              </span>
              <button type="button" className="admin-btn danger sm" onClick={stopBulkSearch}>Stop</button>
            </>
          ) : (
            <>
              {bulkState?.finished_at && (
                <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                  Last run: {bulkState.done}/{bulkState.total} · {bulkState.matched} matched · {bulkState.skipped_no_match} no-match
                  {bulkState.errors?.length > 0 && <> · {bulkState.errors.length} error(s)</>}
                </span>
              )}
              <button type="button" className="admin-btn" disabled={bulkStarting} onClick={() => startBulkSearch(false)}>
                {bulkStarting ? 'Starting…' : 'Run Auto-find on uncached products'}
              </button>
              <button type="button" className="admin-btn secondary sm" disabled={bulkStarting} onClick={() => startBulkSearch(true)}>
                Force re-run
              </button>
            </>
          )}
        </div>
        {bulkError && <div className="admin-error-banner" style={{ marginTop: 8 }}>{bulkError}</div>}
      </div>

      {/* Resolve verified Amazon URLs from the source's own product page —
          one bar per source so admins can run them independently. */}
      <div className="iv-bulk-bar">
        <div className="iv-bulk-bar-text">
          <strong>Resolve Labdoor → Amazon (USA)</strong>
          <div className="text-secondary" style={{ fontSize: '0.8rem' }}>
            Walks each Labdoor review's "Buy on Amazon" redirect and caches the final amazon.com URL.
          </div>
        </div>
        <div className="iv-bulk-bar-actions">
          {labdoorState?.running ? (
            <>
              <div className="iv-bulk-progress">
                <div
                  className="iv-bulk-progress-fill"
                  style={{ width: `${labdoorState.total ? Math.round((labdoorState.done / labdoorState.total) * 100) : 0}%` }}
                />
              </div>
              <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                {labdoorState.done} / {labdoorState.total} · {labdoorState.matched} matched · {labdoorState.skipped_no_match} no-match
                {labdoorState.current && <> · now: <em>{labdoorState.current.name?.slice(0, 40)}…</em></>}
              </span>
              <button type="button" className="admin-btn danger sm" onClick={stopLabdoorResolve}>Stop</button>
            </>
          ) : (
            <>
              {labdoorState?.finished_at && (
                <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                  Last run: {labdoorState.done}/{labdoorState.total} · {labdoorState.matched} matched · {labdoorState.skipped_no_match} no-match
                  {labdoorState.errors?.length > 0 && <> · {labdoorState.errors.length} error(s)</>}
                </span>
              )}
              <button type="button" className="admin-btn" disabled={labdoorStarting} onClick={() => startLabdoorResolve(false)}>
                {labdoorStarting ? 'Starting…' : 'Resolve Labdoor → Amazon'}
              </button>
              <button type="button" className="admin-btn secondary sm" disabled={labdoorStarting} onClick={() => startLabdoorResolve(true)}>
                Force re-resolve
              </button>
            </>
          )}
        </div>
        {labdoorError && <div className="admin-error-banner" style={{ marginTop: 8 }}>{labdoorError}</div>}
      </div>

      <div className="iv-bulk-bar">
        <div className="iv-bulk-bar-text">
          <strong>Resolve Trustified → Amazon (India)</strong>
          <div className="text-secondary" style={{ fontSize: '0.8rem' }}>
            Walks Trustified's pass page → shop page → "Amazon" button (amzn.to short link) and caches the final amazon.in URL.
          </div>
        </div>
        <div className="iv-bulk-bar-actions">
          {trustifiedState?.running ? (
            <>
              <div className="iv-bulk-progress">
                <div
                  className="iv-bulk-progress-fill"
                  style={{ width: `${trustifiedState.total ? Math.round((trustifiedState.done / trustifiedState.total) * 100) : 0}%` }}
                />
              </div>
              <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                {trustifiedState.done} / {trustifiedState.total} · {trustifiedState.matched} matched · {trustifiedState.skipped_no_match} no-match
                {trustifiedState.current && <> · now: <em>{trustifiedState.current.name?.slice(0, 40)}…</em></>}
              </span>
              <button type="button" className="admin-btn danger sm" onClick={stopTrustifiedResolve}>Stop</button>
            </>
          ) : (
            <>
              {trustifiedState?.finished_at && (
                <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                  Last run: {trustifiedState.done}/{trustifiedState.total} · {trustifiedState.matched} matched · {trustifiedState.skipped_no_match} no-match
                  {trustifiedState.errors?.length > 0 && <> · {trustifiedState.errors.length} error(s)</>}
                </span>
              )}
              <button type="button" className="admin-btn" disabled={trustifiedStarting} onClick={() => startTrustifiedResolve(false)}>
                {trustifiedStarting ? 'Starting…' : 'Resolve Trustified → Amazon'}
              </button>
              <button type="button" className="admin-btn secondary sm" disabled={trustifiedStarting} onClick={() => startTrustifiedResolve(true)}>
                Force re-resolve
              </button>
            </>
          )}
        </div>
        {trustifiedError && <div className="admin-error-banner" style={{ marginTop: 8 }}>{trustifiedError}</div>}
      </div>

      <div className="iv-bulk-bar">
        <div className="iv-bulk-bar-text">
          <strong>Bulk auto-import from verified Amazon URLs</strong>
          <div className="text-secondary" style={{ fontSize: '0.8rem' }}>
            For every product that has a Trustified, Unbox Health, or Labdoor verified Amazon link, scrape the listing and replace the gallery + save Amazon info — same as the manual import flow, no admin clicks needed.
            Priority order: Trustified → Unbox → Labdoor. Skips products that already have ≥2 images and a linked Amazon URL.
          </div>
        </div>
        <div className="iv-bulk-bar-actions">
          {autoImportState?.running ? (
            <>
              <div className="iv-bulk-progress">
                <div
                  className="iv-bulk-progress-fill"
                  style={{ width: `${autoImportState.total ? Math.round((autoImportState.done / autoImportState.total) * 100) : 0}%` }}
                />
              </div>
              <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                {autoImportState.done} / {autoImportState.total} · {autoImportState.imported} imported · {autoImportState.skipped_already_done} already-done · {autoImportState.skipped_no_url} no-url
                {autoImportState.errors?.length > 0 && <> · {autoImportState.errors.length} error(s)</>}
                {autoImportState.current && <> · now: <em>{autoImportState.current.name?.slice(0, 40)}…</em></>}
              </span>
              <button type="button" className="admin-btn danger sm" onClick={stopAutoImport}>Stop</button>
            </>
          ) : (
            <>
              {autoImportState?.finished_at && (
                <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
                  Last run: {autoImportState.done}/{autoImportState.total} · {autoImportState.imported} imported · {autoImportState.skipped_already_done} already-done · {autoImportState.skipped_no_url} no-url
                  {autoImportState.errors?.length > 0 && <> · {autoImportState.errors.length} error(s)</>}
                </span>
              )}
              <button
                type="button"
                className="admin-btn"
                disabled={autoImportStarting || !can.write}
                onClick={() => {
                  if (window.confirm('This will scrape Amazon and REPLACE the gallery for every product with a verified URL that doesn\'t already have ≥2 images + an Amazon link. Old images will be deleted. Continue?')) {
                    startAutoImport(false)
                  }
                }}
              >
                {autoImportStarting ? 'Starting…' : 'Auto-import unimported products'}
              </button>
              <button
                type="button"
                className="admin-btn secondary sm"
                disabled={autoImportStarting || !can.write}
                onClick={() => {
                  if (window.confirm('Force re-import EVERY product with a verified URL — even ones that already look complete. Existing galleries will be replaced. Continue?')) {
                    startAutoImport(true)
                  }
                }}
              >
                Force re-import all
              </button>
            </>
          )}
        </div>
        {autoImportError && <div className="admin-error-banner" style={{ marginTop: 8 }}>{autoImportError}</div>}
      </div>

      <div className="admin-filters">
        <select className="admin-select" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1) }}>
          {FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
        <select
          className="admin-select"
          value={sourceFilter}
          onChange={(e) => { setSourceFilter(e.target.value); setPage(1) }}
          title="Filter products by the testing source they're rated by"
        >
          <option value="">All sources</option>
          {sourceOptions.map((s) => (
            <option key={s.slug} value={s.slug}>
              {s.name} ({s.count.toLocaleString()})
            </option>
          ))}
        </select>
        <form onSubmit={applySearch} style={{ display: 'flex', gap: 6, flex: 1, minWidth: 220 }}>
          <input
            className="admin-input grow"
            placeholder="Search by product or brand…"
            value={pendingSearch}
            onChange={(e) => setPendingSearch(e.target.value)}
          />
          <button type="submit" className="admin-btn secondary">Apply</button>
          {search && (
            <button type="button" className="admin-btn ghost" onClick={() => { setPendingSearch(''); setSearch('') }}>
              Clear
            </button>
          )}
        </form>
        <label
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '0.85rem', cursor: 'pointer', whiteSpace: 'nowrap' }}
          title="Hide products you've already marked validated (per-browser)"
        >
          <input
            type="checkbox"
            checked={hideDone}
            onChange={(e) => {
              const v = e.target.checked
              setHideDone(v)
              localStorage.setItem(HIDE_DONE_KEY, v ? '1' : '0')
            }}
          />
          Hide done
        </label>
        <span className="text-secondary" style={{ fontSize: '0.8rem' }}>
          {total.toLocaleString()} products · {filterLabel}
        </span>
      </div>

      {error && <div className="admin-error-banner">{error}</div>}

      <div className="iv-shell">
        {/* Left: queue */}
        <div className="iv-list">
          {(() => {
            const visibleItems = hideDone ? items.filter((p) => !validated.has(p.id)) : items
            const hiddenCount = items.length - visibleItems.length
            if (loading) return <div className="admin-loading">Loading…</div>
            if (items.length === 0) return <div className="admin-empty">No products match.</div>
            if (visibleItems.length === 0) {
              return (
                <div className="admin-empty">
                  All {hiddenCount} product{hiddenCount === 1 ? '' : 's'} on this page are marked done. Uncheck "Hide done" or move to another page.
                </div>
              )
            }
            return <>
              {hiddenCount > 0 && (
                <div className="text-secondary" style={{ fontSize: '0.78rem', padding: '4px 8px' }}>
                  {hiddenCount} done item{hiddenCount === 1 ? '' : 's'} hidden on this page
                </div>
              )}
              {visibleItems.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`iv-list-item ${selected?.id === p.id ? 'active' : ''} ${validated.has(p.id) ? 'done' : ''}`}
              onClick={() => selectProduct(p)}
            >
              <div className="iv-list-thumb">
                {p.first_image_url
                  ? <img src={p.first_image_url} alt="" onError={(e) => { e.target.style.display = 'none' }} />
                  : <span className="text-secondary" style={{ fontSize: '0.7rem' }}>none</span>}
              </div>
              <div className="iv-list-meta">
                <strong>{p.name}</strong>
                <div className="text-secondary" style={{ fontSize: '0.75rem' }}>
                  {p.brand || '—'} · {p.category || '—'}
                </div>
                <div className="iv-list-pills">
                  <span className={`admin-pill ${p.image_count === 0 ? 'red' : p.image_count === 1 ? 'amber' : 'green'}`}>
                    {p.image_count} image{p.image_count === 1 ? '' : 's'}
                  </span>
                  {p.legacy_only && <span className="admin-pill amber">legacy</span>}
                  {p.amazon_url && <span className="admin-pill purple">amazon</span>}
                  {p.unbox_amazon_url && <span className="admin-pill green" title="Unbox Health affiliate URL available">✓ unbox</span>}
                  {p.labdoor_amazon_url && <span className="admin-pill green" title="Labdoor → Amazon URL cached">✓ labdoor</span>}
                  {p.trustified_amazon_url && <span className="admin-pill green" title="Trustified → Amazon URL cached">✓ trustified</span>}
                  {(p.source_slugs || []).map((slug) => (
                    <span key={slug} className="admin-pill blue" title={`Rated by ${slug}`}>{slug}</span>
                  ))}
                  {p.amazon_candidates_count != null && (
                    <span className={`admin-pill ${p.amazon_candidates_count > 0 ? 'green' : 'red'}`} title="Candidates cached — opens instantly">
                      ✨ {p.amazon_candidates_count}
                    </span>
                  )}
                  {p.amazon_candidates_max_score != null && (
                    <span
                      className={`admin-pill ${p.amazon_candidates_max_score >= 0.7 ? 'green' : p.amazon_candidates_max_score >= 0.4 ? 'amber' : 'red'}`}
                      title="Best candidate match score"
                    >
                      {Math.round(p.amazon_candidates_max_score * 100)}% best
                    </span>
                  )}
                  {validated.has(p.id) && <span className="admin-pill blue">done</span>}
                </div>
              </div>
            </button>
              ))}
            </>
          })()}
          <Pagination page={page} totalPages={totalPages} total={total} onChange={setPage} />
        </div>

        {/* Right: detail panel */}
        <div className="iv-detail">
          {!selected ? (
            <div className="admin-empty">
              <div className="ico">←</div>
              <h3>Pick a product</h3>
              <div>Select a product on the left to start finding its Amazon listing.</div>
            </div>
          ) : (
            <>
              <div className="iv-detail-head">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="text-secondary" style={{ fontSize: '0.75rem' }}>
                    {selected.brand} · {selected.category}
                  </div>
                  <div style={{ margin: '2px 0 6px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <textarea
                      className="admin-input"
                      value={nameDraft}
                      onChange={(e) => { setNameDraft(e.target.value); setNameSaveMsg('') }}
                      rows={2}
                      style={{ fontSize: '1rem', lineHeight: 1.35, fontWeight: 600, resize: 'vertical', minHeight: 48, wordBreak: 'break-word' }}
                      placeholder="Product name"
                      disabled={savingName}
                    />
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        className="admin-btn primary sm"
                        onClick={() => saveProductName({ andValidate: true })}
                        disabled={savingName || !nameDraft.trim()}
                        title="Save name and mark this product as validated"
                      >
                        {savingName ? 'Saving…' : 'Save & mark validated'}
                      </button>
                      <button
                        type="button"
                        className="admin-btn ghost sm"
                        onClick={() => saveProductName({ andValidate: false })}
                        disabled={savingName || !nameDraft.trim() || nameDraft.trim() === (selectedDetail?.name || selected.name)}
                        title="Save the renamed product without changing validation status"
                      >
                        Save name only
                      </button>
                      {nameSaveMsg && (
                        <span className="text-secondary" style={{ fontSize: '0.75rem' }}>{nameSaveMsg}</span>
                      )}
                    </div>
                  </div>
                  <div style={{ fontSize: '0.8rem' }}>
                    {(() => {
                      const count = selectedDetail?.images?.length ?? selected.image_count
                      return `Currently ${count} image${count === 1 ? '' : 's'}${selected.legacy_only && !selectedDetail ? ' (legacy single)' : ''}`
                    })()}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0, whiteSpace: 'nowrap' }}>
                  <a
                    className="admin-btn secondary sm"
                    href={`/supplement/${selected.slug}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ textDecoration: 'none' }}
                    title="Open the public product page in a new tab"
                  >
                    View on site ↗
                  </a>
                  {validated.has(selected.id) ? (
                    <button type="button" className="admin-btn ghost sm" onClick={() => unmarkValidated(selected.id)}>
                      Unmark validated
                    </button>
                  ) : (
                    <button type="button" className="admin-btn secondary sm" onClick={() => markValidated(selected.id)}>
                      Mark validated
                    </button>
                  )}
                </div>
              </div>

              <div className="iv-section">
                <h4>
                  Current images
                  {selectedDetail?.images?.length > 0 && (
                    <span className="text-secondary" style={{ fontSize: '0.78rem', fontWeight: 'normal', marginLeft: 8 }}>
                      ({selectedDetail.images.length})
                    </span>
                  )}
                </h4>
                <div className="iv-current-strip">
                  {loadingDetail && !selectedDetail ? (
                    <div className="text-secondary">Loading…</div>
                  ) : selectedDetail?.images?.length > 0 ? (
                    selectedDetail.images.map((img, i) => (
                      <button
                        key={img.id || `legacy-${i}`}
                        type="button"
                        className={`iv-thumb iv-thumb-zoomable ${i === 0 ? 'iv-thumb-current' : ''}`}
                        onClick={() => setZoom({ url: img.url, alt: img.alt || selected.name })}
                        title={img.type ? `${img.type} — click to zoom` : 'Click to zoom'}
                      >
                        <img src={img.url} alt={img.alt || ''} />
                        <span className="iv-zoom-hint">🔍 Zoom</span>
                      </button>
                    ))
                  ) : selected.first_image_url ? (
                    <button
                      type="button"
                      className="iv-thumb iv-thumb-current iv-thumb-zoomable"
                      onClick={() => setZoom({ url: selected.first_image_url, alt: selected.name })}
                      title="Click to zoom"
                    >
                      <img src={selected.first_image_url} alt={selected.name} />
                      <span className="iv-zoom-hint">🔍 Zoom</span>
                    </button>
                  ) : (
                    <div className="text-secondary">No images on file.</div>
                  )}
                </div>
              </div>

              {selectedDetail?.amazon_url && (
                <div className="iv-section">
                  <h4>
                    Linked Amazon listing
                    <span className="admin-pill purple" style={{ marginLeft: 8 }}>stored</span>
                  </h4>
                  <div className="iv-linked-card">
                    <strong>{selectedDetail.amazon_data?.title || selectedDetail.name}</strong>
                    <div className="iv-linked-meta">
                      <span><strong>ASIN:</strong> {selectedDetail.amazon_asin || '—'}</span>
                      {selectedDetail.amazon_data?.brand && <span><strong>Brand:</strong> {selectedDetail.amazon_data.brand}</span>}
                      {selectedDetail.amazon_data?.price && <span><strong>Price:</strong> {selectedDetail.amazon_data.price}</span>}
                      {selectedDetail.amazon_data?.fetched_at && (
                        <span className="text-secondary">
                          fetched {new Date(selectedDetail.amazon_data.fetched_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                    <div className="iv-linked-actions">
                      <a
                        className="admin-btn secondary sm"
                        href={selectedDetail.amazon_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ textDecoration: 'none' }}
                      >
                        Open listing on Amazon →
                      </a>
                      <button
                        type="button"
                        className="admin-btn secondary sm"
                        onClick={() => {
                          setAmazonUrl(selectedDetail.amazon_url)
                          // Trigger a fresh scrape so the user can re-import images / refresh price/specs.
                          ;(async () => {
                            setScraping(true); setScrapeError(''); setScrapeData(null); setPicked(new Set())
                            try {
                              const data = await imageValidationApi.scrapeAmazon(selectedDetail.amazon_url)
                              setScrapeData(data)
                              setPicked(new Set((data.images || []).map((i) => i.url)))
                            } catch (e) {
                              setScrapeError(e.userMessage || 'Failed to fetch the Amazon page')
                            } finally {
                              setScraping(false)
                            }
                          })()
                        }}
                        disabled={scraping}
                      >
                        {scraping ? 'Re-fetching…' : '↻ Re-fetch from Amazon (refresh price/specs/images)'}
                      </button>
                    </div>

                    {selectedDetail.amazon_data?.specs && Object.keys(selectedDetail.amazon_data.specs).length > 0 && (
                      <details className="iv-linked-details">
                        <summary>Stored product info ({Object.keys(selectedDetail.amazon_data.specs).length} fields)</summary>
                        <table className="iv-spec-table">
                          <tbody>
                            {Object.entries(selectedDetail.amazon_data.specs).map(([k, v]) => (
                              <tr key={k}><th>{k}</th><td>{v}</td></tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    )}

                    {selectedDetail.amazon_data?.about?.length > 0 && (
                      <details className="iv-linked-details">
                        <summary>About this item ({selectedDetail.amazon_data.about.length} bullets)</summary>
                        <ul className="iv-about-list">
                          {selectedDetail.amazon_data.about.map((b, i) => <li key={i}>{b}</li>)}
                        </ul>
                      </details>
                    )}
                  </div>
                </div>
              )}

              <div className="iv-section">
                <h4>{selectedDetail?.amazon_url ? 'Change linked Amazon listing' : '1. Find the matching Amazon listing'}</h4>
                <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
                  {selectedDetail?.amazon_url
                    ? 'Already linked above. Use this section if you want to swap the linked product or import additional images.'
                    : 'Auto-search both amazon.in and amazon.com, or open Amazon search manually and paste the URL below.'}
                </p>

                {/* Verified Amazon URL from Unbox Health — shows up immediately
                    when the supplement was imported with an unbox-health buy_url.
                    Always rendered first because a human curated the link. */}
                {selected.unbox_amazon_url && (
                  <div className="iv-unbox-verified">
                    <div className="iv-unbox-verified-head">
                      <span className="admin-pill green">✓ Verified by Unbox Health</span>
                      <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
                        Affiliate link from the unboxhealth.in product page
                      </span>
                    </div>
                    <div className="iv-unbox-verified-body">
                      <div className="iv-thumb">
                        {selected.first_image_url
                          ? <img src={selected.first_image_url} alt="" onError={(e) => { e.target.style.opacity = 0.3 }} />
                          : <span className="text-secondary" style={{ fontSize: '0.7rem' }}>no image</span>}
                      </div>
                      <div className="iv-unbox-verified-meta">
                        <div className="iv-candidate-title">{selected.name}</div>
                        <div className="iv-candidate-pills">
                          <span className="admin-pill blue">amazon.in</span>
                          <span className="admin-pill green">100% verified</span>
                        </div>
                      </div>
                      <div className="iv-unbox-verified-actions">
                        <button
                          type="button"
                          className="admin-btn"
                          onClick={() => pickCandidate({ url: selected.unbox_amazon_url })}
                          disabled={scraping}
                        >
                          {scraping ? 'Fetching…' : 'Use this listing'}
                        </button>
                        <a
                          className="admin-btn ghost sm"
                          href={selected.unbox_amazon_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ textDecoration: 'none' }}
                        >
                          Open on Amazon ↗
                        </a>
                      </div>
                    </div>
                  </div>
                )}

                {selected.labdoor_amazon_url && (
                  <div className="iv-unbox-verified">
                    <div className="iv-unbox-verified-head">
                      <span className="admin-pill green">✓ Verified by Labdoor (USA)</span>
                      <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
                        Affiliate link from the labdoor.com review page
                      </span>
                    </div>
                    <div className="iv-unbox-verified-body">
                      <div className="iv-thumb">
                        {selected.first_image_url
                          ? <img src={selected.first_image_url} alt="" onError={(e) => { e.target.style.opacity = 0.3 }} />
                          : <span className="text-secondary" style={{ fontSize: '0.7rem' }}>no image</span>}
                      </div>
                      <div className="iv-unbox-verified-meta">
                        <div className="iv-candidate-title">{selected.name}</div>
                        <div className="iv-candidate-pills">
                          <span className="admin-pill amber">amazon.com</span>
                          <span className="admin-pill green">100% verified</span>
                        </div>
                      </div>
                      <div className="iv-unbox-verified-actions">
                        <button
                          type="button"
                          className="admin-btn"
                          onClick={() => pickCandidate({ url: selected.labdoor_amazon_url })}
                          disabled={scraping}
                        >
                          {scraping ? 'Fetching…' : 'Use this listing (Amazon-USA)'}
                        </button>
                        <a
                          className="admin-btn ghost sm"
                          href={selected.labdoor_amazon_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ textDecoration: 'none' }}
                        >
                          Open on Amazon ↗
                        </a>
                      </div>
                    </div>
                  </div>
                )}

                {selected.trustified_amazon_url && (
                  <div className="iv-unbox-verified">
                    <div className="iv-unbox-verified-head">
                      <span className="admin-pill green">✓ Verified by Trustified</span>
                      <span className="text-secondary" style={{ fontSize: '0.75rem' }}>
                        Affiliate link from the shop.trustified.co.in product page
                      </span>
                    </div>
                    <div className="iv-unbox-verified-body">
                      <div className="iv-thumb">
                        {selected.first_image_url
                          ? <img src={selected.first_image_url} alt="" onError={(e) => { e.target.style.opacity = 0.3 }} />
                          : <span className="text-secondary" style={{ fontSize: '0.7rem' }}>no image</span>}
                      </div>
                      <div className="iv-unbox-verified-meta">
                        <div className="iv-candidate-title">{selected.name}</div>
                        <div className="iv-candidate-pills">
                          <span className="admin-pill blue">amazon.in</span>
                          <span className="admin-pill green">100% verified</span>
                        </div>
                      </div>
                      <div className="iv-unbox-verified-actions">
                        <button
                          type="button"
                          className="admin-btn"
                          onClick={() => pickCandidate({ url: selected.trustified_amazon_url })}
                          disabled={scraping}
                        >
                          {scraping ? 'Fetching…' : 'Use this listing (Amazon-IN)'}
                        </button>
                        <a
                          className="admin-btn ghost sm"
                          href={selected.trustified_amazon_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ textDecoration: 'none' }}
                        >
                          Open on Amazon ↗
                        </a>
                      </div>
                    </div>
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  {autoCandidates === null ? (
                    <button
                      type="button"
                      className="admin-btn"
                      onClick={() => runAutoSearch(false)}
                      disabled={autoSearching}
                    >
                      {autoSearching ? 'Searching .in & .com…' : '✨ Auto-find on Amazon'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="admin-btn secondary sm"
                      onClick={() => runAutoSearch(true)}
                      disabled={autoSearching}
                      title="Re-run live (ignores cache)"
                    >
                      {autoSearching ? 'Refreshing…' : '↻ Refresh from Amazon'}
                    </button>
                  )}
                  {autoFromCache && autoSearchedAt && (
                    <span className="text-secondary" style={{ fontSize: '0.78rem' }}>
                      Cached {new Date(autoSearchedAt).toLocaleString()}
                    </span>
                  )}
                  <a
                    className="admin-btn ghost sm"
                    href={amazonSearchUrl(selected.name, selected.brand)}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ display: 'inline-flex', alignItems: 'center', textDecoration: 'none' }}
                  >
                    Open amazon.in manually →
                  </a>
                </div>

                {autoSearchError && <div className="admin-error-banner" style={{ marginTop: 10 }}>{autoSearchError}</div>}

                {autoCandidates !== null && (() => {
                  // The unbox-health verified URL is rendered as its own banner
                  // above this grid; drop it from auto-search results so the
                  // admin doesn't see the same listing twice.
                  const gridCandidates = autoCandidates.filter((c) => !['unbox-health', 'labdoor', 'trustified'].includes(c.source))
                  return (
                  <div style={{ marginTop: 12 }}>
                    {gridCandidates.length === 0 ? (
                      <div className="rating-empty">
                        {selected.unbox_amazon_url
                          ? 'No additional auto-search candidates. Use the verified Amazon URL above.'
                          : 'No confident match on amazon.in or amazon.com. Skip this product — handle it manually later.'}
                      </div>
                    ) : (
                      <>
                        <div className="text-secondary" style={{ fontSize: '0.78rem', marginBottom: 6 }}>
                          {gridCandidates.length} candidate{gridCandidates.length === 1 ? '' : 's'} — click the one whose image matches the product above.
                        </div>
                        <div className="iv-candidate-grid" ref={candidateGridRef}>
                          {gridCandidates.map((c) => (
                            <button
                              key={`${c.domain}-${c.asin}`}
                              type="button"
                              className="iv-candidate"
                              onClick={() => pickCandidate(c)}
                              onMouseEnter={positionHoverPreview}
                              onFocus={positionHoverPreview}
                            >
                              <div className="iv-thumb">
                                {c.image
                                  ? <img src={c.image} alt="" onError={(e) => { e.target.style.opacity = 0.3 }} />
                                  : <span className="text-secondary" style={{ fontSize: '0.7rem' }}>no image</span>}
                              </div>
                              <div className="iv-candidate-meta">
                                <div className="iv-candidate-title">{c.title}</div>
                                <div className="iv-candidate-pills">
                                  <span className={`admin-pill ${c.domain.endsWith('.in') ? 'blue' : 'amber'}`}>{c.domain}</span>
                                  <span className={`admin-pill ${c.score >= 0.7 ? 'green' : c.score >= 0.4 ? 'amber' : 'red'}`}>
                                    {Math.round(c.score * 100)}% match
                                  </span>
                                </div>
                              </div>

                              {/* Hover preview — fixed-positioned, JS-clamped to viewport. */}
                              <div className="iv-candidate-hover" aria-hidden="true">
                                {c.image && (
                                  <div className="iv-candidate-hover-img">
                                    <img src={c.image} alt="" />
                                  </div>
                                )}
                                <div className="iv-candidate-hover-body">
                                  <div className="iv-candidate-hover-title">{c.title}</div>
                                  <div className="iv-candidate-pills" style={{ marginTop: 6 }}>
                                    <span className={`admin-pill ${c.domain.endsWith('.in') ? 'blue' : 'amber'}`}>{c.domain}</span>
                                    <span className={`admin-pill ${c.score >= 0.7 ? 'green' : c.score >= 0.4 ? 'amber' : 'red'}`}>
                                      {Math.round(c.score * 100)}% match
                                    </span>
                                  </div>
                                  <div className="text-secondary" style={{ fontSize: '0.7rem', marginTop: 8 }}>
                                    Click to fetch full listing
                                  </div>
                                </div>
                              </div>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                  )
                })()}
              </div>

              <div className="iv-section">
                <h4>2. Or paste the Amazon URL manually</h4>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    className="admin-input grow"
                    placeholder="https://www.amazon.in/dp/…"
                    value={amazonUrl}
                    onChange={(e) => setAmazonUrl(e.target.value)}
                    disabled={scraping}
                  />
                  <button
                    type="button"
                    className="admin-btn"
                    onClick={fetchAmazon}
                    disabled={scraping || !amazonUrl.trim()}
                  >
                    {scraping ? 'Fetching…' : 'Fetch'}
                  </button>
                </div>
                {scrapeError && <div className="admin-error-banner" style={{ marginTop: 8 }}>{scrapeError}</div>}
              </div>

              {scrapeData && (
                <div className="iv-section">
                  <h4>3. Review & import</h4>
                  <div className="iv-amazon-meta">
                    <strong>{scrapeData.title || '—'}</strong>
                    <div className="text-secondary" style={{ fontSize: '0.78rem' }}>
                      ASIN: {scrapeData.asin || '—'}
                      {scrapeData.price && <> · {scrapeData.price}</>}
                      {' · '}
                      <a href={scrapeData.url} target="_blank" rel="noopener noreferrer">view listing</a>
                    </div>
                  </div>

                  <div className="iv-compare">
                    <div className="iv-compare-side">
                      <div className="iv-compare-label">Your product</div>
                      {selected.first_image_url ? (
                        <button
                          type="button"
                          className="iv-thumb large iv-thumb-zoomable"
                          onClick={() => setZoom({ url: selected.first_image_url, alt: selected.name })}
                          title="Click to zoom"
                        >
                          <img src={selected.first_image_url} alt={selected.name} />
                          <span className="iv-zoom-hint">🔍 Zoom</span>
                        </button>
                      ) : (
                        <div className="iv-thumb large"><span className="text-secondary">no image</span></div>
                      )}
                    </div>
                    <div className="iv-compare-side">
                      <div className="iv-compare-label">Amazon main image</div>
                      {scrapeData.images[0] ? (
                        <button
                          type="button"
                          className="iv-thumb large iv-thumb-zoomable"
                          onClick={() => setZoom({ url: scrapeData.images[0].url, alt: scrapeData.title || 'Amazon main image' })}
                          title="Click to zoom"
                        >
                          <img src={scrapeData.images[0].url} alt="" onError={(e) => { e.target.style.opacity = 0.3 }} />
                          <span className="iv-zoom-hint">🔍 Zoom</span>
                        </button>
                      ) : (
                        <div className="iv-thumb large"><span className="text-secondary">none</span></div>
                      )}
                    </div>
                  </div>

                  <div className="iv-amazon-grid">
                    {(scrapeData.images || []).map((img) => {
                      const checked = picked.has(img.url)
                      return (
                        <label key={img.url} className={`iv-amazon-card ${checked ? 'picked' : ''}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => togglePick(img.url)}
                          />
                          <div className="iv-thumb">
                            <img src={img.url} alt="" onError={(e) => { e.target.style.opacity = 0.3 }} />
                          </div>
                        </label>
                      )
                    })}
                  </div>

                  <div className="iv-import-row">
                    <button
                      type="button"
                      className="admin-btn"
                      onClick={importSelected}
                      disabled={!can.write || importing || picked.size === 0}
                    >
                      {importing ? 'Replacing…' : `Replace gallery with ${picked.size} image${picked.size === 1 ? '' : 's'} + save Amazon info`}
                    </button>
                    {picked.size === 0 && <span className="text-secondary" style={{ fontSize: '0.8rem' }}>Pick at least one image to import.</span>}
                    {importMsg && <span className="text-secondary" style={{ fontSize: '0.85rem' }}>{importMsg}</span>}
                  </div>
                  <div className="text-secondary" style={{ fontSize: '0.75rem', marginTop: 8, marginBottom: 4 }}>
                    Renames the supplement to the Amazon title (slug stays the same), saves the listing URL, ASIN, and the product info below.
                    <strong> Old gallery images and the legacy single image are deleted</strong> — only the selected Amazon images are kept.
                    The old gallery is preserved if any new image fails to save.
                  </div>

                  {(scrapeData.specs && Object.keys(scrapeData.specs).length > 0) && (
                    <div className="iv-spec-block">
                      <h5>Product information (will be saved with this listing)</h5>
                      <table className="iv-spec-table">
                        <tbody>
                          {Object.entries(scrapeData.specs).map(([k, v]) => (
                            <tr key={k}>
                              <th>{k}</th>
                              <td>{v}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {(scrapeData.about && scrapeData.about.length > 0) && (
                    <div className="iv-spec-block">
                      <h5>About this item</h5>
                      <ul className="iv-about-list">
                        {scrapeData.about.map((b, i) => <li key={i}>{b}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Click-to-zoom lightbox: shared across Current images and the compare panel.
          Backdrop click or ESC dismisses (the keydown handler is registered above). */}
      {zoom && (
        <div className="iv-zoom-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setZoom(null) }}>
          <button type="button" className="iv-zoom-close" onClick={() => setZoom(null)} aria-label="Close zoom">×</button>
          <img src={zoom.url} alt={zoom.alt || ''} />
        </div>
      )}
    </>
  )
}
