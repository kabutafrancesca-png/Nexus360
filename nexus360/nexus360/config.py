import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    DATABASE_URL = os.getenv("DATABASE_URL")
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB uploads
