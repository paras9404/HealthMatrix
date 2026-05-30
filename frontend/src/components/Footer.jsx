import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { sourcesApi } from '../services/api.js'
import './Footer.css'

export default function Footer() {
  const [sources, setSources] = useState([])

  useEffect(() => {
    sourcesApi.list({ counts: true })
      .then((s) => setSources(s.items || []))
      .catch(() => {})
  }, [])

  const activeSources = sources.filter((s) => (s.supplement_count ?? 0) > 0)
  const labCount = activeSources.length

  return (
    <footer className="footer">
      <div className="footer-inner container">
        <Link to="/" className="footer-logo" aria-label="HealthMatrix home">
          <span className="logo-mark">
            <svg viewBox="0 0 32 32" width="22" height="22" fill="none">
              <rect width="32" height="32" rx="9" fill="currentColor"/>
              <path d="M10 9v14M22 9v14M10 16h12" stroke="#fff" strokeWidth="3" strokeLinecap="round"/>
            </svg>
          </span>
          <span>HealthMatrix</span>
        </Link>

        <p className="footer-tagline">
          One score. {labCount > 0 ? `${labCount} labs.` : 'Trusted labs.'} <em>Zero guesswork.</em>
        </p>

        <nav className="footer-links" aria-label="Footer">
          <Link to="/browse">Browse</Link>
          <Link to="/compare">Compare</Link>
          <Link to="/about">About</Link>
          <Link to="/about#methodology">Methodology</Link>
          <Link to="/about#disclaimer">Disclaimer</Link>
        </nav>
      </div>

      <div className="footer-bot container">
        <span>© {new Date().getFullYear()} HealthMatrix · Not medical advice</span>
        {activeSources.length > 0 && (
          <span className="footer-credit">
            Data from{' '}
            {activeSources.map((s, i) => (
              <span key={s.slug}>
                <a href={s.website_url} target="_blank" rel="noopener noreferrer">{s.name}</a>
                {i < activeSources.length - 2 ? ', ' : i === activeSources.length - 2 ? ' & ' : ''}
              </span>
            ))}
          </span>
        )}
      </div>
    </footer>
  )
}
