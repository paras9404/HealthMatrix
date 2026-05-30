import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { supplementsApi, categoriesApi, sourcesApi } from '../services/api.js'
import { trackEvent } from '../hooks/useTracker.js'
import SupplementCard from '../components/SupplementCard.jsx'
import ScoreRing from '../components/ScoreRing.jsx'
import { CardSkeleton, EmptyState, ErrorState } from '../components/Loader.jsx'
import Seo from '../components/Seo.jsx'
import { useCompare } from '../hooks/useCompare.jsx'
import { getCategoryEmoji, getScoreColor, getScoreGrade, cleanProductName } from '../utils/format.js'
import { buildBreadcrumbJsonLd, buildItemListJsonLd, buildCollectionPageJsonLd } from '../utils/seo.js'
import './Browse.css'

export default function Browse() {
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState({ items: [], total: 0, total_pages: 1 })
  const [categories, setCategories] = useState([])
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [view, setView] = useState('grid')
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 480px)').matches
  )
  const [loadedPage, setLoadedPage] = useState(1)
  const [loadingMore, setLoadingMore] = useState(false)
  const sentinelRef = useRef(null)
  const loadMoreRef = useRef(() => {})

  const q = params.get('q') || ''
  const category = params.get('category') || ''
  const source = params.get('source') || ''
  const sort = params.get('sort') || 'top'
  const page = parseInt(params.get('page') || '1', 10)

  useEffect(() => {
    const mql = window.matchMedia('(max-width: 480px)')
    const onChange = (e) => setIsMobile(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    categoriesApi.list().then((c) => setCategories(c.items || [])).catch(() => {})
    sourcesApi.list({ counts: true }).then((s) => setSources(s.items || [])).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    setError(null)
    const startPage = isMobile ? 1 : page
    supplementsApi.list({ q, category, source, sort, page: startPage, per_page: 12 })
      .then((d) => {
        setData(d)
        setLoadedPage(startPage)
      })
      .catch((err) => setError(err.userMessage))
      .finally(() => setLoading(false))
  }, [q, category, source, sort, page, isMobile])

  // Fire a 'search' event whenever the user changes the actual search text.
  // Filters/sort/page changes don't count — those are page_views via useTracker.
  useEffect(() => {
    const text = (q || '').trim()
    if (!text) return
    const t = setTimeout(() => {
      trackEvent('search', {
        query: text,
        path: `/browse?q=${encodeURIComponent(text)}`,
        meta: {
          category: category || null,
          source: source || null,
          result_count: data?.total ?? null,
        },
      })
    }, 600) // debounce: don't fire mid-typing
    return () => clearTimeout(t)
  }, [q]) // eslint-disable-line react-hooks/exhaustive-deps

  loadMoreRef.current = () => {
    if (loadingMore || loading) return
    if (loadedPage >= (data.total_pages || 1)) return
    const next = loadedPage + 1
    setLoadingMore(true)
    supplementsApi.list({ q, category, source, sort, page: next, per_page: 12 })
      .then((d) => {
        setData((prev) => ({
          ...d,
          items: [...(prev.items || []), ...(d.items || [])],
        }))
        setLoadedPage(next)
      })
      .catch((err) => setError(err.userMessage))
      .finally(() => setLoadingMore(false))
  }

  useEffect(() => {
    if (!isMobile) return
    let ticking = false
    const check = () => {
      ticking = false
      const el = sentinelRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      if (rect.top < window.innerHeight + 400) loadMoreRef.current()
    }
    const onScroll = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(check)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll, { passive: true })
    const interval = setInterval(check, 250)
    check()
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      clearInterval(interval)
    }
  }, [isMobile])

  const updateParam = (key, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    setParams(next)
  }

  const clearFilters = () => { setParams({}); setMobileFiltersOpen(false) }

  // Lock body scroll while mobile drawer open
  useEffect(() => {
    if (!mobileFiltersOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e) => { if (e.key === 'Escape') setMobileFiltersOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [mobileFiltersOpen])

  const visibleItems = data.items

  const activeFilters = useMemo(() => {
    const list = []
    if (q) list.push({ key: 'q', label: `"${q}"`, clear: () => updateParam('q', '') })
    if (category) list.push({
      key: 'category',
      label: categories.find((c) => c.slug === category)?.name || category,
      clear: () => updateParam('category', ''),
    })
    if (source) list.push({
      key: 'source',
      label: `Tested by ${sources.find((s) => s.slug === source)?.name || source}`,
      clear: () => updateParam('source', ''),
    })
    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, category, source, categories, sources])

  // SEO: build a title that reflects the active filter without becoming spammy.
  // Filtered/paginated/searched permutations are noindex so we don't compete
  // with the canonical /browse page for ranking.
  const categoryName = category ? (categories.find((c) => c.slug === category)?.name || '') : ''
  const sourceName = source ? (sources.find((s) => s.slug === source)?.name || '') : ''
  let seoTitle = 'Browse Supplements'
  let seoDescription = 'Browse supplements rated by independent testing labs. Filter by category, lab, or search by name to find products you can trust.'
  if (q) {
    seoTitle = `Search results for "${q}"`
    seoDescription = `Supplements matching "${q}" — ranked by aggregate quality score across independent labs.`
  } else if (categoryName && sourceName) {
    seoTitle = `${categoryName} tested by ${sourceName}`
    seoDescription = `${categoryName} supplements tested by ${sourceName}. Aggregate quality scores from independent labs.`
  } else if (categoryName) {
    seoTitle = `${categoryName} Supplements`
    seoDescription = `${categoryName} supplements rated by independent testing labs. Compare aggregate quality scores side by side.`
  } else if (sourceName) {
    seoTitle = `Supplements tested by ${sourceName}`
    seoDescription = `All supplements in our catalog with ratings from ${sourceName}.`
  }
  const seoNoindex = !!(q || page > 1 || sort !== 'top')
  const canonicalPath = category ? `/browse?category=${category}` : '/browse'
  const seoJsonLd = [buildBreadcrumbJsonLd([
    { name: 'Home', url: '/' },
    { name: 'Browse', url: '/browse' },
    ...(categoryName ? [{ name: categoryName, url: `/browse?category=${category}` }] : []),
  ])]
  if (!seoNoindex) {
    seoJsonLd.push(buildCollectionPageJsonLd({
      name: seoTitle,
      description: seoDescription,
      path: canonicalPath,
      itemCount: data.total,
    }))
    if (visibleItems.length > 0) {
      seoJsonLd.push(buildItemListJsonLd(visibleItems, canonicalPath))
    }
  }
  // Pagination link tags. Only emit on permutations we actually index.
  const buildPageUrl = (p) => {
    const usp = new URLSearchParams()
    if (q) usp.set('q', q)
    if (category) usp.set('category', category)
    if (source) usp.set('source', source)
    if (sort && sort !== 'top') usp.set('sort', sort)
    if (p > 1) usp.set('page', String(p))
    const qs = usp.toString()
    return `/browse${qs ? `?${qs}` : ''}`
  }
  const totalPages = data.total_pages || 1
  const seoPrev = !seoNoindex && page > 1 ? buildPageUrl(page - 1) : undefined
  const seoNext = !seoNoindex && page < totalPages ? buildPageUrl(page + 1) : undefined

  return (
    <div className="browse fade-in">
      <Seo
        title={seoTitle}
        description={seoDescription}
        path={canonicalPath}
        noindex={seoNoindex}
        jsonLd={seoJsonLd}
        prev={seoPrev}
        next={seoNext}
      />
      <div className="container">
        <header className="browse-head">
          <div className="crumbs">
            <Link to="/">Home</Link>
            <span>›</span>
            <span>Browse</span>
          </div>
          <div className="browse-title-row">
            <h1>Browse supplements</h1>
            <span className="browse-count">
              {loading ? 'Loading…' : `${data.total} ${data.total === 1 ? 'product' : 'products'}`}
            </span>
          </div>
        </header>

        <div className="browse-grid">
          {mobileFiltersOpen && (
            <div
              className="filters-backdrop"
              onClick={() => setMobileFiltersOpen(false)}
              aria-hidden="true"
            />
          )}
          <aside className={`filters ${mobileFiltersOpen ? 'filters-open' : ''}`}>
            <div className="filters-mobile-header">
              <h3>Filters</h3>
              <button
                type="button"
                className="filters-close"
                onClick={() => setMobileFiltersOpen(false)}
                aria-label="Close filters"
              >
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="filter-section">
              <h4>Category</h4>
              <ul className="filter-list">
                <li>
                  <button
                    type="button"
                    className={!category ? 'active' : ''}
                    onClick={() => updateParam('category', '')}
                  >
                    All categories
                    <span className="filter-count">{data.total ?? ''}</span>
                  </button>
                </li>
                {categories.map((c) => {
                  if (!c.supplement_count) return null
                  return (
                    <li key={c.slug}>
                      <button
                        type="button"
                        className={category === c.slug ? 'active' : ''}
                        onClick={() => updateParam('category', c.slug)}
                      >
                        <span className="filter-icon">{getCategoryEmoji(c.icon)}</span>
                        {c.name}
                        <span className="filter-count">{c.supplement_count}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>

            <div className="filter-section">
              <h4>Tested by</h4>
              <ul className="filter-list">
                <li>
                  <button
                    type="button"
                    className={!source ? 'active' : ''}
                    onClick={() => updateParam('source', '')}
                  >
                    All labs
                  </button>
                </li>
                {sources
                  .filter((s) => (s.supplement_count ?? 0) > 0)
                  .map((s) => (
                    <li key={s.slug}>
                      <button
                        type="button"
                        className={source === s.slug ? 'active' : ''}
                        onClick={() => updateParam('source', s.slug)}
                        title={s.description}
                      >
                        <span className="filter-dot" style={{ background: s.color || s.brand_color || '#0F766E' }}></span>
                        {s.name}
                        <span className="filter-count">{s.supplement_count}</span>
                      </button>
                    </li>
                  ))}
              </ul>
            </div>

            {/* Sort lives inside the filter drawer on mobile so the toolbar
              * stays uncluttered. Hidden on desktop where the toolbar select
              * is always visible. */}
            <div className="filter-section filter-section-mobile">
              <h4>Sort by</h4>
              <ul className="filter-list">
                {[
                  { value: 'top', label: 'Top rated' },
                  { value: 'lowest', label: 'Lowest rated' },
                  { value: 'price_asc', label: 'Price: Low to High' },
                  { value: 'price_desc', label: 'Price: High to Low' },
                  { value: 'name', label: 'Name (A–Z)' },
                  { value: 'newest', label: 'Newest' },
                ].map((opt) => (
                  <li key={opt.value}>
                    <button
                      type="button"
                      className={sort === opt.value ? 'active' : ''}
                      onClick={() => updateParam('sort', opt.value)}
                    >
                      {opt.label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            <div className="filters-mobile-footer">
              <button type="button" className="btn btn-secondary" onClick={clearFilters}>
                Clear
              </button>
              <button type="button" className="btn btn-primary" onClick={() => setMobileFiltersOpen(false)}>
                Show {visibleItems.length} {visibleItems.length === 1 ? 'result' : 'results'}
              </button>
            </div>
          </aside>

          <section className="results">
            <div className="toolbar">
              {/* Mobile-only filter trigger — visible only on mobile via CSS.
               * Lives inside the toolbar so it sits on the same row as the
               * grid/list toggle on small screens. */}
              <button
                type="button"
                className="filters-mobile-trigger"
                onClick={() => setMobileFiltersOpen(true)}
                aria-label="Open filters"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="4" y1="6" x2="20" y2="6"/>
                  <line x1="4" y1="12" x2="14" y2="12"/>
                  <line x1="4" y1="18" x2="9" y2="18"/>
                </svg>
                Filters
                {activeFilters.length > 0 && (
                  <span className="filters-badge">{activeFilters.length}</span>
                )}
              </button>
              <div className="chips">
                {activeFilters.map((f) => (
                  <span key={f.key} className="chip chip-active">
                    {f.label}
                    <button type="button" onClick={f.clear} aria-label="Remove">×</button>
                  </span>
                ))}
                {activeFilters.length > 0 && (
                  <button type="button" className="btn-text" onClick={clearFilters}>Clear all</button>
                )}
              </div>
              <div className="toolbar-right">
                <select
                  className="sort"
                  value={sort}
                  onChange={(e) => updateParam('sort', e.target.value)}
                >
                  <option value="top">Top rated</option>
                  <option value="lowest">Lowest rated</option>
                  <option value="price_asc">Price: Low to High</option>
                  <option value="price_desc">Price: High to Low</option>
                  <option value="name">Name (A–Z)</option>
                  <option value="newest">Newest</option>
                </select>
                <div className="browse-view-toggle">
                  <button
                    type="button"
                    className={view === 'grid' ? 'active' : ''}
                    onClick={() => setView('grid')}
                    title="Grid view"
                    aria-label="Grid view"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
                  </button>
                  <button
                    type="button"
                    className={view === 'list' ? 'active' : ''}
                    onClick={() => setView('list')}
                    title="List view"
                    aria-label="List view"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
                  </button>
                </div>
              </div>
            </div>

            {error ? (
              <ErrorState message={error} onRetry={() => window.location.reload()} />
            ) : loading ? (
              <div className="grid-cards-dense">
                {Array(8).fill(null).map((_, i) => <CardSkeleton key={i} />)}
              </div>
            ) : visibleItems.length === 0 ? (
              <div className="empty">
                <span style={{ fontSize: 48 }}>🔍</span>
                <h3>No supplements match those filters</h3>
                <p className="muted">Try removing a filter or searching for something else.</p>
                <button type="button" className="btn btn-primary" onClick={clearFilters}>Clear filters</button>
              </div>
            ) : view === 'grid' ? (
              <>
                <div className="grid-cards-dense">
                  {visibleItems.map((s) => (
                    <SupplementCard key={s.id || s.slug} supplement={s} compact />
                  ))}
                </div>
                {isMobile ? (
                  <InfiniteFooter
                    sentinelRef={sentinelRef}
                    hasMore={loadedPage < (data.total_pages || 1)}
                    loading={loadingMore}
                    total={data.total}
                  />
                ) : (
                  data.total_pages > 1 && (
                    <Pagination
                      page={page}
                      totalPages={data.total_pages}
                      total={data.total}
                      perPage={12}
                      onChange={(p) => {
                        updateParam('page', String(p))
                        window.scrollTo({ top: 200, behavior: 'smooth' })
                      }}
                    />
                  )
                )}
              </>
            ) : (
              <>
                <div className="list">
                  {visibleItems.map((s) => <ListRow key={s.id || s.slug} supplement={s} />)}
                </div>
                {isMobile ? (
                  <InfiniteFooter
                    sentinelRef={sentinelRef}
                    hasMore={loadedPage < (data.total_pages || 1)}
                    loading={loadingMore}
                    total={data.total}
                  />
                ) : (
                  data.total_pages > 1 && (
                    <Pagination
                      page={page}
                      totalPages={data.total_pages}
                      total={data.total}
                      perPage={12}
                      onChange={(p) => {
                        updateParam('page', String(p))
                        window.scrollTo({ top: 200, behavior: 'smooth' })
                      }}
                    />
                  )
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function ListRow({ supplement: s }) {
  const { add, remove, has, canAdd, max } = useCompare()
  const inCompare = has(s.slug)
  const blockReason = inCompare ? null : canAdd(s)
  const compareDisabled = blockReason === 'full'
  const brandName = s.brand?.name || s.brand || ''
  const displayName = cleanProductName(s.name, brandName)

  let compareTitle
  if (inCompare) compareTitle = 'Remove from compare'
  else if (compareDisabled) compareTitle = `Compare full (${max} max)`
  else compareTitle = 'Add to compare'

  const toggle = (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (inCompare) remove(s.slug)
    else add({ ...s, brand: brandName, image: s.image })
  }

  return (
    <Link to={`/supplement/${s.slug}`} className="list-row">
      <div className="list-icon">
        {s.image ? (
          <img src={s.image} alt={`${brandName} ${displayName}`.trim()} loading="lazy" />
        ) : (
          <span className="list-icon-emoji">{getCategoryEmoji(s.category?.icon)}</span>
        )}
      </div>
      <div className="list-main">
        {brandName && <span className="list-brand">{brandName}</span>}
        <h3>{displayName}</h3>
        <div className="list-meta">
          {s.category && <span className="badge badge-primary">{s.category.name}</span>}
          {s.form && <span className="badge">{s.form}</span>}
          {s.size && <span className="list-size">{s.size}</span>}
          {s.price && <span className="list-price">{s.price}</span>}
        </div>
      </div>
      <div className="list-score">
        <ScoreRing score={s.aggregate_score} size={56} stroke={5} />
        <div className="list-score-text">
          <strong style={{ color: getScoreColor(s.aggregate_score) }}>{getScoreGrade(s.aggregate_score)}</strong>
          {s.review_count != null && (
            <span className="muted">{s.review_count} {s.review_count === 1 ? 'lab' : 'labs'}</span>
          )}
        </div>
      </div>
      <div className="list-actions" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          className={`btn btn-sm ${inCompare ? 'btn-secondary' : 'btn-ghost'}`}
          onClick={toggle}
          disabled={compareDisabled}
          title={compareTitle}
        >
          {inCompare ? '✓ Added' : '+ Compare'}
        </button>
      </div>
    </Link>
  )
}

function InfiniteFooter({ sentinelRef, hasMore, loading, total }) {
  if (!hasMore) {
    return (
      <div className="infinite-end">
        <span className="muted">All {total} {total === 1 ? 'product' : 'products'} loaded</span>
      </div>
    )
  }
  return (
    <div ref={sentinelRef} className="infinite-sentinel" aria-live="polite">
      <span className="infinite-spinner" aria-hidden="true" />
      <span className="muted">{loading ? 'Loading more…' : 'Scroll for more'}</span>
    </div>
  )
}

function Pagination({ page, totalPages, total, perPage, onChange }) {
  if (totalPages <= 1) {
    return (
      <div className="pagination-wrap">
        <span className="muted">Showing {total} {total === 1 ? 'product' : 'products'}</span>
      </div>
    )
  }
  const pages = []
  const start = Math.max(1, page - 2)
  const end = Math.min(totalPages, page + 2)
  for (let i = start; i <= end; i++) pages.push(i)
  const startIdx = total === 0 ? 0 : (page - 1) * perPage + 1
  const endIdx = Math.min(page * perPage, total)

  return (
    <div className="pagination-wrap">
      <span className="muted">Showing {startIdx}–{endIdx} of {total}</span>
      <nav className="pagination" aria-label="Pagination">
        <button type="button" className="page-btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="m15 18-6-6 6-6"/></svg>
          Prev
        </button>
        {start > 1 && (
          <>
            <button type="button" className="page-num" onClick={() => onChange(1)}>1</button>
            {start > 2 && <span className="page-dots">…</span>}
          </>
        )}
        {pages.map((p) => (
          <button
            key={p}
            type="button"
            className={`page-num ${p === page ? 'active' : ''}`}
            onClick={() => onChange(p)}
          >
            {p}
          </button>
        ))}
        {end < totalPages && (
          <>
            {end < totalPages - 1 && <span className="page-dots">…</span>}
            <button type="button" className="page-num" onClick={() => onChange(totalPages)}>{totalPages}</button>
          </>
        )}
        <button type="button" className="page-btn" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
          Next
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="m9 18 6-6-6-6"/></svg>
        </button>
      </nav>
    </div>
  )
}
