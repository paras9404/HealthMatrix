import { useEffect } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAdminAuth } from './AdminAuth.jsx'

const NAV = [
  { to: '/admin', label: 'Dashboard', icon: '◧', end: true },
  { to: '/admin/analytics', label: 'Analytics', icon: '📊' },
  { to: '/admin/supplements', label: 'Supplements', icon: '💊' },
  { to: '/admin/product-groups', label: 'Product groups', icon: '⊞' },
  { to: '/admin/brands', label: 'Brands', icon: '⌬' },
  { to: '/admin/categories', label: 'Categories', icon: '◫' },
  { to: '/admin/sources', label: 'Sources', icon: '⚙' },
  { to: '/admin/ratings', label: 'Ratings', icon: '★' },
  { to: '/admin/source-import', label: 'Add from source', icon: '➕' },
  { to: '/admin/image-validation', label: 'Image validation', icon: '🖼' },
]

const ADMIN_NAV = [
  { to: '/admin/users', label: 'Admin users', icon: '👤', superadmin: true },
  { to: '/admin/audit', label: 'Audit log', icon: '⚿', superadmin: true },
]

export default function AdminLayout() {
  const { user, logout, can } = useAdminAuth()
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    document.body.classList.add('admin-mode')
    return () => document.body.classList.remove('admin-mode')
  }, [])

  // Determine current page title from path.
  const allNav = [...NAV, ...ADMIN_NAV]
  const currentNav = allNav.find((n) => n.end ? location.pathname === n.to : location.pathname.startsWith(n.to))
  const pageTitle = currentNav?.label || 'Admin'

  const initials = (user?.username || '?').slice(0, 2).toUpperCase()

  async function onLogout() {
    await logout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-sidebar-brand">
          <span className="mark">
            <svg viewBox="0 0 32 32" width="18" height="18" fill="none">
              <rect width="32" height="32" rx="8" fill="currentColor"/>
              <path d="M10 9v14M22 9v14M10 16h12" stroke="#fff" strokeWidth="3" strokeLinecap="round"/>
            </svg>
          </span>
          <div>
            HealthMatrix
            <span className="sub">Admin Panel</span>
          </div>
        </div>

        <nav>
          <div className="section-label">Manage</div>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `admin-nav-link ${isActive ? 'active' : ''}`}
            >
              <span className="icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}

          {can.viewAudit && (
            <>
              <div className="section-label">Admin</div>
              {ADMIN_NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `admin-nav-link ${isActive ? 'active' : ''}`}
                >
                  <span className="icon">{item.icon}</span>
                  {item.label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="admin-sidebar-foot">
          <div className="avatar">{initials}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="name" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {user?.username}
            </div>
            <div className="role">{user?.role}</div>
          </div>
        </div>
      </aside>

      <div className="admin-content">
        <header className="admin-topbar">
          <div className="title">{pageTitle}</div>
          <div className="actions">
            <a href="/" className="admin-btn ghost sm" title="Open public site">View site →</a>
            <button onClick={onLogout} className="admin-btn secondary sm">Sign out</button>
          </div>
        </header>
        <main className="admin-main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
