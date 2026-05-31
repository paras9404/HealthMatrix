import { Link } from 'react-router-dom'
import ScoreRing from './ScoreRing.jsx'
import { getCategoryEmoji, getScoreColor, getScoreGrade, cleanProductName, shortenName, imageSrc } from '../utils/format.js'
import './HeroDashboard.css'

// Map a 0-100 normalized score to the lab's own framing for the tickers —
// "Certified" reads better when the lab uses pass/fail style verdicts, and
// "Quality" matches Labdoor's grade-style language.
function tickerLabel(sourceSlug, score) {
  const rounded = Math.round(score ?? 0)
  if (sourceSlug === 'labdoor') return `${getScoreGrade(score)} Quality`
  return `Certified · ${rounded}/100`
}

export default function HeroDashboard({ featured = [] }) {
  const top = featured[0]
  const next = featured.slice(1, 3)
  if (!top) {
    return (
      <div className="hero-dash">
        <div className="dash-card skeleton" style={{ height: 320 }} />
        <div className="dash-blob dash-blob-1" aria-hidden="true"></div>
        <div className="dash-blob dash-blob-2" aria-hidden="true"></div>
      </div>
    )
  }

  const cat = top.category
  const brandName = top.brand?.name || top.brand || ''
  const displayName = cleanProductName(top.name, brandName)
  const score = top.aggregate_score
  const reviews = top.review_count
  const ratings = (top.ratings || []).slice(0, 3)

  // Source the ticker badges from the product's actual lab ratings rather
  // than a hardcoded NSF/Labdoor pair, so the visible lab names always match
  // who tested *this* supplement.
  const tickerSources = ratings
    .filter((r) => r.source?.name)
    .slice(0, 2)
  const ticker1 = tickerSources[0]
  const ticker2 = tickerSources[1]

  return (
    <div className="hero-dash">
      {ticker1 && (
        <div className="dash-ticker dash-ticker-1">
          <span className="tick-dot" style={{ background: ticker1.source.color || undefined }}></span>
          <strong>{ticker1.source.name}</strong>
          <span>{tickerLabel(ticker1.source.slug, ticker1.normalized_score)}</span>
        </div>
      )}
      {ticker2 && (
        <div className="dash-ticker dash-ticker-2">
          <span className="tick-dot tick-dot-warn" style={{ background: ticker2.source.color || undefined }}></span>
          <strong>{ticker2.source.name}</strong>
          <span>{tickerLabel(ticker2.source.slug, ticker2.normalized_score)}</span>
        </div>
      )}

      <Link to={`/supplement/${top.slug}`} className="dash-card">
        <div className="dash-card-head">
          <div className="dash-thumb">
            {top.image ? (
              <img src={imageSrc(top.image)} alt={displayName} loading="lazy" />
            ) : (
              <span>{getCategoryEmoji(cat?.icon)}</span>
            )}
          </div>
          <div className="dash-meta">
            <span className="dash-brand">{brandName}</span>
            <strong>{shortenName(displayName, 30)}</strong>
            {cat && (
              <span className="badge badge-primary" style={{ marginTop: 4 }}>
                {getCategoryEmoji(cat.icon)} {cat.name}
              </span>
            )}
          </div>
          <div className="dash-verified" title="Verified across labs">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2 4 6v6c0 5 3.5 9.5 8 10 4.5-.5 8-5 8-10V6l-8-4z"/>
              <path d="m9 12 2 2 4-4"/>
            </svg>
          </div>
        </div>

        <div className="dash-score-row">
          <div className="dash-ring">
            <ScoreRing score={score} size={104} stroke={9} />
          </div>
          <div className="dash-score-text">
            <span className="muted">HealthMatrix Score</span>
            <strong style={{ color: getScoreColor(score) }}>{getScoreGrade(score)}</strong>
            <span className="muted">across {reviews || ratings.length} independent labs</span>
          </div>
        </div>

        {ratings.length > 0 && (
          <div className="dash-bars">
            {ratings.map((r, i) => {
              const norm = r.normalized_score
              const srcName = r.source?.name || r.source?.slug || 'Source'
              const srcColor = r.source?.color || '#0F766E'
              return (
                <div key={i} className="dash-bar">
                  <div className="dash-bar-head">
                    <span className="dash-bar-dot" style={{ background: srcColor }}></span>
                    <span>{srcName}</span>
                    <strong style={{ color: getScoreColor(norm), marginLeft: 'auto' }}>{Math.round(norm || 0)}</strong>
                  </div>
                  <div className="dash-bar-track">
                    <div
                      className="dash-bar-fill"
                      style={{ width: `${norm || 0}%`, background: getScoreColor(norm), transitionDelay: `${i * 100}ms` }}
                    ></div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div className="dash-foot">
          <span className="muted">Latest verified results</span>
          <span className="dash-cta">View full report →</span>
        </div>
      </Link>

      {next.length > 0 && (
        <div className="dash-stack">
          {next.map((s) => {
            const sName = cleanProductName(s.name, s.brand?.name || s.brand || '')
            return (
              <Link key={s.slug} to={`/supplement/${s.slug}`} className="dash-stack-item">
                <ScoreRing score={s.aggregate_score} size={44} stroke={4} />
                <span
                  className="dash-stack-grade"
                  style={{ color: getScoreColor(s.aggregate_score) }}
                >
                  {getScoreGrade(s.aggregate_score)}
                </span>
                <div className="dash-stack-text">
                  <strong>{shortenName(sName, 28)}</strong>
                  <span>{s.brand?.name || s.brand}</span>
                </div>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="dash-stack-arrow">
                  <path d="m9 18 6-6-6-6"/>
                </svg>
              </Link>
            )
          })}
        </div>
      )}

      <div className="dash-blob dash-blob-1" aria-hidden="true"></div>
      <div className="dash-blob dash-blob-2" aria-hidden="true"></div>
    </div>
  )
}
