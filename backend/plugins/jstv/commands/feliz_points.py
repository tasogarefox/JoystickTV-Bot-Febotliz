from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings

class PointsCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.points"
    title = "Points"
    description = "Check your points"

    aliases = ("points", "p")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_chat_reply(
            ctx.message,
            f"You have {int(ctx.viewer.points)} points",
            whisper=True,
        )

        return True
