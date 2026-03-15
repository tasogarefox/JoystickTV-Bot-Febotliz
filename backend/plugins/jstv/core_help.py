import logging

from sqlalchemy import select

from app.db.models import (
    CommandDefinition, Command, CommandAlias
)
from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandContext, JSTVCommandSettings
from app.handlers.jstv.commands import db as dbcmdhandlers

logger = logging.getLogger(__name__)


# ==============================================================================
# Commands

class HelpCommand(JSTVCommand):
    key = "core.commands.help"
    title = "Help Command"
    description = "List available commands or show help for a specific command"

    settings = JSTVCommandSettings(
        aliases = ("help", "usage", "command", "commands", "cmd", "cmds"),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return f"Usage: !{alias}; !{alias} all; !{alias} <!COMMAND>"

    @classmethod
    async def handle(cls, ctx) -> bool:
        args = ctx.argument.split()
        show_all = args[0].casefold() == "all" if len(args) > 0 else False
        alias = args[0] if not show_all and len(args) > 0 else None

        if alias:
            if alias.startswith("!"):
                alias = alias[1:]

            if not alias:
                await cls.reply_usage(ctx)
                return False

        if alias:
            return await cls._show_command_help(ctx, alias)
        else:
            return await cls._list_commands(ctx, show_all=show_all)

    @classmethod
    async def _show_command_help(
        cls,
        ctx: JSTVCommandContext,
        alias: str,
    ) -> bool:
        try:
            bound_cmd = await dbcmdhandlers.BoundCommand.from_alias(
                db=ctx.db,
                alias=alias,
                channel_db_id=ctx.channel.id,
            )

        except (KeyError, ValueError) as e:
            await ctx.reply(str(e), mention=True)
            return False

        if bound_cmd.aliases:
            alias = bound_cmd.aliases[0]

        try:
            text = bound_cmd.command.usage(alias)
        except Exception as e:
            logger.exception(f"Exception handling help for {alias}")
            await ctx.reply(
                f"Error handling help for {alias}."
                f" See logs for details"
            )
            return False

        await ctx.reply(f"{alias}: {text}")
        return True

    @classmethod
    async def _list_commands(
        cls,
        ctx: JSTVCommandContext,
        *,
        show_all: bool = False,
    ) -> bool:
        stmt = (
            select(CommandAlias.name)
            .select_from(Command)
            .join(Command.default_alias)
            .join(Command.definition)
            .where(
                Command.disabled.is_(False),
                CommandDefinition.disabled.is_(False),
            )
        )

        if not show_all:
            stmt = stmt.where(Command.min_access_level <= ctx.viewer.access_level)

        stmt = stmt.order_by(CommandAlias.name)

        result = await ctx.db.execute(stmt)
        aliases = result.scalars().all()

        if not aliases:
            await ctx.reply("No commands available")
            return False

        await ctx.reply(f"Available commands: {', '.join(aliases)}")
        return True
