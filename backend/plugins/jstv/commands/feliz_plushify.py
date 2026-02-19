import asyncio
import random

from app.connectors.warudo import QUIRKY_ANIMALS_MAP
from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Constants

QUIRKY_ANIMALS_LIST = tuple(QUIRKY_ANIMALS_MAP.items())


# ==============================================================================
# Commands

class PlushifyCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.plushify"
    title = "Plushify"
    description = "Plushify yourself into a random animal and sit on my head in Warudo"

    aliases = ("plush", "plushify")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.follower,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        animal, prop = random.choice(QUIRKY_ANIMALS_LIST)

        await asyncio.gather(
            ctx.connector.send_chat_reply(
                ctx.message,
                f"has been plushified into a {animal}",
                mention=True,
            ),
            ctx.connector.send_warudo("Plushify", [ctx.message.actorname, prop]),
        )

        return True
