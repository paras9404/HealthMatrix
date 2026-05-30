import { Link, NavLink, useLocation } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { useCompare } from '../hooks/useCompare.jsx'
import { useSearchSuggestions } from '../hooks/useSearchSuggestions.jsx'
import SearchSuggestions from './SearchSuggestions.jsx'
import './Navbar.css'

export default function Navbar() {
  const [open, setOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const location = useLocation()
  const { items: compareItems } = useCompare()

  const desktop = useSearchSuggestions()
  const mobile = useSearchSuggestions()
  const mobileInputRef = useRef(null)
  const mobilePanelRef = useRef(null)
  const searchToggleRef = useRef(null)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Close menus on every navigation — including same-pathname cases like
  // submitting search on /browse going to /browse?q=foo (only the search
  // string changes), or paginating where only the query string mutates.
  useEffect(() => {
    setOpen(false)
    setMobileSearchOpen(false)
    desktop.setShowSuggest(false)
    mobile.setShowSuggest(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.search])

  useEffect(() => {
    if (mobileSearchOpen) mobileInputRef.current?.focus()
  }, [mobileSearchOpen])

  // Tap outside the mobile panel (and outside the toggle that opened it) to
  // dismiss. Without this, the only way to close without searching is to tap
  // the same icon again — discoverable, but a tap-anywhere is cheaper.
  useEffect(() => {
    if (!mobileSearchOpen) return
    const onClick = (e) => {
      const insidePanel = mobilePanelRef.current?.contains(e.target)
      const insideToggle = searchToggleRef.current?.contains(e.target)
      if (!insidePanel && !insideToggle) setMobileSearchOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('touchstart', onClick, { passive: true })
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('touchstart', onClick)
    }
  }, [mobileSearchOpen])

  return (
    <header className={`navbar ${scrolled ? 'navbar-scrolled' : ''}`}>
      <div className="container navbar-inner">
        <Link to="/" className="logo">
          <span className="logo-mark">
            <svg viewBox="0 0 32 32" width="22" height="22" fill="none">
              <rect width="32" height="32" rx="9" fill="currentColor"/>
              <path d="M10 9v14M22 9v14M10 16h12" stroke="#fff" strokeWidth="3" strokeLinecap="round"/>
            </svg>
          </span>
          <span className="logo-text">HealthMatrix</span>
        </Link>

        <div className="navbar-search" ref={desktop.containerRef}>
          <form onSubmit={desktop.submit} role="search">
            <SearchIcon />
            <input
              type="search"
              placeholder="Search supplements, brands, ingredients…"
              value={desktop.query}
              onChange={desktop.onChange}
              onFocus={desktop.onFocus}
              onKeyDown={desktop.onKeyDown}
              aria-autocomplete="list"
              aria-expanded={desktop.showSuggest && desktop.suggestions.length > 0}
              aria-controls="navbar-suggest-list"
            />
            {desktop.query && (
              <button type="button" className="search-clear" onClick={desktop.clear} aria-label="Clear search">×</button>
            )}
          </form>
          {desktop.showSuggest && (
            <SearchSuggestions
              suggestions={desktop.suggestions}
              activeIdx={desktop.activeIdx}
              query={desktop.query}
              onSelect={desktop.goToSuggestion}
              onSeeAll={desktop.submit}
              listId="navbar-suggest-list"
            />
          )}
        </div>

        <nav className={`navbar-links ${open ? 'open' : ''}`}>
          <NavLink to="/browse" className={({ isActive }) => isActive ? 'active' : ''}>Browse</NavLink>
          <NavLink to="/compare" className={({ isActive }) => isActive ? 'active' : ''}>
            Compare
            <span className="nav-beta" title="Beta — under active development">Beta</span>
            {compareItems.length > 0 && <span className="nav-pill">{compareItems.length}</span>}
          </NavLink>
          <NavLink to="/about" className={({ isActive }) => isActive ? 'active' : ''}>About</NavLink>
        </nav>

        {/* Mobile-only search trigger — surfaces search outside the burger menu
         * so it's always one tap away on every page. Opens an expanded search
         * overlay below the navbar. */}
        <button
          ref={searchToggleRef}
          className={`navbar-search-toggle ${mobileSearchOpen ? 'is-open' : ''}`}
          aria-label={mobileSearchOpen ? 'Close search' : 'Open search'}
          aria-expanded={mobileSearchOpen}
          onClick={() => {
            setMobileSearchOpen((v) => !v)
            setOpen(false)
          }}
        >
          <SearchIcon />
        </button>

        <button className="navbar-toggle" aria-label="Toggle menu" onClick={() => { setOpen((o) => !o); setMobileSearchOpen(false) }}>
          {open ? <CloseIcon /> : <MenuIcon />}
        </button>
      </div>

      {mobileSearchOpen && (
        <div className="navbar-mobile-search-panel" ref={mobilePanelRef}>
          <div className="navbar-mobile-search-wrap" ref={mobile.containerRef}>
            <form className="navbar-mobile-search" onSubmit={mobile.submit} role="search">
              <SearchIcon />
              <input
                ref={mobileInputRef}
                type="search"
                placeholder="Search supplements, brands, ingredients…"
                value={mobile.query}
                onChange={mobile.onChange}
                onFocus={mobile.onFocus}
                onKeyDown={mobile.onKeyDown}
                aria-autocomplete="list"
                aria-expanded={mobile.showSuggest && mobile.suggestions.length > 0}
                aria-controls="navbar-mobile-suggest-list"
              />
              {mobile.query && (
                <button type="button" className="search-clear" onClick={mobile.clear} aria-label="Clear search">×</button>
              )}
            </form>
            {mobile.showSuggest && (
              <SearchSuggestions
                suggestions={mobile.suggestions}
                activeIdx={mobile.activeIdx}
                query={mobile.query}
                onSelect={mobile.goToSuggestion}
                onSeeAll={mobile.submit}
                listId="navbar-mobile-suggest-list"
                className="suggest-mobile"
              />
            )}
          </div>
        </div>
      )}
    </header>
  )
}

function SearchIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"/>
      <path d="m21 21-4.3-4.3"/>
    </svg>
  )
}
function MenuIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
}
function CloseIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
}
