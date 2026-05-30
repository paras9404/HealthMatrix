import { Routes, Route, useLocation } from 'react-router-dom'
import Navbar from './components/Navbar.jsx'
import Footer from './components/Footer.jsx'
import CompareTray from './components/CompareTray.jsx'
import CompareNotice from './components/CompareNotice.jsx'
import CompareConfirmModal from './components/CompareConfirmModal.jsx'
import Home from './pages/Home.jsx'
import Browse from './pages/Browse.jsx'
import SupplementDetail from './pages/SupplementDetail.jsx'
import Compare from './pages/Compare.jsx'
import About from './pages/About.jsx'
import NotFound from './pages/NotFound.jsx'
import AdminApp from './admin/AdminApp.jsx'
import { useTracker, useUnloadBeacon } from './hooks/useTracker.js'

export default function App() {
  const location = useLocation()
  const isAdmin = location.pathname.startsWith('/admin')
  // Tracker hooks are no-ops on /admin paths internally.
  useTracker()
  useUnloadBeacon()

  // Admin section runs in its own shell — no public Navbar/Footer/CompareTray.
  if (isAdmin) {
    return (
      <Routes>
        <Route path="/admin/*" element={<AdminApp />} />
      </Routes>
    )
  }

  return (
    <div className="app">
      <Navbar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/browse" element={<Browse />} />
          <Route path="/supplement/:slug" element={<SupplementDetail />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <CompareTray />
      <CompareNotice />
      <CompareConfirmModal />
      <Footer />
    </div>
  )
}
