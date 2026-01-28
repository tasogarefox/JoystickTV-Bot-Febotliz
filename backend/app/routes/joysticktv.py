import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse

from pydantic import BaseModel, field_validator

from app.jstv import jstv_web, jstv_auth
from app.jstv.jstv_error import JSTVAuthError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jstv", tags=["jstv"])


# ==============================================================================
# Schemas

class OAuthCallback(BaseModel):
    state: str
    code: str

    @field_validator("code", mode="before")
    def validate_code(cls, value) -> str:
        if not value:
            raise ValueError("Missing code")
        return value


# ==============================================================================
# Endpoints

@router.get("/install")
async def install():
    state = "abcfastapi123"
    redirect_url = f"{jstv_web.HOST}/api/oauth/authorize?client_id={jstv_web.CLIENT_ID}&scope=bot&state={state}"
    return RedirectResponse(url=redirect_url)

@router.get("/callback")
async def callback(
    data: OAuthCallback = Depends(),
):
    try:
        # Get access token
        await jstv_auth.init_access_token(data.code)
        return HTMLResponse("Bot started!")

    except JSTVAuthError as e:
        # Something went wrong with HTTP request
        logger.error("HTTP error in callback: %s", e)
        return HTMLResponse(f"Error fetching data from {jstv_web.HOST}", status_code=status.HTTP_502_BAD_GATEWAY)
