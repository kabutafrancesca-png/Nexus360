"""Database helper — works with both Postgres (Supabase) and local SQLite.

The driver is chosen automatically from DATABASE_URL:
  postgresql://...  or  postgres://...  → psycopg2  (Supabase / local Postgres)
  sqlite:///...                         → sqlite3   (local fallback, no install needed)

Usage in any route (identical regardless of backend):
    from app.db import query_all, query_one, execute

    rows = query_all("SELECT * FROM accounts WHERE status = ?", ("active",))
    row  = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    new  = execute("INSERT INTO leads (company_name) VALUES (?) RETURNING id", ("Acme",))

IMPORTANT — use ? for every placeholder, not %s.
db.py translates ? → %s automatically when talking to Postgres.
"""
import sqlite3
import re
from flask import current_app, g


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _pg_sql(sql: str) -> str:
    """Translate ?-style placeholders to %s for psycopg2."""
    return sql.replace("?", "%s")


def _sqlite_path(url: str) -> str:
    """Extract the file path from  sqlite:///path/to/file.sqlite3"""
    return re.sub(r"^sqlite:///", "", url)


# ---------------------------------------------------------------------------
# Connection management  (one connection per Flask request, stored in g)
# ---------------------------------------------------------------------------

def get_conn():
    if "db" not in g:
        url = current_app.config["DATABASE_URL"]
        if _is_sqlite(url):
            path = _sqlite_path(url)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row   # rows behave like dicts
            # Enable foreign-key enforcement (off by default in SQLite)
            conn.execute("PRAGMA foreign_keys = ON")
            g.db = conn
            g.db_sqlite = True
        else:
            import psycopg2
            import psycopg2.extras
            g.db = psycopg2.connect(url)
            g.db_sqlite = False
    return g.db


def close_conn(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()
    g.pop("db_sqlite", None)


def init_app(app):
    app.teardown_appcontext(close_conn)


# ---------------------------------------------------------------------------
# Public query helpers
# ---------------------------------------------------------------------------

def query_all(sql: str, params=None):
    """Run a SELECT and return a list of row-dicts."""
    conn = get_conn()
    params = params or ()

    if g.get("db_sqlite"):
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    else:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_pg_sql(sql), params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.rollback()   # release read transaction
        return rows


def query_one(sql: str, params=None):
    """Run a SELECT and return the first row-dict, or None."""
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=None):
    """INSERT / UPDATE / DELETE.
    Add  RETURNING id  (Postgres) or omit it (SQLite — last_insert_rowid used).
    Always returns a dict of the affected/inserted row, or None.
    """
    conn = get_conn()
    params = params or ()

    if g.get("db_sqlite"):
        # SQLite doesn't support RETURNING — strip it and fetch by rowid
        clean_sql = re.sub(r'\s+RETURNING\s+\S+', '', sql, flags=re.IGNORECASE).strip()
        cur = conn.execute(clean_sql, params)
        conn.commit()
        if cur.lastrowid:
            # Find the table name so we can fetch the new row back
            m = re.search(r'(?:INTO|UPDATE)\s+(\w+)', clean_sql, re.IGNORECASE)
            if m:
                row = conn.execute(
                    f"SELECT * FROM {m.group(1)} WHERE rowid = ?", (cur.lastrowid,)
                ).fetchone()
                return dict(row) if row else None
        return None
    else:
        import psycopg2.extras
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(_pg_sql(sql), params)
                result = dict(cur.fetchone()) if cur.description else None
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
