from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app import paths

router = APIRouter(prefix="/toy", tags=["toy"])

FOLDER = paths.ICON_DIR / "toys"
DEFAULT_FILE = FOLDER / "default.png"
FILE_EXTENSIONS = (".png", ".svg", ".webp")


# ==============================================================================
# Endpoints

@router.get("/{filename}")
def get_icon(filename: str):
    filename = Path(filename).name

    for ext in FILE_EXTENSIONS:
        try:
            path = (FOLDER / f"{filename}{ext}").resolve()
        except Exception:
            continue

        if FOLDER in path.parents and path.is_file():
            return FileResponse(path)

    return FileResponse(DEFAULT_FILE)
