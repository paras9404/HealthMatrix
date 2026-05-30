import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { authApi, getToken, setToken } from './services/adminApi.js'

const AdminAuthContext = createContext(null)

export function AdminAuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // Hydrate from token on mount.
  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      const t = getToken()
      if (!t) { setLoading(false); return }
      try {
        const me = await authApi.me()
        if (!cancelled) setUser(me)
      } catch (e) {
        if (!cancelled) { setToken(null); setUser(null) }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    hydrate()
    return () => { cancelled = true }
  }, [])

  const login = useCallback(async (username, password) => {
    const data = await authApi.login(username, password)
    setToken(data.token)
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(async () => {
    try { await authApi.logout() } catch { /* token might be invalid — proceed */ }
    setToken(null)
    setUser(null)
  }, [])

  const refreshUser = useCallback(async () => {
    try {
      const me = await authApi.me()
      setUser(me)
      return me
    } catch {
      return null
    }
  }, [])

  // Role helpers — `user.role` is one of: readonly | editor | superadmin.
  const role = user?.role || null
  const can = {
    read: !!user,
    write: !!user && (role === 'editor' || role === 'superadmin'),
    delete: role === 'superadmin',
    manageUsers: role === 'superadmin',
    viewAudit: role === 'superadmin',
  }

  return (
    <AdminAuthContext.Provider value={{ user, role, can, loading, login, logout, refreshUser }}>
      {children}
    </AdminAuthContext.Provider>
  )
}

export function useAdminAuth() {
  const ctx = useContext(AdminAuthContext)
  if (!ctx) throw new Error('useAdminAuth must be used within AdminAuthProvider')
  return ctx
}
