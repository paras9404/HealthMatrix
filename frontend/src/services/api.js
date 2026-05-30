import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 15000,
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

export const supplementsApi = {
  list: (params = {}) => {
    // Drop empty-string params so the URL is clean
    const cleaned = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v != null))
    return api.get('/supplements', { params: cleaned }).then((r) => r.data)
  },
  get: (slug) => api.get(`/supplements/${slug}`).then((r) => r.data),
  featured: (limit = 6) => api.get('/supplements/featured', { params: { limit } }).then((r) => r.data),
  suggest: (q) => api.get('/supplements/search/suggest', { params: { q } }).then((r) => r.data),
}

export const categoriesApi = {
  list: () => api.get('/categories').then((r) => r.data),
}

export const sourcesApi = {
  list: ({ counts = false } = {}) => api.get('/sources', { params: counts ? { counts: true } : {} }).then((r) => r.data),
}

export const compareApi = {
  get: (slugs) => api.get('/compare', { params: { slugs: slugs.join(',') } }).then((r) => r.data),
}

export const statsApi = {
  get: () => api.get('/stats').then((r) => r.data),
}

export default api
