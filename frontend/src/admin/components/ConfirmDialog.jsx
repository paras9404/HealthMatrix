import Modal from './Modal.jsx'

export default function ConfirmDialog({ open, title, message, onCancel, onConfirm, confirmLabel = 'Delete', danger = true, loading = false }) {
  return (
    <Modal
      open={open}
      title={title || 'Are you sure?'}
      onClose={loading ? undefined : onCancel}
      footer={
        <>
          <button className="admin-btn secondary" onClick={onCancel} disabled={loading}>Cancel</button>
          <button
            className={`admin-btn ${danger ? 'danger' : ''}`}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      <p style={{ color: 'var(--color-text-secondary)' }}>{message}</p>
    </Modal>
  )
}
