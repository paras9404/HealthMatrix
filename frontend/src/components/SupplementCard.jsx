import { Link } from 'react-router-dom'
import ScoreRing from './ScoreRing.jsx'
import { useCompare } from '../hooks/useCompare.jsx'
import { getCategoryEmoji, getScoreColor, getScoreGrade, cleanProductName, imageSrc } from '../utils/format.js'
import './SupplementCard.css'

export default function SupplementCard({ supplement, compact = false }) {
  const { add, remove, has, canAdd, max } = useCompare()
  const inCompare = has(supplement.slug)
  const blockReason = inCompare ? null : canAdd(supplement)
  // Only `full` is a hard block. Category mismatch is resolved via the confirm-switch dialog at click time.
  const compareDisabled = blockReason === 'full'
  const brandName = supplement.brand?.name || supplement.brand || ''
  const displayName = cleanProductName(supplement.name, brandName)
  const score = supplement.aggregate_score
  const reviewCount = supplement.review_count

  let compareTitle
  if (inCompare) compareTitle = 'Remove from compare'
  else if (compareDisabled) compareTitle = `Compare full (${max} max)`
  else compareTitle = 'Add to compare'

  const toggleCompare = (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (inCompare) remove(supplement.slug)
    else add({ ...supplement, brand: brandName, image: supplement.image })
  }

  return (
    <Link to={`/supplement/${supplement.slug}`} className={`scard ${compact ? 'scard-compact' : ''}`}>
      <div className="scard-img">
        {supplement.image ? (
          <img src={imageSrc(supplement.image)} alt={`${brandName} ${displayName}`.trim()} loading="lazy" />
        ) : (
          <span className="scard-img-icon">{getCategoryEmoji(supplement.category?.icon)}</span>
        )}
        {supplement.is_featured && <span className="scard-tag">Featured</span>}
        <button
          type="button"
          className={`scard-compare ${inCompare ? 'active' : ''}`}
          onClick={toggleCompare}
          disabled={compareDisabled}
          title={compareTitle}
          aria-label="Toggle compare"
        >
          {inCompare ? '✓' : '+'}
        </button>
      </div>
      <div className="scard-body">
        <div className="scard-brandline">
          {brandName && <span className="scard-brand">{brandName}</span>}
          {supplement.price && <span className="scard-price">{supplement.price}</span>}
        </div>
        <h3 className="scard-name" title={displayName}>{displayName}</h3>
        <div className="scard-meta">
          {supplement.category && (
            <span className="badge badge-primary">
              {getCategoryEmoji(supplement.category.icon)} {supplement.category.name}
            </span>
          )}
          {supplement.size && <span className="scard-size">{supplement.size}</span>}
        </div>
        <div className="scard-foot">
          <ScoreRing score={score} size={compact ? 38 : 44} stroke={compact ? 3.5 : 4} />
          <div className="scard-foot-text">
            <strong style={{ color: getScoreColor(score) }}>{getScoreGrade(score)}</strong>
            {reviewCount != null && (
              <span className="muted">{reviewCount} {reviewCount === 1 ? 'lab' : 'labs'}</span>
            )}
          </div>
        </div>
      </div>
    </Link>
  )
}
