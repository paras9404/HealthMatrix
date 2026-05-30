// SEO config + JSON-LD builders. Centralizing these keeps page components
// focused on copy — every absolute URL, brand string, and schema shape lives here.

export const SITE_URL = (import.meta.env.VITE_SITE_URL || 'https://healthmatrix.com').replace(/\/$/, '')
export const SITE_NAME = 'HealthMatrix'
export const SITE_LOCALE = 'en_US'
export const SITE_LANGUAGE = 'en-US'
export const DEFAULT_TITLE = 'HealthMatrix — Compare Supplement Ratings Across Trusted Labs'
export const DEFAULT_DESCRIPTION =
  'Compare supplement quality ratings from 9 independent labs — Labdoor, ConsumerLab, NSF, USP, Examine, Trustified, Informed Choice, Informed Sport, and Trustpilot. One aggregate score. Zero guesswork.'
export const DEFAULT_OG_IMAGE = `${SITE_URL}/og-image.png`
export const DEFAULT_OG_IMAGE_ALT = 'HealthMatrix — aggregate supplement quality scores from independent testing labs'
export const TWITTER_HANDLE = '@healthmatrix'

// Build an absolute canonical URL from a path. Strips trailing slash unless root.
export function absoluteUrl(path = '/') {
  if (!path.startsWith('/')) path = `/${path}`
  if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1)
  return `${SITE_URL}${path}`
}

// Resolve a possibly-relative image URL to an absolute one for OG tags.
export function absoluteImage(url) {
  if (!url) return DEFAULT_OG_IMAGE
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('//')) return `https:${url}`
  if (url.startsWith('/static/')) {
    const apiBase = (import.meta.env.VITE_API_URL || SITE_URL).replace(/\/$/, '')
    return `${apiBase}${url}`
  }
  return `${SITE_URL}${url.startsWith('/') ? '' : '/'}${url}`
}

// JSON-LD: site-wide Organization. One per site.
export function buildOrganizationJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    '@id': `${SITE_URL}/#organization`,
    name: SITE_NAME,
    url: SITE_URL,
    logo: {
      '@type': 'ImageObject',
      url: `${SITE_URL}/favicon.svg`,
      width: 512,
      height: 512,
    },
    sameAs: [],
    description: DEFAULT_DESCRIPTION,
  }
}

// JSON-LD: WebSite + sitelinks search box on the home page.
export function buildWebSiteJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    '@id': `${SITE_URL}/#website`,
    name: SITE_NAME,
    url: SITE_URL,
    description: DEFAULT_DESCRIPTION,
    inLanguage: SITE_LANGUAGE,
    publisher: { '@id': `${SITE_URL}/#organization` },
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${SITE_URL}/browse?q={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    },
  }
}

// JSON-LD: BreadcrumbList. crumbs: [{ name, url }]
export function buildBreadcrumbJsonLd(crumbs) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: crumbs.map((c, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: c.name,
      item: absoluteUrl(c.url),
    })),
  }
}

// Parse a "$24.99" / "$19–$28" / "19.99 USD" price string to a numeric range.
// Returns { low, high, currency } or null. Used to power Offer JSON-LD.
function parsePrice(input) {
  if (!input) return null
  if (typeof input === 'number') return { low: input, high: input, currency: 'USD' }
  const str = String(input).trim()
  if (!str) return null
  const currency = /[€]/.test(str) ? 'EUR' : /[£]/.test(str) ? 'GBP' : 'USD'
  const nums = str.match(/\d+(?:\.\d+)?/g)
  if (!nums || nums.length === 0) return null
  const low = parseFloat(nums[0])
  const high = parseFloat(nums[nums.length - 1])
  if (Number.isNaN(low)) return null
  return { low, high: Number.isNaN(high) ? low : high, currency }
}

// ISO date or null. Accepts a Date, ISO string, or backend timestamp.
function isoDate(value) {
  if (!value) return null
  try {
    const d = value instanceof Date ? value : new Date(value)
    if (Number.isNaN(d.getTime())) return null
    return d.toISOString()
  } catch {
    return null
  }
}

