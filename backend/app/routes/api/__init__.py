from fastapi import APIRouter
from . import commands

router = APIRouter(prefix="/api", tags=["api"])

router.include_router(commands.router)

__all__ = ["router"]
