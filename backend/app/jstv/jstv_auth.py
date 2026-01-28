import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.utils.datetime import utcnow

from app.db.database import get_async_db
from app.db.models import User, Channel, ChannelAccessToken

from . import jstv_web
from .jstv_error import JSTVTokenNotFound, JSTVTokenRefreshError, JSTVOAuthInitError, JSTVWebError

logger = logging.getLogger(__name__)

# NOTE:
#   Token initialization and refresh run in their own transaction and MUST commit even
#   if the caller fails. OAuth refresh tokens are single-use.


# ==============================================================================
# Config

TOKEN_REFRESH_LEEWAY_HOURS = 24


# ==============================================================================
# Functions

async def get_access_token(channel_id: str) -> str:
    async with get_async_db() as db:
        result = await db.execute(
            select(ChannelAccessToken)
            .join(Channel)
            .filter(Channel.channel_id == channel_id)
            .with_for_update()
        )

        token = result.scalar_one_or_none()
        if token is None:
            logger.warning(f"No access token for channel {channel_id}")
            raise JSTVTokenNotFound(
                f"No access token for channel {channel_id}, please initialize it first"
            )

        if token.expires_at - utcnow() < timedelta(hours=TOKEN_REFRESH_LEEWAY_HOURS):
            try:
                data = await jstv_web.fetch_refresh_access_token(token.get_refresh_token())
            except JSTVWebError as e:
                logger.error(f"Failed to refresh access token: {e}")
                raise JSTVTokenRefreshError("Failed to refresh access token") from e

            token.set_tokens(data.access_token, data.refresh_token, data.expires_at)
            await db.commit()

            return data.access_token

        return token.get_access_token()

async def init_access_token(auth_code: str) -> str:
    async with get_async_db() as db:
        # Get access token
        try:
            data = await jstv_web.fetch_init_access_token(auth_code)
        except JSTVWebError as e:
            logger.error(f"Failed to get access token: {e}")
            raise JSTVOAuthInitError("Access token initialization failed") from e

        # Get username from stream settings
        try:
            stream_settings = await jstv_web.fetch_stream_settings(data.access_token)
        except JSTVWebError as e:
            logger.error(f"Failed to get stream settings: {e}")
            raise JSTVOAuthInitError("Access token initialization failed") from e

        # Load or create channel
        db_channel = await db.scalar(
            select(Channel)
            .filter_by(channel_id=stream_settings.channel_id)
            .options(
                joinedload(Channel.owner),
                joinedload(Channel.access_token),
            )
        )

        is_new = db_channel is None
        if is_new:
            db_channel = Channel(channel_id=stream_settings.channel_id)
            db.add(db_channel)
            await db.flush()

        # Update or create user
        db_user = db_channel.owner if not is_new else None
        if db_user:
            db_user.username = stream_settings.username
        else:
            db_user = await db.scalar(select(User).filter_by(username=stream_settings.username))

            if db_user is None:
                db_user = User(username=stream_settings.username)
                db.add(db_user)
                await db.flush()

            db_channel.owner = db_user

        # Update or create token
        db_token = db_channel.access_token if not is_new else None
        if db_token is not None:
            db_token.set_tokens(data.access_token, data.refresh_token, data.expires_at)
        else:
            db_token = ChannelAccessToken(
                id=db_channel.id,
                access_token=data.access_token,
                refresh_token=data.refresh_token,
                expires_at=data.expires_at,
            )
            db.add(db_token)

        await db.commit()

        return data.access_token
