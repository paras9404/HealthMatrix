# HealthMatrix

A supplement comparison platform that aggregates quality ratings from 9 independent testing labs (Labdoor, ConsumerLab, NSF, USP, Examine.com, Trustified, Informed Choice, Informed Sport, Trustpilot) into a single view — with affiliate links to each lab's full report and retailer buy pages.

**Stack:** React 18 + Vite (frontend) · Flask 3 + SQLAlchemy 2 (backend) · **PostgreSQL 16** (dev + prod, via psycopg3) · Flask-Migrate / Alembic · Redis-ready rate limiting.

---

## Quick Start

```bash
# 1. Install Postgres 16 (one time, macOS)
brew install postgresql@16

# 2. Bootstrap the project
make install        # backend venv + frontend node_modules
make db-up          # start Postgres
make db-reset       # create db, run migrations, seed sample data

# 3. Run (in two terminals)
make backend        # http://localhost:5001
make frontend       # http://localhost:5173
```

Open http://localhost:5173 — Vite proxies `/api/*` to Flask.

### All make targets

| Category | Command | Description |
|---|---|---|
| Setup | `make install` | venv + node_modules |
| Run | `make backend` / `make frontend` | Start API or UI |
| DB lifecycle | `make db-up` / `make db-down` / `make db-status` | Postgres service control |
| DB shell | `make db-shell` | `psql` into `healthmatrix_dev` |
| DB reset | `make db-reset` | Drop, recreate, migrate, seed |
| Migrations | `make migrate MSG="add foo"` | Generate a new Alembic migration |
| | `make upgrade` / `make downgrade` | Apply / rollback |
| | `make seed` | Re-populate with sample data |
| Imports | `make import-trustified [LIMIT=N]` | Scrape trustified.in /passandfail products |
| | `make import-labdoor [LIMIT=N]` | Scrape labdoor.com rankings + reviews |
| | `make fetch-data` | Refresh DSLD label data + image fallbacks |
| Tools | `make status` / `make freeze` / `make lock` | Inspect env / list pkgs / refresh lockfile |
| Clean | `make clean` | Wipe venv + node_modules (keeps DB) |

### Manual setup (no make)

```bash
# Postgres (one time)
brew install postgresql@16
brew services start postgresql@16
createdb healthmatrix_dev

# Backend
cd backend && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
flask db upgrade && python seed.py && python run.py

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

### Dependency & data hygiene

- All Python packages live in **`backend/venv/`** — never globally installed.
- All Node packages live in **`frontend/node_modules/`**.
- DB data lives in **`/opt/homebrew/var/postgresql@16/`** (Homebrew default).
- All three are gitignored.
- `backend/requirements.txt` lists top-level deps; `backend/requirements.lock.txt` is the full pinned tree (regenerate with `make lock`).

---

## Project Structure

```
HealthMatrix/
├── backend/
│   ├── app/
│   │   ├── __init__.py         # Flask app factory
│   │   ├── config.py           # Dev/prod/test configs
│   │   ├── extensions.py       # SQLAlchemy, CORS, Limiter
│   │   ├── models/             # Category, Source, Supplement, Rating
│   │   └── routes/             # Blueprints: supplements, categories, sources, compare
│   ├── seed.py                 # Seed sample data
│   ├── run.py                  # Dev entrypoint
│   ├── requirements.txt        # SQLite-only (dev)
│   └── requirements-prod.txt   # Adds psycopg2 + redis
├── frontend/
│   ├── src/
│   │   ├── components/         # Navbar, Footer, SupplementCard, ScoreBadge, CompareTray, Loader
│   │   ├── pages/              # Home, Browse, SupplementDetail, Compare, About, NotFound
│   │   ├── services/api.js     # Axios client
│   │   ├── hooks/useCompare.jsx # Compare state (localStorage-backed)
│   │   ├── utils/format.js     # Score colors/grades, helpers
│   │   └── styles/index.css    # Design tokens, base styles
│   ├── vite.config.js          # Dev proxy to Flask
│   └── package.json
└── .claude/launch.json         # Dev-server launcher (optional)
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/supplements?q=&category=&brand=&sort=&page=&per_page=` | Paginated list with search/filter (only `is_published=true`) |
| GET | `/api/supplements/featured?limit=6` | Featured supplements |
| GET | `/api/supplements/search/suggest?q=` | Autocomplete suggestions |
| GET | `/api/supplements/<slug>` | Detail with all ratings |
| GET | `/api/categories` | All categories with counts |
| GET | `/api/categories/<slug>` | Single category |
| GET | `/api/brands` | All brands with counts |
| GET | `/api/brands/<slug>` | Single brand |
| GET | `/api/sources` | All testing sources |
| GET | `/api/compare?slugs=a,b,c` | Side-by-side data (2-4 slugs) |

---

## Data Model

```
brands ──┐
         │
         ▼                  sources
       supplements ◄──── ratings ────►
         ▲                  (FK)
         │
       categories
