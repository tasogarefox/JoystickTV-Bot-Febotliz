import asyncio

from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class ViewerSignCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.clip"
    title = "Clip"
    description = "Create a clip by requesting OBS to save it's replay buffer"

    aliases = ("clip",)

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
        channel_cooldown=30,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await asyncio.gather(
            ctx.connector.talkto("OBS", "clip", None),
            ctx.connector.send_chat_reply(
                ctx.message,
                f"Creating a clip of the last 2 minutes",
            ),
        )

        return True
