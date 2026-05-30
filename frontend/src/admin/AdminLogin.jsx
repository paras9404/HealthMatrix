import { useEffect, useState } from 'react'
import { useNavigate, Navigate, useLocation } from 'react-router-dom'
import { useAdminAuth } from './AdminAuth.jsx'

export default function AdminLogin() {
  const { user, login, loading } = useAdminAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const redirectTo = location.state?.from || '/admin'

  // body class for global Navbar/Footer hiding (defined in admin.css)
  useEffect(() => {
    document.body.classList.add('admin-mode')
    return () => document.body.classList.remove('admin-mode')
  }, [])

  if (loading) return null
  if (user) return <Navigate to={redirectTo} replace />

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(username.trim(), password)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err.userMessage || err.response?.data?.message || 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="admin-login-shell">
      <div className="admin-login-card">
        <div className="admin-login-brand">
          <span className="mark">
            <svg viewBox="0 0 32 32" width="20" height="20" fill="none">
              <rect width="32" height="32" rx="8" fill="currentColor"/>
              <path d="M10 9v14M22 9v14M10 16h12" stroke="#fff" strokeWidth="3" strokeLinecap="round"/>
            </svg>
          </span>
          HealthMatrix
        </div>
        <h1>Admin Sign-in</h1>
        <p className="sub">Authorized personnel only.</p>

        {error && <div className="admin-error-banner">{error}</div>}

        <form onSubmit={onSubmit} autoComplete="off">
          <div className="admin-form-group">
            <label htmlFor="admin-username">Username</label>
            <input
              id="admin-username"
              className="admin-input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </div>
          <div className="admin-form-group">
            <label htmlFor="admin-password">Password</label>
            <input
              id="admin-password"
              className="admin-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <button type="submit" className="admin-btn block" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
