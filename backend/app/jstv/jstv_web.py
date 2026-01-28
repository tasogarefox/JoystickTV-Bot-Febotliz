import os
import asyncio
import logging
import httpx
import base64
from datetime import datetime

from pydantic import BaseModel, Field

from .jstv_error import JSTVWebError

logger = logging.getLogger(__name__)

semaphore = asyncio.Semaphore(10)  # Limit concurrent web requests


# ==============================================================================
# Config

HOST = os.getenv("JOYSTICKTV_HOST")
WS_HOST = os.getenv("JOYSTICKTV_API_HOST")
CLIENT_ID = os.getenv("JOYSTICKTV_CLIENT_ID")
CLIENT_SECRET = os.getenv("JOYSTICKTV_CLIENT_SECRET")
assert HOST, "Missing environment variable: JOYSTICKTV_HOST"
assert WS_HOST, "Missing environment variable: JOYSTICKTV_API_HOST"
assert CLIENT_ID, "Missing environment variable: JOYSTICKTV_CLIENT_ID"
assert CLIENT_SECRET, "Missing environment variable: JOYSTICKTV_CLIENT_SECRET"

ACCESS_TOKEN = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode("ascii")).decode()
GATEWAY_IDENTIFIER = '{"channel":"GatewayChannel"}'

TOKEN_URL = f"{HOST}/api/oauth/token"

WEB_TIMEOUT = 10


# ==============================================================================
# Schemas

class AccessData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_at: datetime = Field(alias="expires_in")  # NOTE: This is infact an absolute timestamp

class StreamSettings(BaseModel):
    username: str
    stream_title: str | None
    chat_welcome_message: str | None
    banned_chat_words: tuple[str, ...]
    device_active: bool
    photo_url: str | None
    live: bool
    number_of_followers: int
    channel_id: str


# ==============================================================================
# Functions

async def fetch_init_access_token(auth_code: str) -> AccessData:
    params = {
        "redirect_uri": "unused",
        "code": auth_code,
        "grant_type": "authorization_code",
    }

    headers = {
        "Authorization": f"Basic {ACCESS_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded",
        # "X-JOYSTICK-STATE": "abcflask123",
        "Accept": "application/json",
    }

    try:
        async with semaphore, httpx.AsyncClient(timeout=WEB_TIMEOUT) as client:
            response = await client.post(TOKEN_URL, data=params, headers=headers)
            response.raise_for_status()
            return AccessData.model_validate(response.json())
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error while getting access token: %s", e.response.text)
        raise JSTVWebError("HTTP error while getting access token") from e
    except httpx.RequestError as e:
        logger.error("Network error while getting access token: %s", e)
        raise JSTVWebError("Network error while getting access token") from e

async def fetch_refresh_access_token(refresh_token: str) -> AccessData:
    params = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    headers = {
        "Authorization": f"Basic {ACCESS_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded",
        # "X-JOYSTICK-STATE": "abcflask123",
        "Accept": "application/json",
    }

    try:
        async with semaphore, httpx.AsyncClient(timeout=WEB_TIMEOUT) as client:
            response = await client.post(TOKEN_URL, data=params, headers=headers)
            response.raise_for_status()
            return AccessData.model_validate(response.json())
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error while refreshing access token: %s", e.response.text)
        raise JSTVWebError("HTTP error while refreshing access token") from e
    except httpx.RequestError as e:
        logger.error("Network error while refreshing access token: %s", e)
        raise JSTVWebError("Network error while refreshing access token") from e

async def fetch_stream_settings(access_token: str) -> StreamSettings:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    url = f"{HOST}/api/users/stream-settings"

    try:
        async with semaphore, httpx.AsyncClient(timeout=WEB_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return StreamSettings.model_validate(response.json())
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error while fetching stream settings: %s", e.response.text)
        raise JSTVWebError("HTTP error while fetching stream settings") from e
    except httpx.RequestError as e:
        logger.error("Network error while fetching stream settings: %s", e)
        raise JSTVWebError("Network error while fetching stream settings") from e
