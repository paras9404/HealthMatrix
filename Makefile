# HealthMatrix — dev workflow
# All Python deps live in backend/venv (self-contained, never pollutes global Python).
# All Node deps live in frontend/node_modules.
# Both are gitignored.

.PHONY: help install install-backend install-frontend \
        backend frontend dev \
        db-up db-down db-status db-shell db-reset db-create db-drop \
        migrate upgrade downgrade seed seed-admin reset-db fetch-data import-trustified import-labdoor import-unboxhealth \
        lock freeze status clean

PYTHON := python3
VENV := backend/venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
FLASK := cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/flask

PG_BIN := /opt/homebrew/opt/postgresql@16/bin
PG_DB := healthmatrix_dev

help:
	@echo "HealthMatrix dev commands:"
	@echo ""
	@echo "  Setup:"
	@echo "    make install        — set up backend venv + frontend node_modules"
	@echo ""
	@echo "  Run:"
	@echo "    make backend        — Flask API on :5001"
	@echo "    make frontend       — Vite dev server on :5173"
	@echo ""
	@echo "  Database:"
	@echo "    make db-up          — start Postgres (Homebrew service)"
	@echo "    make db-down        — stop Postgres"
	@echo "    make db-status      — show service status"
	@echo "    make db-shell       — open psql shell on healthmatrix_dev"
	@echo "    make db-create      — create healthmatrix_dev database"
	@echo "    make db-drop        — drop healthmatrix_dev database"
	@echo "    make db-reset       — drop + recreate + migrate + seed"
	@echo ""
	@echo "  Migrations:"
	@echo "    make migrate MSG='description' — generate a new migration"
	@echo "    make upgrade        — apply pending migrations"
	@echo "    make downgrade      — roll back one migration"
	@echo "    make seed           — populate db with sample data"
	@echo "    make seed-admin     — create initial superadmin (uses ADMIN_USERNAME/ADMIN_PASSWORD env or prompts)"
	@echo "    make fetch-data     — download real images + DSLD label data"
	@echo "    make import-trustified [LIMIT=N] — scrape trustified.in /passandfail products"
	@echo "    make import-labdoor [LIMIT=N]    — scrape labdoor.com rankings + reviews"
	@echo "    make import-unboxhealth [LIMIT=N] — scrape unboxhealth.in lab-tested supplement reviews"
	@echo ""
	@echo "  Tooling:"
	@echo "    make lock           — refresh requirements.lock.txt"
	@echo "    make freeze         — list installed Python packages"
	@echo "    make status         — show env summary"
	@echo "    make clean          — remove venv, node_modules, db dump"

# ---------- Setup ----------

install: install-backend install-frontend
	@echo ""
	@echo "✓ Setup complete."
	@echo "  1. make db-up     (start Postgres)"
	@echo "  2. make db-reset  (create db, migrate, seed)"
	@echo "  3. make backend   (terminal 1)"
	@echo "  4. make frontend  (terminal 2)"

install-backend:
	@echo "→ Creating backend venv at $(VENV)..."
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@$(PIP) install --quiet --upgrade pip
	@echo "→ Installing Python deps into venv..."
	@$(PIP) install --quiet -r backend/requirements.txt
	@test -f backend/.env || cp backend/.env.example backend/.env
	@echo "✓ Backend ready ($(VENV))"

install-frontend:
	@echo "→ Installing frontend deps..."
	@cd frontend && npm install --silent
	@echo "✓ Frontend ready (frontend/node_modules)"

# ---------- Run ----------

backend:
	@echo "→ Starting Flask API on http://localhost:5001"
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python run.py

frontend:
	@echo "→ Starting Vite dev server on http://localhost:5173"
	@cd frontend && npm run dev

dev:
	@echo "Run in two terminals:"
	@echo "  make backend"
	@echo "  make frontend"

# ---------- Database (Postgres via Homebrew) ----------

db-up:
	@brew services start postgresql@16 > /dev/null
	@sleep 2
	@$(PG_BIN)/pg_isready -h localhost && echo "✓ Postgres running on :5432"

db-down:
	@brew services stop postgresql@16 > /dev/null && echo "✓ Postgres stopped"

db-status:
	@brew services list | grep postgresql@16 || true
	@$(PG_BIN)/pg_isready -h localhost 2>&1 | sed 's/^/  /'

db-create:
	@$(PG_BIN)/psql -h localhost -U $$USER -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$(PG_DB)'" | grep -q 1 \
	  && echo "  (already exists)" \
	  || $(PG_BIN)/psql -h localhost -U $$USER -d postgres -c "CREATE DATABASE $(PG_DB);"

db-drop:
	@echo "→ Dropping $(PG_DB)..."
	@$(PG_BIN)/psql -h localhost -U $$USER -d postgres -c "DROP DATABASE IF EXISTS $(PG_DB);"

db-shell:
	@$(PG_BIN)/psql -h localhost -d $(PG_DB)

db-reset: db-drop db-create upgrade seed
	@echo "✓ DB fully reset."

# ---------- Migrations ----------

migrate:
	@$(FLASK) db migrate -m "$(MSG)"

upgrade:
	@$(FLASK) db upgrade

downgrade:
	@$(FLASK) db downgrade

seed:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python seed.py

seed-admin:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python seed_admin.py

fetch-data:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python fetch_real_data.py

import-trustified:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python import_trustified.py $(if $(LIMIT),--limit $(LIMIT),)

import-labdoor:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python import_labdoor.py $(if $(LIMIT),--limit $(LIMIT),)

import-unboxhealth:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python import_unboxhealth.py $(if $(LIMIT),--limit $(LIMIT),)

merge-duplicates:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python merge_duplicates.py $(if $(DRY),--dry-run,)

canonicalize-brands:
	@cd backend && set -a && . ./.env && set +a && ../$(VENV)/bin/python canonicalize_brands.py $(if $(DRY),--dry-run,)

reset-db: db-reset

# ---------- Tooling ----------

lock:
	@$(PIP) freeze > backend/requirements.lock.txt
	@echo "✓ Locked $$(wc -l < backend/requirements.lock.txt | tr -d ' ') packages → backend/requirements.lock.txt"

freeze:
	@$(PIP) freeze

status:
	@echo "Venv:      $$(pwd)/$(VENV)"
	@echo "Python:    $$($(PY) --version 2>&1)"
	@echo "Pip:       $$($(PIP) --version | cut -d' ' -f1-2)"
	@echo "Packages:  $$($(PIP) list 2>/dev/null | tail -n +3 | wc -l | tr -d ' ') Python pkgs installed"
	@if [ -d frontend/node_modules ]; then \
	  echo "Frontend:  $$(ls frontend/node_modules | wc -l | tr -d ' ') node_modules"; \
	else \
	  echo "Frontend:  not installed"; \
	fi
	@echo "Postgres:  $$($(PG_BIN)/pg_isready -h localhost 2>&1)"

clean:
	@echo "→ Removing venv, node_modules..."
	@rm -rf $(VENV) frontend/node_modules
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleaned. Run 'make install' to start fresh."
	@echo "  (Postgres data is preserved. Run 'make db-drop' to wipe DB too.)"
