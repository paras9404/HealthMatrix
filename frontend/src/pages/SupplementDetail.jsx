import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { supplementsApi } from '../services/api.js'
import { trackEvent } from '../hooks/useTracker.js'
import ScoreRing from '../components/ScoreRing.jsx'
import ImageGallery from '../components/ImageGallery.jsx'
import SupplementCard from '../components/SupplementCard.jsx'
import { Spinner, ErrorState } from '../components/Loader.jsx'
import Seo from '../components/Seo.jsx'
import { useCompare } from '../hooks/useCompare.jsx'
import { getCategoryEmoji, getScoreColor, getScoreGrade, formatScore, formatDate, cleanProductName } from '../utils/format.js'
import { buildProductJsonLd, buildBreadcrumbJsonLd } from '../utils/seo.js'
import './SupplementDetail.css'

export default function SupplementDetail() {
  const { slug } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('ratings')
  const { add, remove, has, canAdd, max } = useCompare()

  useEffect(() => {
    setLoading(true)
    setError(null)
    setTab('ratings')
    window.scrollTo(0, 0)
    supplementsApi.get(slug)
      .then((d) => {
        setData(d)
        const canonicalSlug = d?.canonical_slug || slug
        if (d?.canonical_slug && d.canonical_slug !== slug) {
          window.history.replaceState(null, '', `/supplement/${d.canonical_slug}`)
        }
        trackEvent('supplement_view', {
          path: `/supplement/${canonicalSlug}`,
          entity_type: 'supplement',
          entity_id: canonicalSlug,
        })
      })
      .catch((err) => setError(err.userMessage))
      .finally(() => setLoading(false))
  }, [slug])

  const showBreakdown = (data?.ratings || []).length > 1

  // If user landed on breakdown tab but it shouldn't be visible, snap back to ratings
  useEffect(() => {
    if (tab === 'breakdown' && !showBreakdown) setTab('ratings')
  }, [tab, showBreakdown])

  const brandName = data?.brand?.name || data?.brand || ''
  const displayName = useMemo(
    () => cleanProductName(data?.name, brandName),
    [data?.name, brandName],
  )
  const sortedRatings = useMemo(
    () => [...(data?.ratings || [])].sort((a, b) => (b.normalized_score || 0) - (a.normalized_score || 0)),
    [data?.ratings],
  )

  if (loading) return <Spinner />
  if (error) return (
    <>
      <Seo title="Supplement not found" path={`/supplement/${slug}`} noindex />
      <div className="container" style={{ padding: 'var(--space-10) 0' }}><ErrorState message={error} /></div>
    </>
  )
  if (!data) return null

  const inCompare = has(data.slug)
  const cat = data.category
  const score = data.aggregate_score
  const reviews = data.review_count
  const tested = sortedRatings[0]?.tested_at ? formatDate(sortedRatings[0].tested_at) : null

  // SEO copy: brand + product name in title, score + lab count in description.
  const seoTitle = brandName ? `${brandName} ${displayName}` : displayName
  const seoDescriptionParts = []
  if (score != null) seoDescriptionParts.push(`HealthMatrix score ${Math.round(score)}/100 (${getScoreGrade(score)})`)
  if (sortedRatings.length > 0) seoDescriptionParts.push(`${sortedRatings.length} independent lab ${sortedRatings.length === 1 ? 'rating' : 'ratings'}`)
  if (cat?.name) seoDescriptionParts.push(`Category: ${cat.name}`)
  const seoDescription = seoDescriptionParts.length
    ? `${seoTitle} — ${seoDescriptionParts.join(' · ')}. See all lab scores side-by-side on HealthMatrix.`
    : `${seoTitle} reviewed and rated by independent supplement testing labs.`

  const seoJsonLd = [
    buildProductJsonLd({ ...data, name: seoTitle, ratings: sortedRatings }),
    buildBreadcrumbJsonLd([
      { name: 'Home', url: '/' },
      { name: 'Browse', url: '/browse' },
      ...(cat ? [{ name: cat.name, url: `/browse?category=${cat.slug}` }] : []),
      { name: displayName, url: `/supplement/${data.slug}` },
    ]),
  ]

  return (
    <div className="detail fade-in">
      <Seo
        title={seoTitle}
        description={seoDescription}
        path={`/supplement/${data.slug}`}
        image={data.image}
        imageAlt={brandName ? `${brandName} ${displayName}` : displayName}
        type="product"
        publishedTime={data.created_at || undefined}
        modifiedTime={data.updated_at || undefined}
        jsonLd={seoJsonLd}
      />
      <div className="container">
        <div className="detail-head">
          <div className="crumbs">
            <Link to="/">Home</Link>
            <span>›</span>
            <Link to="/browse">Browse</Link>
            {cat && (
              <>
                <span>›</span>
                <Link to={`/browse?category=${cat.slug}`}>{cat.name}</Link>
              </>
            )}
            <span>›</span>
            <span className="muted">{displayName}</span>
          </div>

          <div className="detail-hero">
            <div className="detail-img">
              <ImageGallery
                images={data.images}
                fallbackEmoji={getCategoryEmoji(cat?.icon)}
                alt={displayName}
              />
            </div>
            <div className="detail-info">
              {brandName && <span className="detail-brand">{brandName}</span>}
              <h1>{displayName}</h1>
              {(data.price || data.size || data.servings) && (
                <div className="detail-specs">
                  {data.price && <span className="detail-price">{data.price}</span>}
                  {data.size && <span className="detail-spec">{data.size}</span>}
                  {data.servings && (
                    <span className="detail-spec">
                      {data.servings} {data.servings === 1 ? 'serving' : 'servings'}
                    </span>
                  )}
                </div>
              )}
              <div className="detail-tags">
                {cat && (
                  <span className="badge badge-primary">
                    {getCategoryEmoji(cat.icon)} {cat.name}
                  </span>
                )}
                {data.form && <span className="badge">{data.form}</span>}
                {data.is_featured && <span className="badge badge-warning">Featured</span>}
              </div>
              {(data.serving_size || tested) && (
                <p className="muted">
                  {data.serving_size && <>Serving size {data.serving_size}</>}
                  {data.serving_size && tested && <> · </>}
                  {tested && <>Last tested {tested}</>}
                </p>
              )}
            </div>

            <div className="detail-actions">
              {(() => {
                const blockReason = inCompare ? null : canAdd(data)
                const disabled = blockReason === 'full'
                let label = inCompare ? '✓ Added to compare' : '+ Add to compare'
                let title = ''
                if (disabled) {
                  label = `Compare full (${max} max)`
                  title = 'Remove an item from compare to add this one.'
                }
                return (
                  <button
                    type="button"
                    className={`btn ${inCompare ? 'btn-secondary' : 'btn-primary'} btn-lg`}
                    onClick={() => inCompare
                      ? remove(data.slug)
                      : add({ ...data, brand: brandName, image: data.image })
                    }
                    disabled={disabled}
                    title={title}
                  >
                    {label}
                  </button>
                )
              })()}
            </div>

            <div className="detail-score-card">
              {score != null ? (
                <div className="detail-score-ring" style={{ borderColor: getScoreColor(score), color: getScoreColor(score) }}>
                  <strong className="detail-score-value">{Math.round(score)}</strong>
                </div>
              ) : (
                <div className="detail-score-ring detail-score-ring-empty">
                  <span className="detail-score-value">—</span>
                </div>
              )}
              <div className="detail-score-text">
                <span className="detail-score-grade" style={{ color: getScoreColor(score) }}>
                  {getScoreGrade(score)}
                </span>
                <span className="detail-score-meta">
                  Based on {reviews || sortedRatings.length} {(reviews || sortedRatings.length) === 1 ? 'source' : 'sources'}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="detail-tabs">
          <button
            type="button"
            className={tab === 'ratings' ? 'active' : ''}
            onClick={() => setTab('ratings')}
          >
            Lab ratings ({sortedRatings.length})
          </button>
          {showBreakdown && (
            <button
              type="button"
              className={tab === 'breakdown' ? 'active' : ''}
              onClick={() => setTab('breakdown')}
            >
              Score breakdown
            </button>
          )}
          <button
            type="button"
            className={tab === 'about' ? 'active' : ''}
            onClick={() => setTab('about')}
          >
            About this product
          </button>
        </div>

        <div className="detail-body">
          {tab === 'ratings' && (
            <div className="ratings">
              {sortedRatings.length === 0 ? (
                <div className="detail-empty">
                  <p>No ratings available yet for this supplement.</p>
                </div>
              ) : (
                sortedRatings.map((r) => <RatingRow key={r.id} rating={r} />)
              )}
            </div>
          )}

          {tab === 'breakdown' && showBreakdown && (
            <div className="breakdown">
              <div className="bd-section-title">
                <strong>Lab inputs</strong>
                <span className="muted">{sortedRatings.length} sources contributing to this score</span>
              </div>

              <div className="bd-rows">
                {sortedRatings.map((r) => {
                  const norm = r.normalized_score
                  const src = r.source || {}
                  return (
                    <div key={r.id} className="bd-row">
                      <div className="bd-lab">
                        <span className="bd-lab-dot" style={{ background: src.color || src.brand_color || '#0F766E' }}></span>
                        <div>
                          <strong>{src.name}</strong>
                          <span className="muted">{src.is_verified ? 'Verified source' : 'Unverified · ½ weight'}</span>
                        </div>
                      </div>
                      <div className="bd-original">
                        <span className="muted">Original</span>
                        <strong>
                          {formatScore(r.score)}<span className="bd-original-max">/{r.max_score || 100}</span>
                        </strong>
                      </div>
                      <div className="bd-meter">
                        <div className="bd-meter-track">
                          <div
                            className="bd-meter-fill"
                            style={{ width: `${norm || 0}%`, background: getScoreColor(norm) }}
                          ></div>
                        </div>
                        <span className="bd-meter-val" style={{ color: getScoreColor(norm) }}>
                          {Math.round(norm || 0)}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="bd-result">
                <div className="bd-result-icon">
                  <ScoreRing score={score} size={72} stroke={6} />
                </div>
                <div className="bd-result-text">
                  <span className="muted">Aggregate HealthMatrix Score</span>
                  <strong style={{ color: getScoreColor(score) }}>
                    {Math.round(score || 0)} <em>· {getScoreGrade(score)}</em>
                  </strong>
                  <span className="muted">
                    Computed from {sortedRatings.length} independent labs{tested ? ` · Last refreshed ${tested}` : ''}
                  </span>
                </div>
              </div>

              <div className="bd-header">
                <div>
                  <span className="eyebrow-sm">Methodology</span>
                  <h3>How we calculate the HealthMatrix Score</h3>
                  <p className="muted">
                    Independent labs grade on different scales — letters, percentages, 1–10. We translate every
                    result into one comparable number.
                  </p>
                </div>
                <div className="bd-formula">
                  <div className="bd-step">
                    <span className="bd-step-num">1</span>
                    <strong>Normalize</strong>
                    <span>Convert each lab's grade to a 0–100 scale</span>
                  </div>
                  <span className="bd-step-arrow">→</span>
                  <div className="bd-step">
                    <span className="bd-step-num">2</span>
                    <strong>Weight</strong>
                    <span>Unverified labs count as half-weight</span>
                  </div>
                  <span className="bd-step-arrow">→</span>
                  <div className="bd-step">
                    <span className="bd-step-num">3</span>
                    <strong>Average</strong>
                    <span>Combine into one aggregate score</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === 'about' && (
            <div className="about-product">
              <div className="about-grid">
                {brandName && (
                  <div><span className="muted">Brand</span><strong>{brandName}</strong></div>
                )}
                {cat?.name && (
                  <div><span className="muted">Category</span><strong>{cat.name}</strong></div>
                )}
                {data.form && (
                  <div><span className="muted">Form</span><strong>{data.form}</strong></div>
                )}
                {data.price && (
                  <div><span className="muted">Price</span><strong>{data.price}</strong></div>
                )}
                {data.size && (
                  <div><span className="muted">Size</span><strong>{data.size}</strong></div>
                )}
                {data.servings && (
                  <div><span className="muted">Servings per container</span><strong>{data.servings}</strong></div>
                )}
                {data.serving_size && (
                  <div><span className="muted">Serving size</span><strong>{data.serving_size}</strong></div>
                )}
                {tested && (
                  <div><span className="muted">Last tested</span><strong>{tested}</strong></div>
                )}
              </div>
              {data.ingredients && (
                <div className="about-card-section">
                  <h4>Ingredients</h4>
                  <p>{data.ingredients}</p>
                </div>
              )}
              <div className="disclaimer">
                <strong>Disclaimer.</strong> HealthMatrix aggregates publicly available data from independent labs.
                We don't test supplements ourselves. This isn't medical advice — consult a healthcare professional
                before starting any regimen.
              </div>
            </div>
          )}
        </div>

        {cat && (
          <SimilarProducts
            categorySlug={cat.slug}
            categoryName={cat.name}
            currentSlug={data.slug}
          />
        )}
      </div>
    </div>
  )
}

function SimilarProducts({ categorySlug, categoryName, currentSlug }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    supplementsApi.list({ category: categorySlug, sort: 'top', per_page: 5 })
      .then((res) => {
        if (cancelled) return
        const filtered = (res.items || [])
          .filter((s) => s.slug !== currentSlug)
          .slice(0, 4)
        setItems(filtered)
      })
      .catch(() => { if (!cancelled) setItems([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [categorySlug, currentSlug])

  if (loading || items.length === 0) return null

  return (
    <section className="similar-section">
      <div className="similar-head">
        <h2>More top-rated {categoryName}</h2>
        <Link to={`/browse?category=${categorySlug}`} className="similar-link">
          See all {categoryName} →
        </Link>
      </div>
      <div className="similar-grid">
        {items.map((s) => (
          <SupplementCard key={s.slug} supplement={s} compact />
        ))}
      </div>
    </section>
  )
}

function RatingRow({ rating }) {
  const score = rating.normalized_score
  const color = getScoreColor(score)
  const src = rating.source || {}
  return (
    <div className="rating-row">
      <div className="rating-source">
        <div
          className="source-mark"
          style={{ background: src.color || src.brand_color || 'var(--color-primary)' }}
        >
          {(src.name || '?').charAt(0)}
        </div>
        <div>
          <div className="rating-name">
            {src.name}
            {src.is_verified && <span className="check">✓</span>}
          </div>
          <div className="muted">{rating.summary || (rating.tested_at && `Tested ${formatDate(rating.tested_at)}`) || ''}</div>
        </div>
      </div>
      <div className="rating-score">
        {score != null && <ScoreRing score={score} size={48} stroke={4} />}
        <div className="rating-score-text">
          <strong>
            {formatScore(rating.score)}
            <span className="muted">/{rating.max_score || 100}</span>
          </strong>
          {rating.verdict && (
            <span
              className="badge"
              style={{
                background: `color-mix(in srgb, ${color} 14%, transparent)`,
                color,
              }}
            >
              {rating.verdict}
            </span>
          )}
        </div>
      </div>
      <div className="rating-actions">
        {rating.report_url && (
          <a
            href={rating.report_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary btn-sm"
            onClick={() => trackEvent('outbound_click', {
              meta: { url: rating.report_url, source: rating.source?.name || rating.source_name || null },
            })}
          >
            Full report ↗
          </a>
        )}
      </div>
    </div>
  )
}
