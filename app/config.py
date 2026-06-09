import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///app.db")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
