from app.db.enums import AccessLevel
from app.handlers.jstv.commands import (
    db as dbcmdhandlers, JSTVCommand, JSTVCommandSettings,
)


# ==============================================================================
# Commands

class AliasesCommand(JSTVCommand):
    key = "core.commands.aliases"
    title = "Aliases Command"
    description = "List command aliases"

    settings = JSTVCommandSettings(
        aliases = ("aliases", "alias"),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return f"Usage: !{alias} <!COMMAND>"

    @classmethod
    async def handle(cls, ctx) -> bool:
        alias, _, argument = ctx.argument.partition(" ")
        alias, argument = alias.strip(), argument.strip()

        if alias.startswith("!"):
            alias = alias[1:]

        if not alias:
            await cls.reply_usage(ctx)
            return False

        try:
            bound_cmd = await dbcmdhandlers.BoundCommand.from_alias(
                db=ctx.db,
                alias=alias,
                channel_db_id=ctx.channel.id,
            )

        except (KeyError, ValueError) as e:
            await ctx.reply(str(e), mention=True)
            return False

        await ctx.reply(f"Aliases: {', '.join(bound_cmd.aliases)}")
        return True
