from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.commands import Command, CommandSettings, CommandContext
from app.connectors.joysticktv import JoystickTVConnector

class PointsCommand(Command):
    key = "feliz.points"
    title = "Points"
    description = "Check your points"

    aliases = ("points", "p")

    settings = CommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx: CommandContext) -> bool:
        if not isinstance(ctx.connector, JoystickTVConnector):
            return False
        if not isinstance(ctx.evmsg, evjstv.JSTVBaseChatMessage):
            return False

        await ctx.connector.send_chat_reply(
            ctx.evmsg,
            f"You have {int(ctx.viewer.points)} points",
            whisper=True,
        )

        return True
