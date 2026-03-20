import asyncio

from app.settings import NSFW_ENABLED
from app.connectors.warudo import WarudoConnector
from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class StretchCommand(JSTVCommand):
    key = "feliz.stretchies"
    title = "Stretchies"
    description = "Tell me to do stretchies <3"

    settings = JSTVCommandSettings(
        aliases = ("stretchies", "stretch"),
        min_access_level=AccessLevel.viewer,
        channel_cooldown=60 * 15,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        warudo = ctx.connector_manager.get(WarudoConnector)
        tasks = []

        if not NSFW_ENABLED:
            msg = "Stretchies time!"
        else:
            msg = "Stretchies time! Unfold those foxy folds!"

        tasks.append(ctx.reply(msg))

        if warudo:
            tasks.append(warudo.send_action("Stretchies"))

        if tasks:
            await asyncio.gather(*tasks)

        return True
