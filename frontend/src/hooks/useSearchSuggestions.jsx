import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { supplementsApi } from '../services/api.js'

// Centralizes the type-ahead behavior used by every search input on the site.
// Owns: query state, debounced suggest fetch, keyboard navigation, click-away
// dismissal. Visual variants supply their own input + dropdown markup, but
// share the state machine so behavior stays consistent.
export function useSearchSuggestions() {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [showSuggest, setShowSuggest] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const containerRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    const onClick = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setShowSuggest(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('touchstart', onClick, { passive: true })
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('touchstart', onClick)
    }
  }, [])

  // Meilisearch is fast enough that a 120ms debounce is generous; firing on the
  // very first keystroke still feels instant.
  useEffect(() => {
    const q = query.trim()
    if (!q) { setSuggestions([]); setActiveIdx(-1); return }
    const t = setTimeout(() => {
      supplementsApi.suggest(q)
        .then((res) => {
          const items = (res.items || res || []).slice(0, 6)
          setSuggestions(items)
          // Keep activeIdx at -1 by default so Enter triggers the search
          // results page rather than auto-jumping into the top product.
          setActiveIdx(-1)
        })
        .catch(() => setSuggestions([]))
    }, 120)
    return () => clearTimeout(t)
  }, [query])

  const submit = (e) => {
    if (e?.preventDefault) e.preventDefault()
    const q = query.trim()
    // An empty submit (e.g., user clicks the hero Search button with no text)
    // takes them to the full Browse page rather than doing nothing.
    navigate(q ? `/browse?q=${encodeURIComponent(q)}` : '/browse')
    setQuery('')
    setShowSuggest(false)
  }

  const goToSuggestion = (s) => {
    navigate(`/supplement/${s.slug}`)
    setQuery('')
    setShowSuggest(false)
  }

  const onKeyDown = (e) => {
    if (!showSuggest || suggestions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(suggestions.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter') {
      if (activeIdx >= 0 && activeIdx < suggestions.length) {
        e.preventDefault()
        goToSuggestion(suggestions[activeIdx])
      }
    } else if (e.key === 'Escape') {
      setShowSuggest(false)
    }
  }

  const onChange = (e) => {
    setQuery(e.target.value)
    setShowSuggest(true)
  }

  const onFocus = () => setShowSuggest(true)

  const clear = () => {
    setQuery('')
    setSuggestions([])
    setActiveIdx(-1)
  }

  return {
    query,
    setQuery,
    suggestions,
    showSuggest,
    setShowSuggest,
    activeIdx,
    containerRef,
    submit,
    goToSuggestion,
    onKeyDown,
    onChange,
    onFocus,
    clear,
  }
}
