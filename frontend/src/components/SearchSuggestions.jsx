import { getCategoryEmoji, getScoreColor, cleanProductName, imageSrc } from '../utils/format.js'
import './SearchSuggestions.css'

// The backend escapes supplement names before wrapping matches in <mark>, so
// the only HTML in the highlighted strings should come from us. Strip
// everything other than <mark>/</mark> defensively before injecting — XSS
// belt-and-braces.
function sanitizeHighlight(html) {
  if (!html) return ''
  return String(html).replace(/<(?!\/?mark>)[^>]*>/gi, '')
}

export default function SearchSuggestions({
  suggestions,
  activeIdx,
  query,
  onSelect,
  onSeeAll,
  listId = 'suggest-list',
  className = '',
}) {
  if (!suggestions || suggestions.length === 0) return null
  return (
    <div className={`suggest ${className}`} id={listId} role="listbox">
      {suggestions.map((s, idx) => {
        const brandName = s.brand?.name || s.brand || ''
        const display = cleanProductName(s.name, brandName)
        const nameHtml = s.name_highlighted ? sanitizeHighlight(s.name_highlighted) : null
        const brandHtml = s.brand_highlighted ? sanitizeHighlight(s.brand_highlighted) : null
        return (
          <button
            key={s.slug}
            type="button"
            role="option"
            aria-selected={idx === activeIdx}
            className={`suggest-item ${idx === activeIdx ? 'suggest-item-active' : ''}`}
            onClick={() => onSelect(s)}
          >
            {s.image ? (
              <img className="suggest-thumb" src={imageSrc(s.image)} alt="" loading="lazy" />
            ) : (
              <span className="suggest-icon">{getCategoryEmoji(s.category?.icon)}</span>
            )}
            <div className="suggest-text">
              {nameHtml ? (
                <strong dangerouslySetInnerHTML={{ __html: nameHtml }} />
              ) : (
                <strong>{display}</strong>
              )}
              <span>
                {brandHtml ? (
                  <span dangerouslySetInnerHTML={{ __html: brandHtml }} />
                ) : brandName}
                {s.category?.name ? ` · ${s.category.name}` : ''}
              </span>
            </div>
            {s.aggregate_score != null && (
              <span className="suggest-score" style={{ color: getScoreColor(s.aggregate_score) }}>
                {Math.round(s.aggregate_score)}
              </span>
            )}
          </button>
        )
      })}
      {onSeeAll && (
        <button type="button" className="suggest-all" onClick={onSeeAll}>
          See all results for "{query}" →
        </button>
      )}
    </div>
  )
}
