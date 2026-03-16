from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class PointsCommand(JSTVCommand):
    key = "core.watch_streak"
    title = "Watch Streak"
    description = "Check your watch streak"

    settings = JSTVCommandSettings(
        aliases = ("streak", "watchstreak"),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.reply((
            f"has watched {ctx.viewer.cur_watch_streak} streams in a row"
        ), mention=True)

        return True
