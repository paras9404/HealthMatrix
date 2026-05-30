"""Set logo_url for each Source to point to the locally-stored image.

Logos live in backend/static/images/sources/<slug>.png and are served
at /static/images/sources/<slug>.png by Flask.

Run: python set_source_logos.py
"""
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text

from app import create_app
from app.extensions import db

LOGO_DIR = Path(__file__).resolve().parent / "static" / "images" / "sources"


def main():
    app = create_app()
    with app.app_context():
        rows = db.session.execute(text("SELECT id, slug FROM sources")).fetchall()
        updated = 0
        for source_id, slug in rows:
            file_path = LOGO_DIR / f"{slug}.png"
            if not file_path.exists():
                print(f"skip {slug}: no file at {file_path}")
                continue
            url = f"/static/images/sources/{slug}.png"
            db.session.execute(
                text("UPDATE sources SET logo_url = :url WHERE id = :id"),
                {"url": url, "id": source_id},
            )
            updated += 1
            print(f"set  {slug} -> {url}")
        db.session.commit()
        print(f"done: updated {updated} source(s)")


if __name__ == "__main__":
    main()
