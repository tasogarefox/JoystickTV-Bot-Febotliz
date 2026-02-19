from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class ViewerSignCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.viewersign"
    title = "ViewerSign"
    description = """Write a message to the "ViewerSign" in Warudo"""

    aliases = ("viewersign", "sign", "showsign")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.follower,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        if not ctx.message.botCommandArg:
            await ctx.connector.send_chat_reply(
                ctx.message,
                f"Usage: !{ctx.alias} <TEXT>",
                mention=True,
            )
            return True

        await ctx.connector.send_warudo("ViewerSign", ctx.message.botCommandArg)

        return True