```

| Table | Purpose | Key fields |
|---|---|---|
| **brands** | Manufacturers (Thorne, Nordic Naturals, etc.) | `name`, `slug`, `country`, `website_url` |
| **categories** | Vitamins, Protein, Probiotics, etc. | `name`, `slug`, `icon`, `sort_order` |
| **sources** | Testing labs (Labdoor, ConsumerLab, NSF, USP, Examine, Trustified, Informed Choice, Informed Sport, Trustpilot) | `name`, `slug`, `rating_scale`, `is_verified` |
| **supplements** | Products | `name`, `slug`, `brand_id` (FK), `category_id` (FK), `form`, `price_range`, `is_published`, `is_featured` |
| **ratings** | A score from a source about a supplement | `supplement_id` (FK ON DELETE CASCADE), `source_id` (FK ON DELETE RESTRICT), `score`, `max_score`, `verdict`, `report_url`, `buy_url` |

### Constraints + indexes

- **CHECK constraints**: `score >= 0`, `max_score > 0`, `score <= max_score`; `form` ∈ enum; `price_range` ∈ {$,$$,$$$,$$$$}.
- **Unique**: `(supplement_id, source_id)` — one rating per source per supplement.
- **Cascading delete**: deleting a supplement removes its ratings; sources/brands are protected (RESTRICT).
- **Composite indexes**: `(brand_id, category_id)`, `(is_featured, created_at)`, `(source_id, score)` for fast filter+sort.

### Aggregate score

Average of `(score / max_score) * 100` across all sources whose `is_active=true`. Inactive sources are excluded automatically — flip `sources.is_active=false` and that source's contribution drops out of every supplement's aggregate score immediately, with no cache flush.

### Dynamic visibility (everything is DB-driven)

Every supplement, brand, category, and source has an `is_active` (or `is_published`) flag. The frontend never has hardcoded source/category lists — they all come from the API.

```sql
-- Hide all Trustpilot data sitewide
UPDATE sources SET is_active=false WHERE slug='trustpilot';

-- Soft-delete a category (its supplements vanish from /browse)
UPDATE categories SET is_active=false WHERE slug='herbal';

-- Drop a counterfeit brand
UPDATE brands SET is_active=false WHERE slug='suspect-brand';

