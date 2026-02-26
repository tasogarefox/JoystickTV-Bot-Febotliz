
from dataclasses import dataclass

from app.settings import POINTS_NAME
from app.jstv import jstv_db
from app.db.models import Viewer
from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

@dataclass(slots=True)
class Cache:
    target_name: str | None
    target: Viewer | None

class PointsCommand(JSTVCommand[None, Cache]):
    key = "core.points"
    title = "Points"
    description = "Check your points"

    settings = JSTVCommandSettings(
        aliases = ("points", "p"),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    async def prepare(cls, ctx) -> bool:
        target_name, _, argument = ctx.argument.partition(" ")

        if target_name.startswith("@"):
            target_name = target_name[1:]

        if not target_name:
            target_name = target = None

        elif ctx.viewer.access_level < AccessLevel.moderator:
            await ctx.reply((
                "You must be a moderator to check someone else's points"
            ), mention=True)
            return False

        else:
            target = await jstv_db.get_viewer(ctx.db, ctx.channel, target_name)
            if target is None:
                await ctx.reply(f"Viewer @{target_name} not found", mention=True)
                return False

        ctx.set_cache(Cache(
            target_name=target_name,
            target=target,
        ))

        return True

    @classmethod
    async def handle(cls, ctx) -> bool:
        assert ctx.cache
        target_name = ctx.cache.target_name
        target = ctx.cache.target

        if target is None:
            msg = f"You have {int(ctx.viewer.points):,} {POINTS_NAME}"
        else:
            msg = f"Viewer @{target_name} has {int(target.points):,} {POINTS_NAME}"

        await ctx.reply(msg, whisper=True)
        return True
