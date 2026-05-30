"""Seed an initial superadmin account for the admin panel.

Reads ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD from the environment.
If the user already exists, this script no-ops (idempotent).

Usage:
    ADMIN_USERNAME=admin ADMIN_PASSWORD='ChangeMe!2026' python seed_admin.py
or with the make target:
    make seed-admin

Run after `flask db upgrade`.
"""
import os
import sys
import getpass

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import AdminUser, ROLE_SUPERADMIN


def main():
    username = (os.getenv("ADMIN_USERNAME") or "").strip().lower()
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower() or None
    password = os.getenv("ADMIN_PASSWORD") or ""

    app = create_app()
    with app.app_context():
        # Default username if none provided.
        if not username:
            username = "admin"

        existing = AdminUser.query.filter(db.func.lower(AdminUser.username) == username).first()
        if existing:
            print(f"✓ Admin user '{username}' already exists (id={existing.id}, role={existing.role}).")
            print("  Update credentials via the admin panel or directly in the DB.")
            return 0

        # Interactive password prompt if not supplied via env.
        if not password:
            if not sys.stdin.isatty():
                print("ERROR: ADMIN_PASSWORD env var is required when not running interactively.", file=sys.stderr)
                return 1
            print(f"Creating superadmin '{username}'.")
            while True:
                password = getpass.getpass("Password (min 8 chars): ")
                if len(password) < 8:
                    print("  Too short, try again.")
                    continue
                confirm = getpass.getpass("Confirm: ")
                if password != confirm:
                    print("  Passwords don't match, try again.")
                    continue
                break

        if len(password) < 8:
            print("ERROR: password must be at least 8 characters.", file=sys.stderr)
            return 1

        user = AdminUser(username=username, email=email, role=ROLE_SUPERADMIN, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"✓ Created superadmin '{user.username}' (id={user.id}).")
        if email:
            print(f"  Email: {email}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
