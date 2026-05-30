import { getScoreColor, getScoreGrade, formatScore } from '../utils/format.js'
import './ScoreBadge.css'

export default function ScoreBadge({ score, reviewCount, size = 'md' }) {
  const color = getScoreColor(score)
  const grade = getScoreGrade(score)

  if (score == null) {
    return (
      <div className={`score-badge size-${size}`}>
        <div className="score-empty">Not yet rated</div>
      </div>
    )
  }

  return (
    <div className={`score-badge size-${size}`}>
      <div className="score-circle" style={{ '--score-color': color }}>
        <span className="score-grade">{grade}</span>
      </div>
      <div className="score-text">
        <div className="score-value">{formatScore(score)} <span className="score-max">/100</span></div>
        {reviewCount != null && (
          <div className="score-reviews">
            {reviewCount} {reviewCount === 1 ? 'source' : 'sources'}
          </div>
        )}
      </div>
    </div>
  )
}
