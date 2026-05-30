import axios from 'axios'

const TOKEN_KEY = 'hm_admin_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

const adminApi = axios.create({
  baseURL: '/api/admin',
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
})

adminApi.interceptors.request.use((config) => {
  const t = getToken()
  if (t) config.headers.Authorization = `Bearer ${t}`
  return config
})

adminApi.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    const msg = err.response?.data?.message || err.message || 'Network error'
    err.userMessage = msg
    if (status === 401) {
      // Token missing/expired — bounce to login from any page that uses this client.
      setToken(null)
      const onLogin = window.location.pathname.startsWith('/admin/login')
      if (!onLogin) window.location.href = '/admin/login'
    }
    return Promise.reject(err)
  }
)

// ---------------- Auth ----------------
export const authApi = {
  login: (username, password) =>
    adminApi.post('/auth/login', { username, password }).then((r) => r.data),
  me: () => adminApi.get('/auth/me').then((r) => r.data),
  logout: () => adminApi.post('/auth/logout').then((r) => r.data),
  changePassword: (current_password, new_password) =>
    adminApi.post('/auth/change-password', { current_password, new_password }).then((r) => r.data),
}

// ---------------- Dashboard ----------------
export const dashboardApi = {
  stats: () => adminApi.get('/dashboard/stats').then((r) => r.data),
  recentActivity: () => adminApi.get('/dashboard/recent-activity').then((r) => r.data),
}

// ---------------- Generic CRUD factory ----------------
function makeCrud(resource) {
  return {
    list: (params = {}) => adminApi.get(`/${resource}`, { params }).then((r) => r.data),
    get: (id) => adminApi.get(`/${resource}/${id}`).then((r) => r.data),
    create: (payload) => adminApi.post(`/${resource}`, payload).then((r) => r.data),
    update: (id, payload) => adminApi.patch(`/${resource}/${id}`, payload).then((r) => r.data),
    remove: (id) => adminApi.delete(`/${resource}/${id}`).then((r) => r.data),
  }
}

export const supplementsAdminApi = {
  ...makeCrud('supplements'),
  // Re-scrape the saved Amazon URL and update only amazon_data.price.
  // Slow (network-bound) — backend can take 10s+ so override the default timeout.
  refreshPrice: (id) =>
    adminApi.post(`/supplements/${id}/refresh-price`, null, { timeout: 30000 }).then((r) => r.data),
  // Bulk: walks every supplement with an amazon_url, refreshes price field only.
  // Returns immediately; poll bulkRefreshPriceStatus() while it runs.
  bulkRefreshPriceStart: (body = {}) =>
    adminApi.post('/supplements/bulk-refresh-price', body).then((r) => r.data),
  bulkRefreshPriceStatus: () =>
    adminApi.get('/supplements/bulk-refresh-price/status').then((r) => r.data),
  bulkRefreshPriceStop: () =>
    adminApi.post('/supplements/bulk-refresh-price/stop').then((r) => r.data),
}
export const brandsAdminApi = makeCrud('brands')
export const categoriesAdminApi = makeCrud('categories')
export const sourcesAdminApi = makeCrud('sources')
export const ratingsAdminApi = makeCrud('ratings')
export const imagesAdminApi = makeCrud('images')
export const usersAdminApi = makeCrud('users')

// ---------------- Product groups ----------------
// Slash-spaced URL because the Flask blueprint is registered under that prefix.
export const productGroupsAdminApi = {
  ...makeCrud('product-groups'),
  suggestions: (params = {}) =>
    adminApi.get('/product-groups/suggestions', { params }).then((r) => r.data),
  ungrouped: (params = {}) =>
    adminApi.get('/product-groups/ungrouped', { params }).then((r) => r.data),
  addMembers: (group_id, member_ids) =>
    adminApi.post(`/product-groups/${group_id}/members`, { member_ids }).then((r) => r.data),
  removeMember: (group_id, supplement_id) =>
    adminApi.delete(`/product-groups/${group_id}/members/${supplement_id}`).then((r) => r.data),
  setVariantLabel: (group_id, supplement_id, variant_label) =>
    adminApi.patch(`/product-groups/${group_id}/members/${supplement_id}/variant-label`,
                    { variant_label }).then((r) => r.data),
}

// ---------------- Audit ----------------
export const auditApi = {
  list: (params = {}) => adminApi.get('/audit', { params }).then((r) => r.data),
}

