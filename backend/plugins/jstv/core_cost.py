import logging

from app.db.enums import AccessLevel
from app.jstv import jstv_db
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings
from app.handlers.jstv.commands import db as dbcmdhandlers

logger = logging.getLogger(__name__)


# ==============================================================================
# Commands

class CostCommand(JSTVCommand):
    key = "core.commands.cost"
    title = "Cost Command"
    description = "Calculate and show cost of a command"

    settings = JSTVCommandSettings(
        aliases = ("cost", "costs"),
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

        bound_viewer = jstv_db.BoundViewer(
            ctx.db, ctx.channel, ctx.user, ctx.viewer,
        )

        # Load handler
        try:
            bound_vcmd = await dbcmdhandlers.BoundViewerCommand.from_alias(
                ctx.db, alias, bound_viewer,
            )

        except (KeyError, ValueError) as e:
            await ctx.reply(str(e), mention=True)
            return False

        cmd = bound_vcmd.command
        cmdctx = await bound_vcmd.make_command_context(
            connector=ctx.connector,
            message=ctx.message,
            alias=alias,
            argument=argument,
        )

        # Prepare handler
        try:
            success = await cmd.prepare(cmdctx)

        except Exception as e:
            # Report error
            logger.exception("Error preparing command %r: %s", cmd.key, e)
            await ctx.reply(
                f"Error preparing command {alias}. See logs for details"
            )
            return False

        if not success:
            await ctx.reply(f"Failed to prepare command {alias}")
            return False

        # Calculate costs
        try:
            var_costs = await cmd.variable_costs(cmdctx)

        except Exception as e:
            # Report error
            logger.exception("Error calculating variable costs for command %r: %s", cmd.key, e)
            await ctx.reply(
                f"Error calculating variable costs for command {alias}. See logs for details"
            )
            return False

        # Report costs
        str_costs = dbcmdhandlers.format_command_costs(cmdctx.settings.base_cost, var_costs)
        await ctx.reply(f"Cost: {str_costs}", mention=True)
        return True
