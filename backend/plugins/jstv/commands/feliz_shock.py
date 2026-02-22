from app.connectors.pishock import PiShockConnector, parse_shocks
from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class VibeCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.shock.send"
    title = "Shock"
    description = "Send shocks using PiShock"

    aliases = ("shock",)

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.broadcaster,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        pishock = ctx.connector_manager.get(PiShockConnector)

        # if not pishock or not info or not info.available:
        if not pishock or not pishock.is_connected or not pishock.devices:
            await ctx.connector.send_chat_reply(ctx.message, (
                "No shockers available"
            ))
            return False

        argsstr = ctx.message.botCommandArg
        try:
            if not argsstr:
                raise ValueError

            shocks = parse_shocks(argsstr)
            shock = shocks[0] if shocks else None

        except ValueError as e:
            # Show the usage
            errmsg = f"{e} " if isinstance(e, Exception) else ""
            await ctx.connector.send_chat_reply(ctx.message, errmsg + (
                # f"\nUsage: !{ctx.alias } [AMOUNT%] [TIMEs] ..."
                f"\nExample: !{ctx.alias } 10% 0.3s"
            ).strip(), mention=True)
            return False

        if not shock:
            await ctx.connector.send_chat_reply(ctx.message, (
                f"Failed to parse shock command"
            ))
            return False

        if not await pishock.send_shock(shock):
            await ctx.connector.send_chat_reply(ctx.message, (
                f"Failed to send shock command"
            ))
            return False

        await ctx.connector.send_chat_reply(ctx.message, (
            f"Sent shock command: {shock}"
        ))
        return True
