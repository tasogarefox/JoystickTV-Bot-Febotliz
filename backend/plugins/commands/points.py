from app.db.enums import CommandAccessLevel
from app.commands import Command, CommandSettings, CommandContext
from app.connectors.joysticktv import JoystickTVConnector

class PointsCommand(Command):
    key = "feliz.points"
    description = "Check your points"

    name = "Points"
    aliases = ("points", "p")

    settings = CommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx: CommandContext) -> bool:
        if not isinstance(ctx.connector, JoystickTVConnector):
            return False

        await ctx.connector.send_chat_reply(
            ctx.event,
            f"You have {int(ctx.viewer.points)} points",
            whisper=True,
        )

        return True
