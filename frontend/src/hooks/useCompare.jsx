import { createContext, useContext, useEffect, useMemo, useRef, useState, useCallback } from 'react'

const CompareContext = createContext(null)
const STORAGE_KEY = 'healthmatrix.compare'
const MAX_ITEMS = 4
const NOTICE_TIMEOUT_MS = 4000

function loadInitial() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) return []
    const parsed = JSON.parse(saved)
    if (!Array.isArray(parsed)) return []
    // Items written before category-locking shipped don't have `category`; clearing
    // them avoids inheriting an undefined lock that no new item could satisfy.
    if (parsed.some((p) => !p || typeof p !== 'object' || !('category' in p))) return []
    return parsed
  } catch {
    return []
  }
}

function shapeItem(s) {
  return {
    slug: s.slug,
    name: s.name,
    brand: s.brand,
    image: s.image,
    category: s.category ?? null,
  }
}

export function CompareProvider({ children }) {
  const [items, setItems] = useState(loadInitial)
  const [notice, setNotice] = useState(null)
  const [pendingSwitch, setPendingSwitch] = useState(null)
  const noticeTimerRef = useRef(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  }, [items])

  useEffect(() => () => {
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current)
  }, [])

  const dismissNotice = useCallback(() => {
    if (noticeTimerRef.current) {
      clearTimeout(noticeTimerRef.current)
      noticeTimerRef.current = null
    }
    setNotice(null)
  }, [])

  const showNotice = useCallback((n) => {
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current)
    setNotice(n)
    noticeTimerRef.current = setTimeout(() => {
      setNotice(null)
      noticeTimerRef.current = null
    }, NOTICE_TIMEOUT_MS)
  }, [])

  const lockedCategory = items[0]?.category ?? null

  const canAdd = useCallback((s) => {
    if (!s) return 'invalid'
    if (items.find((p) => p.slug === s.slug)) return 'duplicate'
    if (items.length === 0) return null
    const newCatId = s.category?.id ?? null
    const lockedCatId = lockedCategory?.id ?? null
    // Category mismatch is *resolvable* via confirm-switch — don't disable; we'll prompt at click time.
    if (newCatId !== lockedCatId) return 'category_mismatch'
    if (items.length >= MAX_ITEMS) return 'full'
    return null
  }, [items, lockedCategory])

  const add = useCallback((s) => {
    if (!s) return { ok: false, reason: 'invalid' }
    if (items.find((p) => p.slug === s.slug)) {
      return { ok: false, reason: 'duplicate' }
    }
    const newCatId = s.category?.id ?? null
    const lockedCatId = lockedCategory?.id ?? null
    const isMismatch = items.length > 0 && newCatId !== lockedCatId
    if (isMismatch) {
      setPendingSwitch({
        newItem: shapeItem(s),
        fromCategory: lockedCategory,
        toCategory: s.category ?? null,
        existingCount: items.length,
      })
      return { ok: false, reason: 'category_mismatch', pending: true }
    }
    if (items.length >= MAX_ITEMS) {
      showNotice({
        kind: 'full',
        message: `Compare is full (${MAX_ITEMS} max). Remove one to add another.`,
      })
      return { ok: false, reason: 'full' }
    }
    setItems((prev) => {
      if (prev.find((p) => p.slug === s.slug)) return prev
      if (prev.length >= MAX_ITEMS) return prev
      const lockedCatIdNow = prev[0]?.category?.id ?? null
      if (prev.length > 0 && (s.category?.id ?? null) !== lockedCatIdNow) return prev
      return [...prev, shapeItem(s)]
    })
    return { ok: true }
  }, [items, lockedCategory, showNotice])

  const confirmSwitch = useCallback(() => {
    setPendingSwitch((p) => {
      if (!p) return null
      // Replace the cart entirely with the new item — fresh start in the new category.
      setItems([p.newItem])
      dismissNotice()
      return null
    })
  }, [dismissNotice])

  const cancelSwitch = useCallback(() => {
    setPendingSwitch(null)
  }, [])

  const remove = useCallback((slug) => {
    setItems((prev) => prev.filter((p) => p.slug !== slug))
  }, [])

  const clear = useCallback(() => {
    setItems([])
    dismissNotice()
    setPendingSwitch(null)
  }, [dismissNotice])

  const has = useCallback((slug) => items.some((i) => i.slug === slug), [items])

  const value = useMemo(() => ({
    items,
    add,
    remove,
    clear,
    has,
    canAdd,
    lockedCategory,
    notice,
    dismissNotice,
    pendingSwitch,
    confirmSwitch,
    cancelSwitch,
    max: MAX_ITEMS,
  }), [items, add, remove, clear, has, canAdd, lockedCategory, notice, dismissNotice, pendingSwitch, confirmSwitch, cancelSwitch])

  return (
    <CompareContext.Provider value={value}>
      {children}
    </CompareContext.Provider>
  )
}

export function useCompare() {
  const ctx = useContext(CompareContext)
  if (!ctx) throw new Error('useCompare must be used within CompareProvider')
  return ctx
}
