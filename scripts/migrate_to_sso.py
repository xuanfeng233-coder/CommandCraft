"""Migrate CommandCraft auth from local users to BraynLabs SSO.

This script:
1. Creates the sso_users table (if not exists)
2. Clears old auth_sessions (they reference users.id, not braynlabs_id)
3. Drops old tables no longer needed (users, email_verification_codes, email_send_rate, register_rate, sso_tickets)

Existing users will need to re-login via BraynLabs.

Usage:
    python scripts/migrate_to_sso.py [db_path]
    Default: on Docker it's /app/data/subscriptions.db
             locally it's ./data/subscriptions.db
"""

import sqlite3
import sys


def migrate(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=OFF")

    print(f"Migrating {db_path} ...")

    # 1. Create sso_users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sso_users (
            braynlabs_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT DEFAULT NULL,
            synced_at TEXT NOT NULL
        )
    """)
    print("  [OK] sso_users table ensured")

    # 2. Clear old auth_sessions
    try:
        cur = conn.execute("SELECT COUNT(*) FROM auth_sessions")
        count = cur.fetchone()[0]
        if count > 0:
            conn.execute("DELETE FROM auth_sessions")
            print(f"  [OK] Cleared {count} old auth sessions")
    except Exception:
        print("  [SKIP] No auth_sessions table found")

    # 3. Drop old tables
    for table in ["email_verification_codes", "email_send_rate", "register_rate", "sso_tickets", "users"]:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            print(f"  [OK] Dropped table: {table}")
        except Exception as e:
            print(f"  [WARN] Could not drop {table}: {e}")

    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    conn.close()
    print("Migration complete!")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "./data/subscriptions.db"
    migrate(path)