-- Unpublish a single supplement
UPDATE supplements SET is_published=false WHERE slug='thorne-zinc-picolinate-50';
```

A supplement is visible only if `is_published=true` AND its `brand.is_active=true` AND its `category.is_active=true`. Flipping any flag back to `true` instantly restores visibility — no rebuild, no redeploy. Counts on category cards, the trust strip, the footer, search results, and `/api/*` responses all recalculate from these flags on every request.

---

## Production Deployment

1. **Postgres**: set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db` (we use psycopg3, both dev and prod).
2. **Redis** (rate limiting): set `REDIS_URL=redis://host:6379/0` and install `requirements-prod.txt`.
3. **Migrations**: `flask db upgrade` on every deploy (CI step).
4. **WSGI**: `gunicorn -w 4 -b 0.0.0.0:5001 'app:create_app()'`.
5. **Frontend**: `npm run build` produces `frontend/dist/` — serve from any static CDN (Vercel, Cloudflare Pages, S3+CloudFront).
6. **CORS**: set `CORS_ORIGINS` env var to your frontend domain.

### Working with migrations

```bash
make migrate MSG="add brands.tier column"   # generate migration
make upgrade                                 # apply
make downgrade                               # rollback one
make db-shell                                # raw psql access
```

---

## Legal & Compliance Notes

This MVP follows the safer aggregator model:
- We **link out** to each lab's full report rather than republishing it.
- Buy buttons use `rel="noopener noreferrer sponsored nofollow"` (FTC-compliant affiliate disclosure).
- Disclaimers are present on every supplement page and in the footer.
- Source attribution is shown on every rating.
- We're **supplements-only** — prescription medications would require additional regulatory review.

Before scaling: review each source's ToS, secure affiliate program approvals, and confirm the use of brand names falls under nominative fair use in your jurisdiction.

---

## Roadmap

- User accounts (saved supplements, custom comparisons)
- Editorial reviews / blog
- Ingredient-level filtering (e.g., "vegan", "third-party tested only")
- Email alerts for new ratings on tracked supplements
- Background scrapers (with permission) or partner API integrations

---

## Admin Panel

A full admin panel lives at `/admin` (frontend) backed by `/api/admin/*` (backend). All admin routes require a bearer token issued by `POST /api/admin/auth/login`.

### Quick start

```bash
# After `make db-reset` (which now also runs the new admin-tables migration):
make seed-admin                 # interactive prompt
# or non-interactive:
ADMIN_USERNAME=admin ADMIN_PASSWORD='ChangeMe!2026' make seed-admin
```

Then open http://localhost:5173/admin/login and sign in.

### Role matrix

| Role | View | Create / Update | Delete | Manage admin users | View audit log |
|---|:-:|:-:|:-:|:-:|:-:|
| `readonly` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `editor` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `superadmin` | ✅ | ✅ | ✅ | ✅ | ✅ |

Roles are enforced both server-side (decorators on every endpoint — `@login_required`, `@require_editor`, `@require_superadmin`) and client-side (UI hides destructive controls + `ProtectedRoute` blocks superadmin pages). The server is the source of truth — the frontend hides actions only for ergonomics.

### What's in the panel

- **Dashboard** — counts (supplements/published/featured/unrated/new this week, brands, categories, sources, ratings, images), plus a feed of the last 20 admin actions.
- **Supplements** — paginated table with search by name/slug/brand/UPC, filter by brand / category / published-state. Full edit form (name, slug, brand, category, form, price, image URLs, ingredients, description, featured/published flags). Renaming a slug auto-creates a `supplement_aliases` row so old URLs still resolve.
- **Brands / Categories / Sources** — CRUD with active/hidden toggles and "in use" guards (deleting a brand/category in use returns 400 with a helpful message; sources can be deactivated to hide their ratings sitewide without losing data).
- **Ratings** — paginated, filterable by source. Type-ahead supplement picker for new ratings; full lab metadata (score, max_score, verdict, report URL, buy URL, batch number, tested-by lab, tested-on date).
- **Admin users** (superadmin only) — create/edit/disable/delete admins, change roles, reset passwords. Last-superadmin protection prevents you from locking yourself out.
- **Audit log** (superadmin only) — every CREATE/UPDATE/DELETE/LOGIN/LOGOUT/LOGIN_FAILED is recorded with actor, IP, user-agent, before/after diff. Filterable by action / entity type / user.

### Admin API endpoints

| Method | Path | Min. role |
|---|---|---|
| `POST` | `/api/admin/auth/login` | (anonymous) |
| `GET` | `/api/admin/auth/me` | `readonly` |
| `POST` | `/api/admin/auth/logout` | `readonly` |
| `POST` | `/api/admin/auth/change-password` | `readonly` (self) |
| `GET` | `/api/admin/dashboard/stats` · `/recent-activity` | `readonly` |
| `GET` | `/api/admin/{supplements\|brands\|categories\|sources\|ratings\|images}` | `readonly` |
| `POST`, `PATCH` | same | `editor` |
| `DELETE` | same | `superadmin` |
| `GET` | `/api/admin/users` | `readonly` (list) |
| `POST`, `PATCH`, `DELETE` | `/api/admin/users[/<id>]` | `superadmin` |
| `GET` | `/api/admin/audit` | `superadmin` |

### Auth implementation

- **Tokens** — `itsdangerous.URLSafeTimedSerializer` (already a Flask dep) signs `{uid, username, password_hash_suffix}` with `SECRET_KEY` and a 12-hour expiry. Changing a password invalidates all existing tokens. No new packages required.
- **Passwords** — `werkzeug.security.generate_password_hash` (PBKDF2-SHA256 by default). Min length 8.
- **Rate limiting** — `POST /auth/login` is capped at 10/min per IP via Flask-Limiter.
- **Storage** — token saved in `localStorage` under `hm_admin_token`; axios interceptor attaches it as `Authorization: Bearer <token>` and on 401 clears it and redirects to `/admin/login`.

### Adding a new admin user

```bash
# As a superadmin, via curl:
TOKEN=$(curl -s -X POST http://localhost:5001/api/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"ChangeMe!2026"}' | jq -r .token)

curl -X POST http://localhost:5001/api/admin/users \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"alice12345","role":"editor","email":"alice@example.com"}'
```

Or use the **Admin users** page at `/admin/users`.

### Production hardening checklist

1. Rotate the seeded `admin` password immediately on first login (Sign in → top-right user menu → settings → change password). The seeded password is just a bootstrap.
2. Set a strong `SECRET_KEY` env var in production (any token issued before a `SECRET_KEY` change becomes invalid — by design).
3. Serve the admin UI behind HTTPS only — bearer tokens in localStorage are XSS-vulnerable, same as any SPA. Keep `Content-Security-Policy` strict.
4. Restrict by IP/VPN at the edge (nginx/CloudFront) for `/api/admin/*` if you can — defense in depth.
5. Periodically review `/admin/audit` for suspicious LOGIN_FAILED bursts.
