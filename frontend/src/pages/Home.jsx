import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supplementsApi, categoriesApi, sourcesApi, statsApi } from '../services/api.js'
import SupplementCard from '../components/SupplementCard.jsx'
import HeroDashboard from '../components/HeroDashboard.jsx'
import LabLogo from '../components/LabLogo.jsx'
import { CardSkeleton } from '../components/Loader.jsx'
import Seo from '../components/Seo.jsx'
import SearchSuggestions from '../components/SearchSuggestions.jsx'
import { useSearchSuggestions } from '../hooks/useSearchSuggestions.jsx'
import { getCategoryEmoji } from '../utils/format.js'
import { buildWebSiteJsonLd, buildOrganizationJsonLd, buildFAQJsonLd, buildWebPageJsonLd } from '../utils/seo.js'
import './Home.css'

const CATEGORY_HUES = {
  vitamins: 'teal',
  minerals: 'blue',
  protein: 'orange',
  omega: 'cyan',
  probiotics: 'green',
  herbs: 'lime',
  herbal: 'lime',
  sports: 'red',
  sleep: 'violet',
}

const QUICK_TERMS = ['Vitamin D', 'Whey Protein', 'Magnesium', 'Omega-3', 'Creatine']

// Floor to a "marketing-honest" round number so the hero stat doesn't claim
// more than we have: 421 → "400+", 593 → "500+", 87 → "80+", <10 → exact.
// Using floor (not round) guarantees we never overstate the catalogue size.
function floorRounded(n) {
  if (!n || n < 10) return n ? `${n}` : '—'
  const step = n >= 100 ? 100 : 10
  return `${Math.floor(n / step) * step}+`
}

