"""
admin.py  –  Manage admin credentials stored in MongoDB.

Usage
-----
  python admin.py                  # interactive: prompts for username & password
  python admin.py --migrate        # seed DB from ADMIN_USERNAME / ADMIN_PASSWORD_HASH in .env
  python admin.py --username bob   # set username non-interactively (still prompts for password)
"""

import sys
import os
import getpass
import argparse
import bcrypt
from dotenv import load_dotenv

# Make sure we can import project modules regardless of CWD
sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from database import get_admin_user, upsert_admin_user


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def migrate_from_env():
    """Seed the DB with credentials currently defined in .env."""
    username = os.getenv("ADMIN_USERNAME", "").strip()
    existing_hash = os.getenv("ADMIN_PASSWORD_HASH", "").strip()

    if not username or not existing_hash:
        print("[ERROR] ADMIN_USERNAME or ADMIN_PASSWORD_HASH not found in .env.")
        print("        Run without --migrate to set credentials interactively.")
        sys.exit(1)

    upsert_admin_user(username, existing_hash)
    print(f"[OK] Admin user '{username}' migrated from .env to database.")
    print("     You can now remove ADMIN_USERNAME and ADMIN_PASSWORD_HASH from .env.")


def set_credentials(username: str = None):
    """Interactively set (or update) admin credentials in the DB."""
    if not username:
        username = input("Enter admin username: ").strip()
    if not username:
        print("[ERROR] Username cannot be empty.")
        sys.exit(1)

    password = getpass.getpass(f"Enter new password for '{username}': ")
    confirm  = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("[ERROR] Passwords do not match.")
        sys.exit(1)
    if len(password) < 6:
        print("[ERROR] Password must be at least 6 characters.")
        sys.exit(1)

    password_hash = hash_password(password)
    upsert_admin_user(username, password_hash)
    print(f"[OK] Admin user '{username}' saved to database.")


def main():
    parser = argparse.ArgumentParser(description="Manage admin credentials in MongoDB")
    parser.add_argument("--migrate",  action="store_true",
                        help="Seed DB from ADMIN_USERNAME/ADMIN_PASSWORD_HASH in .env")
    parser.add_argument("--username", type=str, default=None,
                        help="Admin username (skips username prompt)")
    args = parser.parse_args()

    if args.migrate:
        migrate_from_env()
    else:
        set_credentials(username=args.username)

    # Verify the record exists
    stored_username = args.username or os.getenv("ADMIN_USERNAME", "admin")
    user = get_admin_user(stored_username) if not args.migrate else get_admin_user(
        os.getenv("ADMIN_USERNAME", "admin")
    )
    if user:
        print(f"[Verified] '{user['username']}' is now active in the database.")
    else:
        print("[WARNING] Could not verify the record. Check your MongoDB connection.")


if __name__ == "__main__":
    main()
