from fastapi import APIRouter
# from . import ...

router = APIRouter(prefix="/api", tags=["api"])

# router.include_router(....router)

__all__ = ["router"]
