import { Routes, Route } from 'react-router-dom'
import { AdminAuthProvider } from './AdminAuth.jsx'
import AdminLogin from './AdminLogin.jsx'
import AdminLayout from './AdminLayout.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Supplements from './pages/Supplements.jsx'
import Brands from './pages/Brands.jsx'
import Categories from './pages/Categories.jsx'
import Sources from './pages/Sources.jsx'
import Ratings from './pages/Ratings.jsx'
import ImageValidation from './pages/ImageValidation.jsx'
import SourceImport from './pages/SourceImport.jsx'
import ProductGroups from './pages/ProductGroups.jsx'
import Users from './pages/Users.jsx'
import AuditLog from './pages/AuditLog.jsx'
import Analytics from './pages/Analytics.jsx'
import './admin.css'

export default function AdminApp() {
  return (
    <AdminAuthProvider>
      <div className="admin-root">
        <Routes>
          <Route path="login" element={<AdminLogin />} />
          <Route element={
            <ProtectedRoute>
              <AdminLayout />
            </ProtectedRoute>
          }>
            <Route index element={<Dashboard />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="supplements" element={<Supplements />} />
            <Route path="product-groups" element={<ProductGroups />} />
            <Route path="brands" element={<Brands />} />
            <Route path="categories" element={<Categories />} />
            <Route path="sources" element={<Sources />} />
            <Route path="ratings" element={<Ratings />} />
            <Route path="image-validation" element={<ImageValidation />} />
            <Route path="source-import" element={<SourceImport />} />
            <Route path="users" element={
              <ProtectedRoute requireRole="superadmin"><Users /></ProtectedRoute>
            } />
            <Route path="audit" element={
              <ProtectedRoute requireRole="superadmin"><AuditLog /></ProtectedRoute>
            } />
          </Route>
        </Routes>
      </div>
    </AdminAuthProvider>
  )
}
