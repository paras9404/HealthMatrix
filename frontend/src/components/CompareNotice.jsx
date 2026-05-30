import { useCompare } from '../hooks/useCompare.jsx'
import './CompareNotice.css'

export default function CompareNotice() {
  const { notice, dismissNotice } = useCompare()
  if (!notice) return null
  return (
    <div className="compare-notice" role="status" aria-live="polite">
      <span className="compare-notice-msg">{notice.message}</span>
      <button
        type="button"
        className="compare-notice-close"
        onClick={dismissNotice}
        aria-label="Dismiss"
      >
        ×
      </button>
    </div>
  )
}
