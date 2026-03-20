from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class PointsCommand(JSTVCommand):
    key = "core.watch_time"
    title = "Watch Time"
    description = "Check your total watch time"

    settings = JSTVCommandSettings(
        aliases = ("watchtime",),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        tmin, tsec = divmod(int(ctx.viewer.total_watch_time), 60)
        thour, tmin = divmod(tmin, 60)
        tday, thour = divmod(thour, 24)

        await ctx.reply((
            f"has been watching {tday:,d}d {thour:d}h {tmin:d}m total"
        ), mention=True)

        return True
