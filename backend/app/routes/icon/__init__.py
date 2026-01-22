from fastapi import APIRouter
from . import toy

router = APIRouter(prefix="/icon", tags=["icon"])

router.include_router(toy.router)

__all__ = ["router"]
