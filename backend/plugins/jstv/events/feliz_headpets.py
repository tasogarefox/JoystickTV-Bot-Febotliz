from app.handlers.jstv.events import JSTVChatEmoteHandler, JSTVEventHandlerSettings

from ..commands.feliz_headpets import HeadPetsCommand, do_headpets


# ==============================================================================
# Constants

EMOTE_CODES = frozenset([":felizpet:"])


# ==============================================================================
# Hnadlers

class HeadPetsEmoteHandler(JSTVChatEmoteHandler):
    key = HeadPetsCommand.key + ".emote"
    title = HeadPetsCommand.title
    description = HeadPetsCommand.description

    emote_codes = EMOTE_CODES

    settings = JSTVEventHandlerSettings(
        priority=0,
    )

    @classmethod
    async def handle_emote(cls, ctx, emote) -> bool:
        await do_headpets(ctx.connector, ctx.message)
        return False
