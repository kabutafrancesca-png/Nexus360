import os
from dotenv import load_dotenv

load_dotenv()

# Resolve the repo root (two levels up from this file: nexus360/nexus360/config.py)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_DB  = os.path.join(_BASE_DIR, "db", "nexus360_local.sqlite3")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    # If DATABASE_URL is not set (Supabase not configured yet),
    # fall back to a local SQLite file so the app still runs.
    DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{_LOCAL_DB}"

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB uploads
