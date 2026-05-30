import { useEffect } from 'react'

export default function Modal({ open, title, onClose, children, footer, wide }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="admin-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div className={`admin-modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true">
        <div className="admin-modal-head">
          <h3>{title}</h3>
          <button className="admin-btn ghost sm" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="admin-modal-body">{children}</div>
        {footer && <div className="admin-modal-foot">{footer}</div>}
      </div>
    </div>
  )
}
