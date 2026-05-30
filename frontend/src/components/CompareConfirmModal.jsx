import { useEffect, useRef } from 'react'
import { useCompare } from '../hooks/useCompare.jsx'
import { cleanProductName } from '../utils/format.js'
import './CompareConfirmModal.css'

export default function CompareConfirmModal() {
  const { pendingSwitch, confirmSwitch, cancelSwitch } = useCompare()
  const cancelBtnRef = useRef(null)

  useEffect(() => {
    if (!pendingSwitch) return
    const onKey = (e) => { if (e.key === 'Escape') cancelSwitch() }
    document.addEventListener('keydown', onKey)
    cancelBtnRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [pendingSwitch, cancelSwitch])

  if (!pendingSwitch) return null

  const { newItem, fromCategory, toCategory, existingCount } = pendingSwitch
  const newName = cleanProductName(newItem.name, newItem.brand)
  const fromName = fromCategory?.name || 'uncategorized'
  const toName = toCategory?.name || 'uncategorized'

  return (
    <div
      className="cmp-modal-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) cancelSwitch() }}
      role="presentation"
    >
      <div className="cmp-modal" role="dialog" aria-modal="true" aria-labelledby="cmp-modal-title">
        <div className="cmp-modal-head">
          <h3 id="cmp-modal-title">Start a new comparison?</h3>
          <button
            type="button"
            className="cmp-modal-close"
            onClick={cancelSwitch}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="cmp-modal-body">
          <p>
            Your comparison currently has <strong>{existingCount}</strong>{' '}
            <strong>{fromName}</strong> {existingCount === 1 ? 'product' : 'products'}.
          </p>
          <p>
            Adding <strong>{newName}</strong> will clear it and start a fresh{' '}
            <strong>{toName}</strong> comparison.
          </p>
          <p className="muted">Comparisons are limited to one category at a time.</p>
        </div>
        <div className="cmp-modal-foot">
          <button
            ref={cancelBtnRef}
            type="button"
            className="btn btn-ghost"
            onClick={cancelSwitch}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={confirmSwitch}
          >
            Clear &amp; add
          </button>
        </div>
      </div>
    </div>
  )
}