// ---------------- Analytics ----------------
export const analyticsApi = {
  overview: () => adminApi.get('/analytics/overview').then((r) => r.data),
  timeseries: (range = '7d') =>
    adminApi.get('/analytics/timeseries', { params: { range } }).then((r) => r.data),
  topPages: (range = '7d', limit = 10) =>
    adminApi.get('/analytics/top-pages', { params: { range, limit } }).then((r) => r.data),
  topSupplements: (range = '7d', limit = 10) =>
    adminApi.get('/analytics/top-supplements', { params: { range, limit } }).then((r) => r.data),
  topSearches: (range = '7d', limit = 20) =>
    adminApi.get('/analytics/top-searches', { params: { range, limit } }).then((r) => r.data),
  topReferrers: (range = '7d', limit = 15) =>
    adminApi.get('/analytics/top-referrers', { params: { range, limit } }).then((r) => r.data),
  devices: (range = '7d') =>
    adminApi.get('/analytics/devices', { params: { range } }).then((r) => r.data),
  activeNow: () => adminApi.get('/analytics/active-now').then((r) => r.data),
  recentEvents: (limit = 50, includeBots = false) =>
    adminApi.get('/analytics/recent-events', {
      params: { limit, include_bots: includeBots ? '1' : '0' },
    }).then((r) => r.data),
  sessions: (params = {}) =>
    adminApi.get('/analytics/sessions', { params }).then((r) => r.data),
  sessionDetail: (sessionUuid) =>
    adminApi.get(`/analytics/sessions/${sessionUuid}`).then((r) => r.data),
  rateLimits: (range = '7d') =>
    adminApi.get('/analytics/rate-limits', { params: { range } }).then((r) => r.data),
}

// ---------------- Source import (paste a Trustified/Labdoor/Unbox URL → upsert product+rating) ----------------
export const sourceImportApi = {
  scrape: (url) =>
    adminApi.post('/source-import/scrape', { url }, { timeout: 45000 }).then((r) => r.data),
  importProduct: (payload) =>
    adminApi.post('/source-import/import', payload, { timeout: 45000 }).then((r) => r.data),
  // Bulk: discover the live catalog → diff → background import.
  // Discovery for Labdoor walks ~40 ranking pages so allow plenty of time.
  discover: (source) =>
    adminApi.post('/source-import/discover', { source }, { timeout: 120000 }).then((r) => r.data),
  bulkImportStart: (source, urls) =>
    adminApi.post('/source-import/bulk-import', { source, urls }).then((r) => r.data),
  bulkImportStatus: () =>
    adminApi.get('/source-import/bulk-import/status').then((r) => r.data),
  bulkImportStop: () =>
    adminApi.post('/source-import/bulk-import/stop').then((r) => r.data),
}

// ---------------- Image validation (temporary tool) ----------------
export const imageValidationApi = {
  listProducts: (params = {}) =>
    adminApi.get('/image-validation/products', { params }).then((r) => r.data),
  scrapeAmazon: (url) =>
    adminApi.post('/image-validation/scrape-amazon', { url }).then((r) => r.data),
  autoSearch: (supplement_id, opts = {}) =>
    adminApi.post('/image-validation/auto-search', { supplement_id, ...opts }).then((r) => r.data),
  bulkSearchStart: (body = {}) =>
    adminApi.post('/image-validation/bulk-search', body).then((r) => r.data),
  bulkSearchStatus: () =>
    adminApi.get('/image-validation/bulk-search/status').then((r) => r.data),
  bulkSearchStop: () =>
    adminApi.post('/image-validation/bulk-search/stop').then((r) => r.data),
  listSources: () =>
    adminApi.get('/image-validation/sources').then((r) => r.data),
  resolveLabdoorAmazon: (supplement_id, opts = {}) =>
    adminApi.post('/image-validation/resolve-labdoor-amazon', { supplement_id, ...opts }).then((r) => r.data),
  bulkResolveLabdoorStart: (body = {}) =>
    adminApi.post('/image-validation/bulk-resolve-labdoor', body).then((r) => r.data),
  bulkResolveLabdoorStatus: () =>
    adminApi.get('/image-validation/bulk-resolve-labdoor/status').then((r) => r.data),
  bulkResolveLabdoorStop: () =>
    adminApi.post('/image-validation/bulk-resolve-labdoor/stop').then((r) => r.data),
  resolveTrustifiedAmazon: (supplement_id, opts = {}) =>
    adminApi.post('/image-validation/resolve-trustified-amazon', { supplement_id, ...opts }).then((r) => r.data),
  bulkResolveTrustifiedStart: (body = {}) =>
    adminApi.post('/image-validation/bulk-resolve-trustified', body).then((r) => r.data),
  bulkResolveTrustifiedStatus: () =>
    adminApi.get('/image-validation/bulk-resolve-trustified/status').then((r) => r.data),
  bulkResolveTrustifiedStop: () =>
    adminApi.post('/image-validation/bulk-resolve-trustified/stop').then((r) => r.data),
  bulkAutoImportStart: (body = {}) =>
    adminApi.post('/image-validation/bulk-auto-import', body).then((r) => r.data),
  bulkAutoImportStatus: () =>
    adminApi.get('/image-validation/bulk-auto-import/status').then((r) => r.data),
  bulkAutoImportStop: () =>
    adminApi.post('/image-validation/bulk-auto-import/stop').then((r) => r.data),
}

export default adminApi
