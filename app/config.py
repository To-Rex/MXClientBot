import os
from pathlib import Path


def _load_dotenv():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///app.db")

# SQLite nisbiy yo'l ishga tushirilgan katalogga bog'liq bo'lib qolmasin:
# server boshqa cwd'dan ishga tushsa yangi bo'sh baza ochilib, foydalanuvchilar
# "ro'yxatdan o'tmagan" bo'lib qolardi. Nisbiy yo'lni loyiha ildiziga mahkamlaymiz.
_SQLITE_PREFIX = "sqlite+aiosqlite:///"
if DATABASE_URL.startswith(_SQLITE_PREFIX) and not DATABASE_URL.startswith(_SQLITE_PREFIX + "/"):
    _db_rel = DATABASE_URL[len(_SQLITE_PREFIX):]
    DATABASE_URL = _SQLITE_PREFIX + str((Path(__file__).resolve().parent.parent / _db_rel))
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
AUTH_API_BASE = os.getenv(
    "AUTH_API_BASE",
    "https://tashqisavdo-tashqi-savda-backend-dykybk-722d50-85-17-200-46.sslip.io/api/v1",
).rstrip("/")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "mx-bot-secret-key-change-in-production")

# Mahsulot katalogi keshi (soniya). 0 = kesh o'chirilgan.
# Buyurtma yaratish/tahrirlash/o'chirishda kesh avtomatik tozalanadi.
try:
    PRODUCTS_CACHE_TTL = int(os.getenv("PRODUCTS_CACHE_TTL", "30"))
except ValueError:
    PRODUCTS_CACHE_TTL = 30

# Eslatmalar (to'lov yaqinlashganda / kechikkanda) tekshiruv oralig'i, soniya. 0 = o'chirilgan.
try:
    REMINDER_INTERVAL = int(os.getenv("REMINDER_INTERVAL", "3600"))
except ValueError:
    REMINDER_INTERVAL = 3600
