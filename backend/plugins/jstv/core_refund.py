import logging

from sqlalchemy import select

from app.settings import POINTS_NAME
from app.db.models import ViewerCommandCooldown
from app.db.enums import AccessLevel
from app.jstv import jstv_db, jstv_dbstate
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandContext, JSTVCommandSettings
from app.handlers.jstv.commands import db as dbcmdhandlers

logger = logging.getLogger(__name__)


# ==============================================================================
# Helpers

async def _get_bound_viewer_command(
    ctx: JSTVCommandContext,
    bound_viewer: jstv_db.BoundViewer,
    alias: str,
) -> dbcmdhandlers.BoundViewerCommand | None:
    try:
        return await dbcmdhandlers.BoundViewerCommand.from_alias(
            ctx.db, alias, bound_viewer,
        )

    except (KeyError, ValueError) as e:
        await ctx.reply(str(e), mention=True)
        return None


# ==============================================================================
# Commands

class RefundCommand(JSTVCommand):
    key = "core.commands.refund"
    title = "Refund Command"
    description = "Refund a command"

    settings = JSTVCommandSettings(
        aliases = ("refund",),
        min_access_level=AccessLevel.moderator,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return f"Usage: !{alias} <@USERNAME> [!COMMAND]"

    @classmethod
    async def handle(cls, ctx) -> bool:
        target_name, _, cmdline = ctx.argument.partition(" ")
        target_name, cmdline = target_name.strip(), cmdline.strip()

        alias, _, argument = cmdline.partition(" ")
        alias, argument = alias.strip(), argument.strip()

        if target_name.startswith("@"):
            target_name = target_name[1:]

        if alias:
            if alias.startswith("!"):
                alias = alias[1:]

            if not alias:
                await cls.reply_usage(ctx)
                return False

        if not target_name:
            await cls.reply_usage(ctx)
            return False

        user = await jstv_db.get_user(ctx.db, target_name)
        viewer = await jstv_db.get_viewer(ctx.db, ctx.channel, user) if user else None
        if viewer is None:
            await ctx.reply((
                f"Viewer @{target_name} not found"
            ), mention=True)
            return False

        bound_viewer = jstv_db.BoundViewer(ctx.db, ctx.channel, user, viewer)

        if not alias:
            return await cls._refund_last(ctx, bound_viewer)

        if not argument:
            return await cls._refund_last_by_command(ctx, bound_viewer, alias)

        return await cls._refund_by_command_line(ctx, bound_viewer, alias, argument)

    @classmethod
    async def _refund_last(
        cls,
        ctx: JSTVCommandContext,
        bound_viewer: jstv_db.BoundViewer,
    ) -> bool:
        user = await bound_viewer.lazy_user()

        result = await ctx.db.execute(
            select(ViewerCommandCooldown)
            .where(ViewerCommandCooldown.user_id==user.id)
            .order_by(ViewerCommandCooldown.last_used_at.desc())
            .limit(1)
        )

        cooldown = result.scalar_one_or_none()
        if cooldown is None:
            await ctx.reply((
                f"Viewer @{user.username} has not used any commands yet"
            ), mention=True)
            return False

        return await cls._refund_from_cooldown(ctx, bound_viewer, cooldown)

    @classmethod
    async def _refund_last_by_command(
        cls,
        ctx: JSTVCommandContext,
        bound_viewer: jstv_db.BoundViewer,
        alias: str,
    ) -> bool:
        bound_vcmd = await _get_bound_viewer_command(ctx, bound_viewer, alias)
        if bound_vcmd is None:
            return False

        cooldown = await bound_vcmd.lazy_viewer_cooldown()
        return await cls._refund_from_cooldown(ctx, bound_viewer, cooldown)

    @classmethod
    async def _refund_by_command_line(
        cls,
        ctx: JSTVCommandContext,
        bound_viewer: jstv_db.BoundViewer,
        alias: str,
        argument: str,
    ) -> bool:
        bound_vcmd = await _get_bound_viewer_command(ctx, bound_viewer, alias)
        if bound_vcmd is None:
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

        total_cost = dbcmdhandlers.calc_total_cost(cmdctx.settings.base_cost, var_costs)
        return await cls._refund_amount(ctx, bound_viewer, total_cost, alias, argument)

    @classmethod
    async def _refund_from_cooldown(
        cls,
        ctx: JSTVCommandContext,
        bound_viewer: jstv_db.BoundViewer,
        cooldown: ViewerCommandCooldown,
    ) -> bool:
        success = await cls._refund_amount(
            ctx,
            bound_viewer,
            cooldown.last_exec_cost,
            cooldown.last_exec_alias,
            cooldown.last_exec_argument,
        )

        if success:
            cooldown.last_exec_cost = 0

        return success

    @classmethod
    async def _refund_amount(
        cls,
        ctx: JSTVCommandContext,
        bound_viewer: jstv_db.BoundViewer,
        amount: int,
        alias: str | None,
        argument: str | None,
    ) -> bool:
        viewer = await bound_viewer.lazy_viewer()
        username = bound_viewer.username

        cmdline = f"!{alias or 'UNKNOWN'} {argument or ''}".rstrip()

        msg = (
            f"@{ctx.actorname} refunded {amount:,.2f} {POINTS_NAME}"
            f" to @{username} for command: {cmdline}"
        )

        if amount > 0:
            jstv_dbstate.adjust_viewer_points(viewer, amount, msg)

        await ctx.reply(msg)
        return True
