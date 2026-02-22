from app.connectors.buttplug import ButtplugConnector, VibeGroup, parse_vibes
from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class VibeCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.vibe.send"
    title = "Vibe"
    description = "Send vibes using Buttplug"

    aliases = ("vibe",)

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.follower,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        buttplug = ctx.connector_manager.get(ButtplugConnector)

        if not buttplug or not buttplug.is_connected or not buttplug.has_devices:
            await ctx.connector.send_chat_reply(ctx.message, (
                "No vibrators available"
            ), mention=True)
            return False

        vibestr = ctx.message.botCommandArg
        try:
            if not vibestr:
                raise ValueError

            vibes = parse_vibes(vibestr)

        except ValueError as e:
            # Show the usage
            errmsg = f"{e} " if isinstance(e, Exception) else ""
            await ctx.connector.send_chat_reply(ctx.message, errmsg + (
                # f"\nUsage: !{ctx.alias } [AMOUNT%] [TIMEs] [DEVICE] ..."
                f"\nExamples: !{ctx.alias } 20% 5s"
                f"; !{ctx.alias } 5s 10% 50% 100%"
                f"; !{ctx.alias } 0.5s 50% 0% 5r"
                # f"; !{ctx.alias } deviceA 5s 50%"
                # f\n"Tokens may appear in any order. Percent and seconds pair automatically. Devices are optional."
            ).strip(), mention=True)
            return False

        await ctx.connector.talkto(ButtplugConnector.NAME, "vibe", VibeGroup(
            frames=vibes,
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        ))

        return True

class VibeClearCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.vibe.clear"
    title = "Vibe Clear"
    description = "Clear all buttplug vibes"

    aliases = ("vibe_clear", "vibe_stop")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.moderator,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.talkto("Buttplug", "stop", None)
        return True

class VibeDelayCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.vibe.delay"
    title = "Vibe Delay"
    description = "Delay buttplug vibes for the specified number of seconds"

    aliases = ("vibe_delay", "vibe_disable")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.moderator,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        try:
            if not ctx.message.botCommandArg:
                raise ValueError
            delay = float(ctx.message.botCommandArg)
        except ValueError:
            await ctx.connector.send_chat_reply(
                ctx.message,
                f"Usage: !{ctx.alias} [SECONDS]",
                mention=True,
            )
            return True

        await ctx.connector.talkto("Buttplug", "disable", delay)
        return True
