export function CardSkeleton() {
  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div className="skeleton" style={{ aspectRatio: '4/3', borderRadius: 0 }} />
      <div style={{ padding: 'var(--space-5)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <div className="skeleton" style={{ height: 12, width: '40%' }} />
        <div className="skeleton" style={{ height: 18 }} />
        <div className="skeleton" style={{ height: 18, width: '70%' }} />
        <div className="skeleton" style={{ height: 36, marginTop: 'var(--space-2)' }} />
      </div>
    </div>
  )
}

export function Spinner() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-12)' }}>
      <div className="spinner" />
      <style>{`
        .spinner {
          width: 36px; height: 36px;
          border: 3px solid var(--color-border);
          border-top-color: var(--color-primary);
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div style={{ textAlign: 'center', padding: 'var(--space-12)' }}>
      <div style={{ fontSize: '3rem', marginBottom: 'var(--space-4)' }}>⚠️</div>
      <h3>Something went wrong</h3>
      <p className="text-secondary" style={{ marginTop: 'var(--space-2)' }}>{message || 'Please try again.'}</p>
      {onRetry && <button onClick={onRetry} className="btn btn-primary" style={{ marginTop: 'var(--space-4)' }}>Try again</button>}
    </div>
  )
}

export function EmptyState({ title, description, action }) {
  return (
    <div style={{ textAlign: 'center', padding: 'var(--space-16) var(--space-6)' }}>
      <div style={{ fontSize: '3rem', marginBottom: 'var(--space-4)' }}>🔍</div>
      <h3>{title || 'Nothing here yet'}</h3>
      {description && <p className="text-secondary" style={{ marginTop: 'var(--space-2)', maxWidth: 460, margin: 'var(--space-2) auto 0' }}>{description}</p>}
      {action && <div style={{ marginTop: 'var(--space-6)' }}>{action}</div>}
    </div>
  )
}
