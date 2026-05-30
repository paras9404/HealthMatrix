import { Link } from 'react-router-dom'
import Seo from '../components/Seo.jsx'

export default function NotFound() {
  return (
    <div className="container fade-in" style={{ padding: 'var(--space-20) 0', textAlign: 'center' }}>
      <Seo
        title="Page not found"
        description="The page you're looking for doesn't exist or has been moved."
        noindex
      />
      <div style={{ fontSize: '6rem', fontFamily: 'var(--font-display)', fontWeight: 800, color: 'var(--color-primary)', lineHeight: 1 }}>404</div>
      <h1 style={{ marginTop: 'var(--space-4)' }}>Page not found</h1>
      <p className="text-secondary" style={{ marginTop: 'var(--space-3)', maxWidth: 480, marginLeft: 'auto', marginRight: 'auto' }}>
        The page you're looking for doesn't exist or has been moved.
      </p>
      <div style={{ marginTop: 'var(--space-6)', display: 'flex', gap: 'var(--space-3)', justifyContent: 'center' }}>
        <Link to="/" className="btn btn-primary">Back to home</Link>
        <Link to="/browse" className="btn btn-secondary">Browse supplements</Link>
      </div>
    </div>
  )
}
