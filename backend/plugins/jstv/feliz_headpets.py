import asyncio

from app.connectors.warudo import WarudoConnector
from app.db.enums import AccessLevel
from app.handlers.jstv.base import JSTVHandlerContext
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings
from app.handlers.jstv.events import JSTVChatEmoteHandler, JSTVEventHandlerSettings


# ==============================================================================
# Constants

DEFAULT_CHAT_RESPONSE = "Pet that fluff-ball <3"

DEFAULT_WARUDO_ACTION = "HeadPets"

# Pairs of aliases and warudo action
# NOTE: Aliases must be in lowercase
ALIASESES_TO_WARUDO_ACTION_GROUPS = (
    (("pet", "pets", "pat", "pats"), DEFAULT_WARUDO_ACTION),
    (("pet1", "pets1", "pat1", "pats1"), "HeadPets1"),
    (("pet2", "pets2", "pat2", "pats2"), "HeadPets2"),
    (("pet3", "pets3", "pat3", "pats3"), "HeadPets3"),
)

# Map from alias to warudo action
ALIAS_TO_WARUDO_ACTION_MAP = dict(
    (k, v)
    for l, v in ALIASESES_TO_WARUDO_ACTION_GROUPS
    for k in l
)

# All aliases
ALIASES = tuple(
    alias
    for aliases, _ in ALIASESES_TO_WARUDO_ACTION_GROUPS
    for alias in aliases
)

# Emote codes
EMOTE_CODES = frozenset([":felizpet:"])


# ==============================================================================
# Helpers

async def do_headpets(
    ctx: JSTVHandlerContext,
    *,
    chat_response: str = DEFAULT_CHAT_RESPONSE,
    warudo_action: str = DEFAULT_WARUDO_ACTION,
) -> None:
    warudo = ctx.connector_manager.get(WarudoConnector)
    tasks = []

    if chat_response:
        tasks.append(ctx.reply(chat_response))

    if warudo and warudo_action:
        tasks.append(warudo.send_action(warudo_action))

    if tasks:
        await asyncio.gather(*tasks)


# ==============================================================================
# Commands

class HeadPetsCommand(JSTVCommand):
    key = "feliz.headpets"
    title = "HeadPets"
    description = "Pet that fluff-ball in Warudo <3"

    settings = JSTVCommandSettings(
        aliases = ALIASES,
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        warudo_action = ALIAS_TO_WARUDO_ACTION_MAP.get(
            ctx.alias.casefold(),
            DEFAULT_WARUDO_ACTION,

        )
        await do_headpets(ctx, warudo_action=warudo_action)
        return True


# ==============================================================================
# Event Handlers

class HeadPetsEmoteHandler(JSTVChatEmoteHandler):
    key = HeadPetsCommand.key + ".emote"
    title = HeadPetsCommand.title
    description = HeadPetsCommand.description
    priority = 0

    emote_codes = EMOTE_CODES

    settings = JSTVEventHandlerSettings()

    @classmethod
    async def handle_emote(cls, ctx, emote) -> bool:
        await do_headpets(ctx)
        return False
