from fastapi import APIRouter
from . import vibegraph

router = APIRouter(prefix="/ws", tags=["ws", "WebSocket"])

router.include_router(vibegraph.router)

__all__ = ["router"]
