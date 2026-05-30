import { Link, useLocation } from 'react-router-dom'
import { useCompare } from '../hooks/useCompare.jsx'
import { getCategoryEmoji, cleanProductName } from '../utils/format.js'
import './CompareTray.css'

export default function CompareTray() {
  const { items, remove, clear, lockedCategory } = useCompare()
  const location = useLocation()

  if (items.length === 0 || location.pathname === '/compare') return null

  return (
    <div className="tray">
      <div className="tray-inner">
        {lockedCategory && (
          <div className="tray-lock" title={`Compare is locked to ${lockedCategory.name}`}>
            <span className="tray-lock-icon">{getCategoryEmoji(lockedCategory.icon)}</span>
            <span className="tray-lock-text">{lockedCategory.name}</span>
          </div>
        )}
        <div className="tray-items">
          {items.map((item) => {
            const display = cleanProductName(item.name, item.brand)
            return (
              <div key={item.slug} className="tray-item">
                <span className="tray-icon">{getCategoryEmoji(item.category?.icon)}</span>
                <div>
                  <strong>{display}</strong>
                  {item.brand && <span className="muted">{item.brand}</span>}
                </div>
                <button
                  type="button"
                  onClick={() => remove(item.slug)}
                  aria-label="Remove"
                >
                  ×
                </button>
              </div>
            )
          })}
        </div>
        <div className="tray-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={clear}>Clear</button>
          <Link
            to={items.length >= 2 ? '/compare' : '#'}
            className="btn btn-primary"
            aria-disabled={items.length < 2}
            onClick={(e) => { if (items.length < 2) e.preventDefault() }}
            style={items.length < 2 ? { opacity: 0.5, pointerEvents: 'none' } : undefined}
          >
            Compare {items.length} →
          </Link>
        </div>
      </div>
    </div>
  )
}
