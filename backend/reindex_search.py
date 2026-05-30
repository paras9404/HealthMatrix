"""Bulk-rebuild the Meilisearch index from the database.

Run this once after first-time setup, or any time you've imported data via the
scraper / SQL scripts and want the search engine to catch up. Per-row admin
edits already keep the index in sync automatically.

Usage:
    cd backend
    source venv/bin/activate
    python reindex_search.py
"""
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.services import search_index


def main() -> int:
    app = create_app()
    with app.app_context():
        if not search_index.is_enabled():
            print("Meilisearch is not configured. Set MEILI_URL and MEILI_MASTER_KEY in .env.")
            return 1
        if not search_index.ensure_index_settings():
            print("Failed to apply index settings — check the engine is reachable.")
            return 2
        report = search_index.reindex_all()
        print(report)
        return 0 if report.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
