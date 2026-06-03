import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  // 60s tolerates Render free-tier cold starts (~30-50s after 15min idle).
  // Warm requests still return in <500ms.
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message = err.response?.data?.message || err.message || 'Network error'
    err.userMessage = message
    return Promise.reject(err)
  }
)

// In-flight GET coalescing: when two components mount on the same page and both
// fire the same GET (e.g. Home + Footer both calling /sources?counts=true), share
// one HTTP request. The cache is keyed by URL + params and only lives until the
// request settles — there's no stale-data risk because subsequent component
// mounts re-issue fresh GETs.
const inflight = new Map()
function dedupeGet(url, params) {
  const key = `${url}?${new URLSearchParams(params || {}).toString()}`
  const hit = inflight.get(key)
  if (hit) return hit
  const promise = api.get(url, { params }).then((r) => r.data).finally(() => inflight.delete(key))
  inflight.set(key, promise)
  return promise
}

export const supplementsApi = {
  list: (params = {}) => {
    // Drop empty-string params so the URL is clean
    const cleaned = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v != null))
    return dedupeGet('/supplements', cleaned)
  },
  get: (slug) => dedupeGet(`/supplements/${slug}`),
  featured: (limit = 6, { includeRatings = false } = {}) => dedupeGet(
    '/supplements/featured',
    includeRatings ? { limit, include_ratings: true } : { limit },
  ),
  suggest: (q) => api.get('/supplements/search/suggest', { params: { q } }).then((r) => r.data),
}

export const categoriesApi = {
  list: () => dedupeGet('/categories'),
}

export const sourcesApi = {
  list: ({ counts = false } = {}) => dedupeGet('/sources', counts ? { counts: true } : {}),
}

export const compareApi = {
  get: (slugs) => api.get('/compare', { params: { slugs: slugs.join(',') } }).then((r) => r.data),
}

export const statsApi = {
  get: () => dedupeGet('/stats'),
}

export default api
