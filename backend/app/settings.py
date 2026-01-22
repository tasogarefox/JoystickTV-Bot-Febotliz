# Load environment variables from .env file before anything else
from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
import os
import logging


# ==============================================================================
# Helper functions

def getenv_bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true")

def getenv_list(key: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(key, default).split(",") if item.strip())

def getenv_log_level(key: str, default: int) -> int:
    name = os.getenv(key, "")
    return logging.getLevelNamesMapping().get(name.upper(), logging.NOTSET) or default


# ==============================================================================
# Settings

# Basic app settings
APP_NAME = os.getenv("APP_NAME", "Febotliz")
APP_SLUG = os.getenv("APP_SLUG", "febotliz")
PRODUCTION = getenv_bool("PRODUCTION", "0")
DEBUG = getenv_bool("DEBUG", "0")
FRONTEND_BASE_URL = "/app/"

# Server settings
SERVER_HOST = os.getenv("SERVER_HOST", "http://localhost")
SERVER_PORT = int(os.getenv("SERVER_PORT", "29392"))
SERVER_STATIC_PATH = os.getenv("SERVER_STATIC_PATH", "/static")

# CORS
CORS_ALLOW_ORIGINS = getenv_list("CORS_ALLOW_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173, http://localhost:29392, http://127.0.0.1:29392")
CORS_ALLOW_METHODS = getenv_list("CORS_ALLOW_METHODS", "*")
CORS_ALLOW_HEADERS = getenv_list("CORS_ALLOW_HEADERS", "*")

# Encryption settings
FERNET_KEY = os.getenv("FERNET_KEY", "")
if not FERNET_KEY:
    raise RuntimeError("You must set a strong FERNET_KEY!")
SECRET_KEY = os.getenv("SECRET_KEY", "")
if PRODUCTION and not SECRET_KEY:
    raise RuntimeError("You must set a strong SECRET_KEY in production!")
TOKEN_ALGORITHM = os.getenv("TOKEN_ALGORITHM", "HS256")

# Logging settings
LOG_LEVEL = getenv_log_level("LOG_LEVEL", logging.DEBUG if DEBUG else logging.INFO)
LOG_DIR = Path(os.getenv("LOG_DIR", "logs")).resolve()
LOG_FILE = LOG_DIR / "app.log"

# Database settings
DATABASE_DIR = Path(os.getenv("DATABASE_DIR", "database")).resolve()
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATABASE_DIR / 'app.db'}")

# Connector settings
MAX_INIT_ATTEMPTS = int(os.getenv("MAX_INIT_ATTEMPTS", 6))
MAX_RECONNECT_DELAY = int(os.getenv("MAX_RECONNECT_DELAY", 60))
