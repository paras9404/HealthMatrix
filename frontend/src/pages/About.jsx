import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { sourcesApi, statsApi } from '../services/api.js'
import Seo from '../components/Seo.jsx'
import {
  buildBreadcrumbJsonLd,
  buildOrganizationJsonLd,
  buildFAQJsonLd,
  buildHowToJsonLd,
  buildWebPageJsonLd,
} from '../utils/seo.js'
import './About.css'

export default function About() {
  const [allSources, setAllSources] = useState([])
  const [stats, setStats] = useState(null)

  useEffect(() => {
    sourcesApi.list({ counts: true }).then((s) => setAllSources(s.items || [])).catch(() => {})
    statsApi.get().then(setStats).catch(() => {})
  }, [])

  // Show only sources that actually have rated supplements in our DB.
  const sources = useMemo(
    () => allSources.filter((s) => (s.supplement_count ?? 0) > 0),
    [allSources],
  )

  const labCount = stats?.sources_with_data ?? sources.length

  const aboutDescription = `HealthMatrix aggregates supplement quality ratings from ${labCount || 9} independent labs into one transparent score. Learn how we calculate it, what our sources are, and how we stay unbiased.`

  const aboutFaq = [
    {
      question: 'How does HealthMatrix calculate the aggregate score?',
      answer: 'Each lab grades on a different scale (letters, percentages, pass/fail, certifications). We normalize every rating to a 0–100 scale, weight unverified sources at half, then average across all available sources to produce one HealthMatrix Score per product.',
    },
    {
      question: 'Who tests the supplements?',
      answer: 'Independent third-party labs like Labdoor, ConsumerLab, NSF International, and USP run the actual lab tests. HealthMatrix is an aggregator — we surface their results in one place and link back to each original report.',
    },
    {
      question: 'Is HealthMatrix biased toward any brand?',
      answer: 'No. We do not accept payment from supplement brands to influence ratings or rankings. Some product pages contain affiliate links to retailers; these are clearly disclosed and never affect the aggregate score.',
    },
    {
      question: 'What does "verified" vs "unverified" mean?',
      answer: 'Verified sources are labs with documented, repeatable testing protocols and full transparency. Unverified sources may rely on user-submitted data or less rigorous methodology — they are still useful signals but contribute at half-weight to the aggregate score.',
    },
    {
      question: 'Is the information on HealthMatrix medical advice?',
      answer: 'No. Information on HealthMatrix is for educational purposes only and is not a substitute for professional medical advice. Always consult a healthcare provider before starting a new supplement.',
    },
  ]

  const methodologyHowTo = buildHowToJsonLd({
    name: 'How the HealthMatrix Aggregate Score is calculated',
    description: 'Three-step normalization that turns lab results on different scales into one comparable 0–100 score.',
    steps: [
      { name: 'Normalize', text: 'Convert each lab\'s grade to a 0–100 scale using the source\'s own scoring rubric.' },
      { name: 'Weight', text: 'Verified labs count at full weight; unverified sources count at half-weight.' },
      { name: 'Average', text: 'Combine all weighted lab scores into one aggregate HealthMatrix Score.' },
    ],
  })

  return (
    <div className="about fade-in">
      <Seo
        title="About HealthMatrix"
        description={aboutDescription}
        path="/about"
        jsonLd={[
          buildOrganizationJsonLd(),
          buildWebPageJsonLd({ title: 'About HealthMatrix', description: aboutDescription, path: '/about', type: 'AboutPage' }),
          buildBreadcrumbJsonLd([
            { name: 'Home', url: '/' },
            { name: 'About', url: '/about' },
          ]),
          buildFAQJsonLd(aboutFaq),
          methodologyHowTo,
        ]}
      />
      <div className="container about-container">
        <header className="about-hero">
          <h1>About HealthMatrix</h1>
          <p className="lead">
            We help you choose supplements that actually pass independent lab tests.
            No selling. No bias. Just transparent ratings.
          </p>
        </header>

        <div className="about-cards">
          <div className="about-card">
            <div className="about-icon">🔬</div>
            <h3>{labCount} independent labs</h3>
            <p className="muted">
              {sources.slice(0, 6).map((s) => s.name).join(', ')}{sources.length > 6 ? '…' : ''}
            </p>
          </div>
          <div className="about-card">
            <div className="about-icon">📊</div>
            <h3>One aggregate score</h3>
            <p className="muted">
              Every lab uses a different scale. We normalize them to 0–100 and average them — so you get one number you can trust.
            </p>
          </div>
          <div className="about-card">
            <div className="about-icon">🔓</div>
            <h3>No paywalls</h3>
            <p className="muted">
              No email gates, no upsells. We earn from optional affiliate links — clearly disclosed.
            </p>
          </div>
        </div>

        <section id="sources" className="about-section">
          <h2>Our sources</h2>
          <p className="muted">
            We aggregate publicly available data and ratings from these independent testing labs.
            Each rating links back to the original source — we don't republish proprietary reports.
          </p>
          <div className="about-sources-grid">
            {sources.length === 0 && (
              <p className="muted">No sources configured yet.</p>
            )}
            {sources.map((s) => (
              <a
                key={s.slug}
                href={s.website_url}
                target="_blank"
                rel="noopener noreferrer"
                className="source-card"
              >
                <h3>
                  {s.name}
                  {s.is_verified && <span className="source-verified" title="Independently verified">✓</span>}
                </h3>
                <p className="muted">{s.description || `${s.rating_scale || ''} rating system.`}</p>
                <div className="source-meta">
                  {s.rating_scale && <span className="badge">{s.rating_scale}</span>}
                </div>
                <span className="source-link">Visit site ↗</span>
              </a>
            ))}
          </div>
        </section>

        <section id="methodology" className="about-section">
          <h2>How we calculate the aggregate score</h2>
          <p className="muted">
            Each lab uses its own scale — Labdoor scores 0–100, ConsumerLab gives Pass/Fail, NSF and USP issue
            certifications. We normalize each rating to a 0–100 scale based on the source's own scoring rubric,
            then average across all available sources to produce the HealthMatrix Aggregate Score.
          </p>
          <ul className="about-list">
            <li><strong>Numeric scores</strong> (e.g., Labdoor 92.1) are used as-is on the 0–100 scale.</li>
            <li><strong>Pass/Fail</strong> verdicts contribute 100 (Pass) or 0 (Fail).</li>
            <li><strong>Certifications</strong> (NSF, USP) contribute 100 when granted.</li>
            <li><strong>5-star scales</strong> are normalized to 0–100 (5 stars = 100).</li>
          </ul>
        </section>

        <section id="disclaimer" className="about-section disclaimer-section">
          <h2>Disclaimer</h2>
          <div className="about-disclaimer">
            <p><strong>Not medical advice.</strong> The information on HealthMatrix is for educational purposes only and is not intended to replace professional medical advice. Always consult your healthcare provider before starting any new supplement.</p>
            <p><strong>Affiliate disclosure.</strong> We may earn a commission from qualifying purchases made through links on this site. This does not influence editorial content or ratings.</p>
            <p><strong>Source attribution.</strong> All ratings, scores, and reports remain the property of their respective testing organizations. HealthMatrix does not produce or own any laboratory test results.</p>
            <p><strong>FDA notice.</strong> Statements about supplements have not been evaluated by the FDA. These products are not intended to diagnose, treat, cure, or prevent any disease.</p>
          </div>
        </section>

        <div className="about-cta">
          <h3>Ready to find a supplement you can trust?</h3>
          <Link to="/browse" className="btn btn-primary btn-lg">Browse supplements</Link>
        </div>
      </div>
    </div>
  )
}
