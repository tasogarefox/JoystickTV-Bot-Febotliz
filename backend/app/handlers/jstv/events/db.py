import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.connector import BaseConnector
from app.events import jstv as evjstv
from app.jstv import jstv_db
from app.db.models import (
    Channel, User, Viewer,
    COMMAND_TAGS_DISABLED,
)

from .handler import JSTVEventHandler, JSTVEventHandlerContext

logger = logging.getLogger(__name__)


# ==============================================================================
# Interface

async def invoke_events(
    db: AsyncSession,
    channel: Channel | str,
    user: User | str | None,
    viewer: Viewer | None,
    connector: BaseConnector,
    message: evjstv.JSTVMessage,
) -> bool | None:
    from app.connectors.joysticktv import JoystickTVConnector

    jstv = connector.manager.get(JoystickTVConnector)
    if jstv is None:
        return None

    async with db.begin_nested():
        if not isinstance(channel, Channel):
            channel = await jstv_db.get_or_create_channel(db, channel)

        if user is not None and not isinstance(user, User):
            user = await jstv_db.get_or_create_user(db, user)

        if viewer is not None and not isinstance(viewer, Viewer):
            viewer = await jstv_db.get_or_create_viewer(db, channel, user)

        retval: bool | None = None
        for handler in JSTVEventHandler.iter_handlers_by_type(type(message)):
            if handler.disabled:
                continue

            if any(tag in COMMAND_TAGS_DISABLED for tag in handler.tags):
                continue

            settings = handler.settings

            ctx = JSTVEventHandlerContext(
                settings=settings,
                connector=connector,
                message=message,
                db=db,
                channel=channel,
                user=user,
                viewer=viewer,
            )

            logger.debug("Invoking event handler %r", handler.key)

            try:
                retval = await handler.handle(ctx)

                if retval:
                    break

            except Exception as e:
                logger.exception("Error handling event %r: %s", handler.key, e)
                await jstv.send_chat(channel.channel_id, (
                    f"Error handling event {handler.key}. See logs for details"
                ))

        return retval
