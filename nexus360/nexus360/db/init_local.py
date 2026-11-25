"""Bootstrap a local SQLite database in one command.

Run this once after cloning the repo (no Supabase / Postgres needed):
    python db/init_local.py

What it does:
    1. Creates  db/nexus360_local.sqlite3
    2. Applies  db/schema_sqlite.sql  (all tables, indexes, views)
    3. Runs     db/seed.py            (demo accounts, users, contracts …)

Re-running is safe — schema uses IF NOT EXISTS and seed uses INSERT OR IGNORE.
To start completely fresh, delete nexus360_local.sqlite3 then re-run.
"""
import os
import sys
import sqlite3
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_DB   = os.path.join(_HERE, "nexus360_local.sqlite3")
_SQL  = os.path.join(_HERE, "schema_sqlite.sql")
_SEED = os.path.join(_HERE, "seed.py")


def apply_schema():
    print(f"Applying schema to {_DB} …")
    with open(_SQL, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = sqlite3.connect(_DB)
    conn.executescript(sql)
    conn.commit()
    conn.close()
    print("  Schema applied.")


def run_seed():
    print("Seeding demo data …")
    result = subprocess.run(
        [sys.executable, _SEED],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")
    if result.returncode != 0:
        print("  ERROR during seed:")
        print(result.stderr)
        sys.exit(1)


def main():
    print("=" * 55)
    print("  Nexus 360 — local SQLite setup")
    print("=" * 55)

    if os.path.exists(_DB):
        print(f"\nDatabase already exists at:\n  {_DB}")
        answer = input("Re-initialise? This will keep existing data (safe). [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    apply_schema()
    run_seed()

    print()
    print("All done!  Start the app with:")
    print("    python run.py")
    print()
    print("Demo logins (password: nexus123):")
    print("    admin@infratel.test    — Admin")
    print("    manager@infratel.test  — Sales Manager")
    print("    am@infratel.test       — Account Manager")
    print("    rep@infratel.test      — Sales Rep")
    print("    exec@infratel.test     — Executive")
    print()
    print("To connect to Supabase instead, add DATABASE_URL to your .env file.")
    print("=" * 55)


if __name__ == "__main__":
    main()
