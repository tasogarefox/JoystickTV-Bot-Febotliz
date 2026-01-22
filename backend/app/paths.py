from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PARENT_DIR = BACKEND_DIR.parent

FRONTEND_DIR = PARENT_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"

TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
ICON_DIR = STATIC_DIR / "icons"
