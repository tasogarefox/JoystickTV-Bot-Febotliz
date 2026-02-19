import asyncio

from app.connectors.joysticktv import JoystickTVConnector
from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Constants

DEFAULT_CHAT_RESPONSE = "Pet that fluff-ball <3"

DEFAULT_WARUDO_ACTION = "HeadPets"

# Pairs of aliases and warudo action
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


# ==============================================================================
# Shared

async def do_headpets(
    connector: JoystickTVConnector,
    evmsg: evjstv.JSTVMessage,
    *,
    chat_response: str = DEFAULT_CHAT_RESPONSE,
    warudo_action: str = DEFAULT_WARUDO_ACTION,
) -> None:
    tasks = []

    if chat_response:
        tasks.append(connector.send_chat(evmsg.channelId, chat_response))

    if warudo_action:
        tasks.append(connector.send_warudo(warudo_action))

    if tasks:
        await asyncio.gather(*tasks)


# ==============================================================================
# Commands

class HeadPetsCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.headpets"
    title = "HeadPets"
    description = "Pet that fluff-ball in Warudo <3"

    aliases = ALIASES

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        warudo_action = ALIAS_TO_WARUDO_ACTION_MAP.get(ctx.alias, DEFAULT_WARUDO_ACTION)
        await do_headpets(ctx.connector, ctx.message, warudo_action=warudo_action)
        return True
