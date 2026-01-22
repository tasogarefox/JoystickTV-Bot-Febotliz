from fastapi import APIRouter
from . import api, ws, icon, joysticktv

router = APIRouter(prefix="", tags=["root"])

router.include_router(api.router)
router.include_router(ws.router)
router.include_router(icon.router)
router.include_router(joysticktv.router)

__all__ = ["router"]
