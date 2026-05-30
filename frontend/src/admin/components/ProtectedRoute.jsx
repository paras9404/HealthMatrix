import { Navigate, useLocation } from 'react-router-dom'
import { useAdminAuth } from '../AdminAuth.jsx'

export default function ProtectedRoute({ children, requireRole }) {
  const { user, loading, can } = useAdminAuth()
  const location = useLocation()

  if (loading) {
    return <div className="admin-loading">Loading…</div>
  }
  if (!user) {
    return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />
  }
  if (requireRole === 'superadmin' && !can.manageUsers) {
    return <ForbiddenScreen />
  }
  if (requireRole === 'editor' && !can.write) {
    return <ForbiddenScreen />
  }
  return children
}

function ForbiddenScreen() {
  return (
    <div className="admin-empty">
      <div className="ico">🔒</div>
      <h3>Access denied</h3>
      <p className="text-secondary">You don't have permission to view this page.</p>
    </div>
  )
}
