import asyncio

from app.settings import NSFW_ENABLED
from app.connectors.warudo import WarudoConnector
from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class HydrateCommand(JSTVCommand):
    key = "feliz.hydrate"
    title = "Hydrate"
    description = "Tell me to hydrate <3"

    settings = JSTVCommandSettings(
        aliases = ("hydrate", "water"),
        min_access_level=AccessLevel.viewer,
        channel_cooldown=60 * 5,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        warudo = ctx.connector_manager.get(WarudoConnector)
        tasks = []

        if not NSFW_ENABLED:
            msg = "Hydration time!"
        else:
            msg = "Drink up, Good Girl 💦"

        tasks.append(ctx.reply(msg))

        if warudo:
            tasks.append(warudo.send_action("Hydrate"))

        if tasks:
            await asyncio.gather(*tasks)

        return True
