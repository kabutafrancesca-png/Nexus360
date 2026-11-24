"""Tiny Postgres helper. Works with Supabase or local Postgres.

Usage in any route:
    from app.db import query_all, query_one, execute

    rows = query_all("SELECT * FROM accounts WHERE status = %s", ("active",))
    row  = query_one("SELECT * FROM accounts WHERE id = %s", (account_id,))
    new  = execute("INSERT INTO leads (company_name) VALUES (%s) RETURNING *", ("Acme",))
"""
import psycopg2
import psycopg2.extras
from flask import current_app, g


def get_conn():
    if "db" not in g:
        g.db = psycopg2.connect(current_app.config["DATABASE_URL"])
    return g.db


def close_conn(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_conn)


def query_all(sql, params=None):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
    conn.rollback()  # read-only, release the transaction
    return rows


def query_one(sql, params=None):
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    """INSERT/UPDATE/DELETE. Add RETURNING * to get the row back."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            result = cur.fetchone() if cur.description else None
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