// JSON-LD: Product + AggregateRating for a supplement detail page.
// `data` is the supplement payload from /api/supplements/<slug>.
export function buildProductJsonLd(data) {
  const brand = data?.brand?.name || data?.brand
  const ratings = data?.ratings || []
  const score = data?.aggregate_score
  const url = absoluteUrl(`/supplement/${data.slug}`)

  const product = {
    '@context': 'https://schema.org',
    '@type': 'Product',
    '@id': `${url}#product`,
    name: data.name,
    url,
    image: absoluteImage(data.image),
    description: data.description || `${data.name}${brand ? ` by ${brand}` : ''} — independently rated supplement aggregated across labs.`,
    inLanguage: SITE_LANGUAGE,
  }

  if (brand) {
    product.brand = { '@type': 'Brand', name: brand }
  }
  if (data.category?.name) {
    product.category = data.category.name
  }
  if (data.upc) {
    product.gtin12 = data.upc
  }
  if (data.sku) {
    product.sku = data.sku
  } else if (data.slug) {
    product.sku = data.slug
  }
  if (data.mpn) {
    product.mpn = data.mpn
  }

  const additionalProps = []
  if (data.ingredients) additionalProps.push({ '@type': 'PropertyValue', name: 'Ingredients', value: data.ingredients })
  if (data.serving_size) additionalProps.push({ '@type': 'PropertyValue', name: 'Serving size', value: data.serving_size })
  if (data.servings) additionalProps.push({ '@type': 'PropertyValue', name: 'Servings per container', value: String(data.servings) })
  if (data.form) additionalProps.push({ '@type': 'PropertyValue', name: 'Form', value: data.form })
  if (additionalProps.length) product.additionalProperty = additionalProps

  // Offer — Google Shopping / rich-result eligible. Skip when no price is known.
  const price = parsePrice(data.price || data.price_range)
  if (price) {
    const offerBase = {
      '@type': 'Offer',
      url,
      priceCurrency: price.currency,
      availability: 'https://schema.org/InStock',
      itemCondition: 'https://schema.org/NewCondition',
    }
    product.offers = price.low === price.high
      ? { ...offerBase, price: price.low.toFixed(2) }
      : {
          '@type': 'AggregateOffer',
          url,
          priceCurrency: price.currency,
          lowPrice: price.low.toFixed(2),
          highPrice: price.high.toFixed(2),
          offerCount: 1,
          availability: 'https://schema.org/InStock',
        }
  }

  if (typeof score === 'number' && ratings.length > 0) {
    product.aggregateRating = {
      '@type': 'AggregateRating',
      ratingValue: score.toFixed(1),
      bestRating: '100',
      worstRating: '0',
      ratingCount: ratings.length,
      reviewCount: ratings.length,
    }
  }

  if (ratings.length > 0) {
    product.review = ratings
      .filter((r) => r.source && (r.normalized_score != null || r.score != null))
      .slice(0, 5)
      .map((r) => {
        const review = {
          '@type': 'Review',
          author: { '@type': 'Organization', name: r.source.name },
          reviewRating: {
            '@type': 'Rating',
            ratingValue: r.normalized_score != null ? Math.round(r.normalized_score) : r.score,
            bestRating: '100',
            worstRating: '0',
          },
          reviewBody: r.verdict || r.summary || `Tested by ${r.source.name}.`,
        }
        const tested = isoDate(r.tested_at)
        if (tested) review.datePublished = tested.slice(0, 10)
        return review
      })
  }

  const created = isoDate(data.created_at)
  const updated = isoDate(data.updated_at)
  if (created) product.releaseDate = created.slice(0, 10)
  if (updated) product.dateModified = updated

  return product
}

// JSON-LD: ItemList for the Browse listing — helps crawlers see the full catalog
// when JS rendering succeeds. Keep this lightweight: name + url only per item.
export function buildItemListJsonLd(items, basePath = '/browse') {
  return {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    url: absoluteUrl(basePath),
    numberOfItems: items.length,
    itemListElement: items.map((s, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      url: absoluteUrl(`/supplement/${s.slug}`),
      name: s.name,
    })),
  }
}

// JSON-LD: CollectionPage — wraps the Browse listing with descriptive metadata.
// Use alongside ItemList when the page is a true collection (catalog/category landing).
export function buildCollectionPageJsonLd({ name, description, path = '/browse', itemCount }) {
  return {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    '@id': `${absoluteUrl(path)}#collection`,
    url: absoluteUrl(path),
    name,
    description,
    inLanguage: SITE_LANGUAGE,
    isPartOf: { '@id': `${SITE_URL}/#website` },
    publisher: { '@id': `${SITE_URL}/#organization` },
    ...(typeof itemCount === 'number' ? { mainEntity: { '@type': 'ItemList', numberOfItems: itemCount } } : {}),
  }
}

// JSON-LD: FAQPage — pairs of question/answer text for rich result eligibility.
// Pass an array of { question, answer } strings.
export function buildFAQJsonLd(items) {
  if (!Array.isArray(items) || items.length === 0) return null
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: items.map((it) => ({
      '@type': 'Question',
      name: it.question,
      acceptedAnswer: {
        '@type': 'Answer',
        text: it.answer,
      },
    })),
  }
}

// JSON-LD: HowTo — describes a step-by-step process. Used for the "how we score" methodology.
export function buildHowToJsonLd({ name, description, steps }) {
  return {
    '@context': 'https://schema.org',
    '@type': 'HowTo',
    name,
    description,
    inLanguage: SITE_LANGUAGE,
    step: (steps || []).map((s, i) => ({
      '@type': 'HowToStep',
      position: i + 1,
      name: s.name,
      text: s.text,
    })),
  }
}

// JSON-LD: WebPage — generic wrapper to anchor a page to the org/website graph.
export function buildWebPageJsonLd({ title, description, path = '/', type = 'WebPage' }) {
  return {
    '@context': 'https://schema.org',
    '@type': type,
    '@id': `${absoluteUrl(path)}#webpage`,
    url: absoluteUrl(path),
    name: title,
    description,
    inLanguage: SITE_LANGUAGE,
    isPartOf: { '@id': `${SITE_URL}/#website` },
    publisher: { '@id': `${SITE_URL}/#organization` },
  }
}
