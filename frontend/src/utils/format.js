export function getScoreColor(score) {
  if (score == null) return 'var(--color-muted)'
  if (score >= 90) return 'var(--color-success)'
  if (score >= 75) return 'var(--color-primary)'
  if (score >= 60) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

export function getScoreGrade(score) {
  if (score == null) return '—'
  if (score >= 95) return 'A+'
  if (score >= 90) return 'A'
  if (score >= 85) return 'A-'
  if (score >= 80) return 'B+'
  if (score >= 75) return 'B'
  if (score >= 70) return 'B-'
  if (score >= 65) return 'C+'
  if (score >= 60) return 'C'
  return 'D'
}

export function formatScore(score) {
  if (score == null) return '—'
  return Number(score).toFixed(1)
}

export function getCategoryEmoji(icon) {
  const map = {
    vitamin: '💊',
    mineral: '⚡',
    protein: '🥛',
    fish: '🐟',
    probiotic: '🦠',
    leaf: '🌿',
    dumbbell: '💪',
    moon: '🌙',
  }
  return map[icon] || '📦'
}

export function formatDate(iso) {
  if (!iso) return null
  const date = new Date(iso)
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}


// Decode common HTML entities and strip noisy suffixes ("Review", trailing brand) from
// scraped supplement names so they read naturally in cards / detail pages.
export function cleanProductName(name, brand) {
  if (!name) return ''
  let s = String(name)
    .replace(/&amp;/g, '&')
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+Review\.?$/i, '')
    .trim()

  // Strip leading brand if it appears at the start of the product name. Also handle
  // the common "Brand — Product" / "Brand - Product" / "Brand: Product" patterns.
  if (brand) {
    const b = brand.toLowerCase()
    if (s.toLowerCase().startsWith(b)) {
      const rest = s.slice(brand.length)
      // Only strip if what follows is a separator or whitespace (not part of another word)
      if (/^[\s\-–—:|]/.test(rest) || rest === '') {
        s = rest
      }
    }
  }

  // Strip any leading separators left behind ("- Platinum" → "Platinum")
  s = s.replace(/^[\s\-–—:|]+/, '').trim()

  // Collapse internal whitespace
  s = s.replace(/\s+/g, ' ').trim()

  // If we ended up with nothing (name was just the brand), fall back to the original
  return s || name
}


// Compact display name for hero/compare-tray thumbnails
export function shortenName(s, max = 36) {
  if (!s) return ''
  if (s.length <= max) return s
  return s.slice(0, max).trimEnd() + '…'
}
