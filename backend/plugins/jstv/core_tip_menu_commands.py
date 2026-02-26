import re

from app.events import jstv as evjstv
from app.handlers.jstv.commands import db as dbcmdhandlers
from app.handlers.jstv.events import JSTVEventHandler, JSTVEventHandlerSettings


# ==============================================================================
# Constants

RE_COMMAND = re.compile(r"(?:^|[^!]*\s)!(\w+)(?:\s+(.*))?$")


# ==============================================================================
# Event Handlers

class TipMenuCommandsEventHandler(JSTVEventHandler[evjstv.JSTVTipped]):
    key = "core.tip_menu_commands"
    title = "Tip Menu Commands"
    description = "If a tip menu item contains a command, execute it"
    priority = 10000

    msgtypes = (evjstv.JSTVTipped,)

    settings = JSTVEventHandlerSettings()

    @classmethod
    async def handle(cls, ctx) -> bool:
        tip_menu_item = ctx.message.metadata.tip_menu_item
        if not tip_menu_item:
            return False

        match = RE_COMMAND.fullmatch(tip_menu_item)
        if not match:
            return False

        alias: str = match.group(1)
        argument: str = (match.group(2) or "").strip()

        cmd_result = await dbcmdhandlers.invoke_command(
            ctx.db,
            channel=ctx.channel or ctx.message.channelId,
            user=ctx.user or ctx.message.actorname,
            viewer=ctx.viewer,
            connector=ctx.connector,
            message=ctx.message,
            alias=alias,
            argument=argument,
            check_permissions=False,
            check_cooldown=False,
            pay=False,
        )

        if cmd_result is None:
            await ctx.reply(f"ERROR: tip command not found: {alias}")
            return False

        return False
