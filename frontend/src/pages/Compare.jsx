import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { compareApi } from '../services/api.js'
import { useCompare } from '../hooks/useCompare.jsx'
import { trackEvent } from '../hooks/useTracker.js'
import ScoreRing from '../components/ScoreRing.jsx'
import { Spinner, EmptyState } from '../components/Loader.jsx'
import Seo from '../components/Seo.jsx'
import { getCategoryEmoji, getScoreColor, getScoreGrade, cleanProductName, imageSrc } from '../utils/format.js'
import './Compare.css'

export default function Compare() {
  const { items, remove, clear } = useCompare()
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (items.length < 2) { setData([]); return }
    setLoading(true)
    const slugs = items.map((i) => i.slug)
    compareApi.get(slugs)
      .then((res) => {
        setData(res.items || [])
        trackEvent('compare', {
          path: `/compare?slugs=${slugs.join(',')}`,
          meta: { slugs, count: slugs.length },
        })
      })
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [items])

  if (items.length === 0) {
    return (
      <div className="container compare-empty">
        <Seo
          title="Compare Supplements Side by Side"
          description="Compare up to 4 supplements head-to-head — aggregate scores, lab ratings, ingredients, and price."
          path="/compare"
          noindex
        />
        <div className="empty">
          <span style={{ fontSize: 56 }}>⚖️</span>
          <h1>
            Nothing to compare yet
            <span className="compare-beta-tag" title="Beta — under active development">Beta</span>
          </h1>
          <p className="muted">Add 2–4 supplements of the same category from Browse to see them side-by-side.</p>
          <Link to="/browse" className="btn btn-primary btn-lg">Browse supplements</Link>
        </div>
      </div>
    )
  }

  if (items.length < 2) {
    const lockedSlug = items[0]?.category?.slug
    const browseHref = lockedSlug ? `/browse?category=${encodeURIComponent(lockedSlug)}` : '/browse'
    return (
      <div className="container compare-empty">
        <Seo
          title="Compare Supplements Side by Side"
          description="Compare up to 4 supplements head-to-head — aggregate scores, lab ratings, ingredients, and price."
          path="/compare"
          noindex
        />
        <h1 className="sr-only">Compare supplements</h1>
        <EmptyState
          title="Add at least one more supplement"
          description="You need at least 2 supplements to compare. Head back to browse and add another."
          action={<Link to={browseHref} className="btn btn-primary">Add another</Link>}
        />
      </div>
    )
  }

  if (loading || data.length === 0) return <Spinner />

  const allSources = new Map()
  data.forEach((s) => {
    (s.ratings || []).forEach((r) => {
      if (r.source) allSources.set(r.source.slug, r.source)
    })
  })
  const sources = Array.from(allSources.values()).sort((a, b) => a.name.localeCompare(b.name))

  const compareNames = data.map((s) => cleanProductName(s.name, s.brand?.name || s.brand)).filter(Boolean)
  const compareSeoTitle = compareNames.length ? `Compare ${compareNames.join(' vs ')}` : 'Compare Supplements'

  return (
    <div className="compare fade-in">
      <Seo
        title={compareSeoTitle}
        description={`Side-by-side comparison of ${compareNames.join(', ')} — aggregate score, lab ratings, ingredients, and price.`}
        path="/compare"
        noindex
      />
      <div className="container">
        <h1 className="sr-only">{compareSeoTitle}</h1>
        <header className="compare-head">
          <div className="crumbs">
            <Link to="/">Home</Link>
            <span>›</span>
            <span>Compare</span>
            <span className="compare-beta-tag" title="Beta — under active development">Beta</span>
          </div>
          <button type="button" className="btn btn-ghost" onClick={clear}>Clear all</button>
        </header>
        <div className="compare-table-wrap">
          <table className="compare-table">
            <thead>
              <tr>
                <th></th>
                {data.map((s) => {
                  const brandName = s.brand?.name || s.brand || ''
                  return (
                    <th key={s.slug} className="ct-product">
                      <button
                        type="button"
                        className="ct-remove"
                        onClick={() => remove(s.slug)}
                        aria-label="Remove"
                      >
                        ×
                      </button>
                      <Link to={`/supplement/${s.slug}`} className="ct-product-link">
                        <div className="ct-img">
                          {s.image ? (
                            <img src={imageSrc(s.image)} alt={s.name} />
                          ) : (
                            <span>{getCategoryEmoji(s.category?.icon)}</span>
                          )}
                        </div>
                        {brandName && <span className="ct-brand">{brandName}</span>}
                        <strong>{cleanProductName(s.name, brandName)}</strong>
                      </Link>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              <tr className="ct-divider"><td colSpan={data.length + 1}>Overview</td></tr>
              <tr>
                <th>Aggregate score</th>
                {data.map((s) => (
                  <td key={s.slug}>
                    <div className="ct-score">
                      <ScoreRing score={s.aggregate_score} size={44} stroke={4} />
                      <strong style={{ color: getScoreColor(s.aggregate_score) }}>
                        {getScoreGrade(s.aggregate_score)}
                      </strong>
                    </div>
                  </td>
                ))}
              </tr>
              <tr>
                <th>Category</th>
                {data.map((s) => (
                  <td key={s.slug}>
                    {s.category ? (
                      <span className="badge badge-primary">{s.category.name}</span>
                    ) : '—'}
                  </td>
                ))}
              </tr>
              <tr>
                <th>Form</th>
                {data.map((s) => <td key={s.slug}>{s.form || '—'}</td>)}
              </tr>
              <tr>
                <th>Size</th>
                {data.map((s) => <td key={s.slug}>{s.size || '—'}</td>)}
              </tr>
              <tr>
                <th>Servings</th>
                {data.map((s) => (
                  <td key={s.slug}>
                    {s.servings ? `${s.servings} ${s.servings === 1 ? 'serving' : 'servings'}` : '—'}
                  </td>
                ))}
              </tr>
              <tr>
                <th>Serving size</th>
                {data.map((s) => <td key={s.slug}>{s.serving_size || '—'}</td>)}
              </tr>
              <tr>
                <th>Price</th>
                {data.map((s) => {
                  const price = s.price || s.price_range
                  return (
                    <td key={s.slug}>
                      {price ? <span className="badge badge-accent">{price}</span> : '—'}
                    </td>
                  )
                })}
              </tr>

              <tr className="ct-divider"><td colSpan={data.length + 1}>Lab ratings</td></tr>
              {sources.map((src) => (
                <tr key={src.slug}>
                  <th>
                    <span
                      className="filter-dot"
                      style={{ background: src.color || src.brand_color || '#0F766E' }}
                    ></span>{' '}
                    {src.name}
                  </th>
                  {data.map((s) => {
                    const r = (s.ratings || []).find((rt) => rt.source?.slug === src.slug)
                    if (!r) return <td key={s.slug}><span className="muted">Not tested</span></td>
                    const norm = r.normalized_score
                    const c = getScoreColor(norm)
                    return (
                      <td key={s.slug}>
                        <div className="ct-rating">
                          <strong style={{ color: c }}>{Math.round(norm || 0)}</strong>
                          {r.verdict && (
                            <span
                              className="badge"
                              style={{
                                background: `color-mix(in srgb, ${c} 14%, transparent)`,
                                color: c,
                              }}
                            >
                              {r.verdict}
                            </span>
                          )}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}

              <tr className="ct-divider"><td colSpan={data.length + 1}>Actions</td></tr>
              <tr>
                <th></th>
                {data.map((s) => (
                  <td key={s.slug}>
                    <Link
                      to={`/supplement/${s.slug}`}
                      className="btn btn-primary btn-sm"
                    >
                      View details
                    </Link>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