export default function Home() {
  const [featured, setFeatured] = useState([])
  const [categories, setCategories] = useState([])
  const [sources, setSources] = useState([])
  const [stats, setStats] = useState(null)
  const [topRated, setTopRated] = useState([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const search = useSearchSuggestions()

  useEffect(() => {
    Promise.all([
      supplementsApi.featured(6),
      categoriesApi.list(),
      sourcesApi.list({ counts: true }),
      statsApi.get().catch(() => null),
      supplementsApi.list({ sort: 'top', per_page: 9 }).catch(() => ({ items: [] })),
    ])
      .then(([f, c, s, st, top]) => {
        const items = f.items || []
        setFeatured(items)
        setCategories(c.items || [])
        setSources(s.items || [])
        setStats(st)
        setTopRated(top.items || [])
        // The /featured endpoint returns lightweight product cards (no ratings).
        // The hero dashboard wants the top product's lab ratings to show real
        // lab names in the floating tickers — fetch the full detail and merge.
        if (items[0]?.slug) {
          supplementsApi.get(items[0].slug)
            .then((full) => {
              setFeatured((prev) => prev.length === 0 ? prev : [{ ...prev[0], ratings: full.ratings || [] }, ...prev.slice(1)])
            })
            .catch(() => { /* tickers fall back to none — non-fatal */ })
        }
      })
      .finally(() => setLoading(false))
  }, [])

  const onQuickSearch = (term) => navigate(`/browse?q=${encodeURIComponent(term)}`)

  const sortedCategories = useMemo(
    () =>
      [...categories].sort(
        (a, b) => (b.supplement_count || 0) - (a.supplement_count || 0),
      ),
    [categories],
  )

  const labCount = stats?.sources_with_data ?? sources.filter((s) => (s.supplement_count ?? 0) > 0).length
  const supplementCount = stats?.supplements ?? 0

  const homeDescription = labCount > 0
    ? `Compare supplement quality ratings from ${labCount} independent labs — Labdoor, ConsumerLab, NSF, USP, and more. ${supplementCount > 0 ? `${supplementCount}+ supplements rated.` : ''} One aggregate score. Zero guesswork.`
    : 'Compare supplement quality ratings from independent labs in one place. One aggregate score. Zero guesswork.'

  const labCountText = labCount > 0 ? `${labCount}` : '9'
  const homeFaq = [
    {
      question: 'What is HealthMatrix?',
      answer: `HealthMatrix is a free comparison tool that aggregates supplement quality ratings from ${labCountText} independent testing labs — including Labdoor, ConsumerLab, NSF, USP, Examine, Trustified, Informed Choice, Informed Sport, and Trustpilot — into a single 0–100 score.`,
    },
    {
      question: 'How is the HealthMatrix Score calculated?',
      answer: 'Each lab uses a different scale. We normalize every result to a 0–100 scale, give unverified sources half-weight, then average across all available sources to produce one aggregate score per product.',
    },
    {
      question: 'Does HealthMatrix test supplements?',
      answer: 'No. HealthMatrix does not perform laboratory testing. We aggregate publicly available ratings and link back to the original report from each independent lab.',
    },
    {
      question: 'Is HealthMatrix free to use?',
      answer: 'Yes. There are no paywalls, account requirements, or email gates. We earn from optional, clearly disclosed affiliate links — they never influence ratings or rankings.',
    },
    {
      question: 'Which independent labs are included?',
      answer: 'Labdoor, ConsumerLab, NSF International, USP, Examine, Trustified, Informed Choice, Informed Sport, and Trustpilot. Coverage per product depends on which labs have published a rating.',
    },
    {
      question: 'How often are ratings updated?',
      answer: 'Ratings refresh as labs publish new reports. Each supplement page shows the latest "tested on" date from the source so you can see when the underlying data was collected.',
    },
  ]

  return (
    <div className="home fade-in">
      <Seo
        title="Compare Supplement Ratings Across Trusted Labs"
        description={homeDescription}
        path="/"
        jsonLd={[
          buildWebSiteJsonLd(),
          buildOrganizationJsonLd(),
          buildWebPageJsonLd({ title: 'HealthMatrix — Compare Supplement Ratings Across Trusted Labs', description: homeDescription, path: '/' }),
          buildFAQJsonLd(homeFaq),
        ]}
      />
      {/* Hero */}
      <section className="hero">
        <div className="container hero-inner">
          <div className="hero-content">
            <span className="eyebrow">
              <span className="pulse"></span>
              {labCount > 0
                ? `Live ratings from ${labCount} ${labCount === 1 ? 'independent lab' : 'independent labs'}`
                : 'Independent supplement ratings'}
            </span>
            <h1 className="hero-title">
              Compare supplement quality from labs that <em>actually</em> test them.
            </h1>
            <p className="hero-lead">
              One score. {labCount > 0 ? `${labCount} labs.` : 'Trusted labs.'} Zero guesswork.
              Find the supplements that pass purity, potency, and safety tests.
            </p>

            <div className="hero-search-wrap" ref={search.containerRef}>
              <form className="hero-search" onSubmit={search.submit} role="search">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                <input
                  type="search"
                  placeholder="Try ‘vitamin D’, ‘creatine’, ‘Thorne’…"
                  value={search.query}
                  onChange={search.onChange}
                  onFocus={search.onFocus}
                  onKeyDown={search.onKeyDown}
                  aria-autocomplete="list"
                  aria-expanded={search.showSuggest && search.suggestions.length > 0}
                  aria-controls="hero-suggest-list"
                />
                <button type="submit" className="btn btn-primary">Search</button>
              </form>
              {search.showSuggest && (
                <SearchSuggestions
                  suggestions={search.suggestions}
                  activeIdx={search.activeIdx}
                  query={search.query}
                  onSelect={search.goToSuggestion}
                  onSeeAll={search.submit}
                  listId="hero-suggest-list"
                  className="suggest-hero"
                />
              )}
            </div>

            <div className="quick-chips">
              <span>Popular:</span>
              {QUICK_TERMS.map((t) => (
                <button key={t} type="button" className="chip" onClick={() => onQuickSearch(t)}>
                  {t}
                </button>
              ))}
            </div>

            <div className="hero-stats">
              <div>
                <strong>{floorRounded(supplementCount)}</strong>
                <span>supplements rated</span>
              </div>
              <div>
                <strong>{labCount || '—'}</strong>
                <span>{labCount === 1 ? 'trusted lab' : 'trusted labs'}</span>
              </div>
            </div>
          </div>

          <HeroDashboard featured={featured} />
        </div>
      </section>

      {/* Trust strip */}
      <section className="trust">
        <div className="container">
          <p className="trust-label">
            Aggregating ratings from {labCount > 0 ? `${labCount} ` : ''}independent testing labs
          </p>
          <div className="trust-row">
            {sources
              .filter((s) => (s.supplement_count ?? 0) > 0)
              .map((s) => (
                <LabLogo key={s.slug} source={s} />
              ))}
          </div>
        </div>
      </section>

      {/* Categories */}
      <section className="section">
        <div className="container">
          <div className="section-head">
            <div>
              <h2>Browse by category</h2>
              <p className="muted">
                Pick a goal — we'll show what passes the labs.
                {categories.length > 0 && (
                  <span className="cat-count-mobile"> {categories.length} categories available.</span>
                )}
              </p>
            </div>
            <Link to="/browse" className="btn btn-ghost">
              View all{categories.length > 0 ? ` ${categories.length}` : ''} →
            </Link>
          </div>
          <div className="cat-grid">
            {sortedCategories.map((c) => {
              const hue = CATEGORY_HUES[c.slug] || 'teal'
              return (
                <Link
                  key={c.slug}
                  to={`/browse?category=${c.slug}`}
                  className={`cat-card cat-${hue}`}
                >
                  <span className="cat-icon">{getCategoryEmoji(c.icon)}</span>
                  <strong>{c.name}</strong>
                  <span className="muted">{c.supplement_count || 0} products</span>
                </Link>
              )
            })}
          </div>
        </div>
      </section>

      {/* Top rated — horizontal rail */}
      <section className="section section-alt">
        <div className="container">
          <div className="section-head">
            <div>
              <h2>Top-rated this month</h2>
              <p className="muted">Highest scores across all labs.</p>
            </div>
            <Link to="/browse" className="btn btn-ghost">See all →</Link>
          </div>
          <div className="card-rail">
            <div className="card-rail-inner">
              {loading
                ? Array(6).fill(null).map((_, i) => <CardSkeleton key={i} />)
                : topRated.map((s) => (
                    <SupplementCard key={s.id || s.slug} supplement={s} compact />
                  ))}
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="section how">
        <div className="container">
          <div className="section-head center">
            <div>
              <h2>How it works</h2>
              <p className="muted">Three steps to a smarter supplement choice.</p>
            </div>
          </div>
          <div className="how-grid">
            <div className="how-step">
              <div className="how-num">01</div>
              <h3>Search or browse</h3>
              <p>Find the supplement you're considering by name, brand, or category.</p>
            </div>
            <div className="how-step">
              <div className="how-num">02</div>
              <h3>See every lab score</h3>
              <p>One aggregate score plus the breakdown from each independent lab — side-by-side.</p>
            </div>
            <div className="how-step">
              <div className="how-num">03</div>
              <h3>Decide with confidence</h3>
              <p>Click through to the lab's full report.</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="cta">
        <div className="container">
          <div className="cta-card">
            <h2>Ready to find a supplement you can trust?</h2>
            <p className="muted">
              {supplementCount > 0 ? floorRounded(supplementCount) : 'Every'} supplements rated by independent labs. Evidence-first.
            </p>
            <div className="cta-actions">
              <Link to="/browse" className="btn btn-primary btn-lg">Browse supplements</Link>
              <Link to="/compare" className="btn btn-secondary btn-lg">Try compare tool</Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
