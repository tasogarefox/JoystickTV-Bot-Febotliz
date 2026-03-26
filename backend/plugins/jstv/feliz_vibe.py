from typing import Any
from dataclasses import dataclass
import os

from app.connectors.buttplug import (
    ButtplugConnector, VibeGroup, VibeFrame,
    parse_vibes,
)
from app.db.enums import AccessLevel
from app.events import jstv as evjstv
from app.handlers import HandlerTags
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings
from app.handlers.jstv.events import JSTVEventHandler, JSTVEventHandlerSettings


# ==============================================================================
# Config

ENFORCE_DEVICES_AVAILABLE = True
OVERRIDE_VIBES = True

MAX_DURATION = float(os.getenv("BUTTPLUG_MAX_DURATION", 120.0))

COST_PER_SECOND = float(os.getenv("BUTTPLUG_COST_PER_SECOND", 10.0))


# ==============================================================================
# Commands

@dataclass(slots=True)
class Cache:
    buttplug: ButtplugConnector
    vibe_group: VibeGroup

class VibeCommand(JSTVCommand[Any, Cache]):
    key = "feliz.vibe.send"
    title = "Vibe"
    description = "Send vibes using Buttplug"
    tags = frozenset({HandlerTags.nsfw})

    settings = JSTVCommandSettings(
        aliases = ("vibe",),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return (
            # f"Usage: !{alias} [AMOUNT%] [TIMEs] [DEVICE] ...; "
            f"Examples: !{alias} 20% 5s"
            f"; !{alias} 5s 10% 50% 100%"
            f"; !{alias} 0.5s 50% 0% 5r"
            # f"; !{alias} deviceA 5s 50%"
            # f\n"Tokens may appear in any order. Percent and seconds pair automatically. Devices are optional."
        )

    @classmethod
    async def prepare(cls, ctx) -> bool:
        buttplug = ctx.connector_manager.get(ButtplugConnector)

        if not buttplug:
            await ctx.reply("Intiface not connected")
            return False

        if not buttplug.has_devices and ENFORCE_DEVICES_AVAILABLE:
            await ctx.reply("No vibrators available")
            return False

        parse_kwargs = {}
        if (
            ctx.message and
            not ctx.message.isFake
            and not ctx.viewer.is_streamer  # Don't limit the streamer
        ):
            parse_kwargs["max_duration"] = MAX_DURATION

        try:
            if not ctx.argument:
                raise ValueError

            vibes = parse_vibes(ctx.argument, **parse_kwargs)

        except ValueError as e:
            errmsg = str(e)
            errmsg += "; " if errmsg else ""
            await ctx.reply(errmsg + cls.usage(ctx.alias), mention=True)
            return False

        group = VibeGroup(
                frames=vibes,
                channel_id=ctx.channel_id,
                username=ctx.actorname,
            )

        ctx.set_cache(Cache(
            buttplug=buttplug,
            vibe_group=group,
        ))

        return True

    @classmethod
    async def handle(cls, ctx) -> bool:
        assert ctx.cache

        await ctx.cache.buttplug.enqueue(ctx.cache.vibe_group)
        return True

    @classmethod
    async def variable_costs(cls, ctx) -> dict[str, float]:
        assert ctx.cache
        group = ctx.cache.vibe_group

        costs = {}

        mod = group.get_duration()
        cost = mod * COST_PER_SECOND
        costs[f"for {mod:,.1f} seconds"] = cost

        return costs

class VibeClearCommand(JSTVCommand):
    key = "feliz.vibe.clear"
    title = "Vibe Clear"
    description = "Clear all buttplug vibes"
    tags = frozenset({HandlerTags.nsfw})

    settings = JSTVCommandSettings(
        aliases = ("vibeclear", "vibestop"),
        min_access_level=AccessLevel.moderator,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.talkto("Buttplug", "stop", None)
        return True

class VibeDelayCommand(JSTVCommand):
    key = "feliz.vibe.delay"
    title = "Vibe Delay"
    description = "Delay buttplug vibes for the specified number of seconds"
    tags = frozenset({HandlerTags.nsfw})

    settings = JSTVCommandSettings(
        aliases = ("vibedelay", "vibedisable"),
        min_access_level=AccessLevel.moderator,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return f"Usage: !{alias} [SECONDS]"

    @classmethod
    async def handle(cls, ctx) -> bool:
        try:
            if not ctx.argument:
                raise ValueError
            delay = float(ctx.argument)
        except ValueError:
            await cls.reply_usage(ctx)
            return True

        await ctx.connector.talkto("Buttplug", "disable", delay)
        return True


# ==============================================================================
# Event Handlers

class VibeOnTipEventHandler(JSTVEventHandler[evjstv.JSTVTipped]):
    key = "feliz.vibe.on_tip"
    title = "Vibe On Tip"
    description = "Send vibes when someone tips"
    # disabled = True
    priority = 1000
    tags = frozenset({HandlerTags.nsfw})

    msgtypes = (evjstv.JSTVTipped,)

    settings = JSTVEventHandlerSettings()

    @classmethod
    async def handle(cls, ctx) -> bool:
        buttplug = ctx.connector_manager.get(ButtplugConnector)

        if not buttplug or not buttplug.has_devices:
            await ctx.reply("Error: No vibrators available")
            return False

        if not OVERRIDE_VIBES:
            await buttplug.delay(180)
            return False

        tip_amount = ctx.message.metadata.how_much

        vibes: tuple[VibeFrame, ...] | None = None

        # Basic Levels
        if 1 <= tip_amount <= 1:
            vibes = (VibeFrame.new_override(tip_amount +  2, 1.00),)
        elif 2 <= tip_amount <= 3:
            vibes = (VibeFrame.new_override(tip_amount *  5, 0.50),)
        elif 4 <= tip_amount <= 10:
            vibes = (VibeFrame.new_override(tip_amount * 10, .025),)
        elif 13 <= tip_amount <= 35:
            vibes = (VibeFrame.new_override(tip_amount *  3, 0.50),)
        elif 40 <= tip_amount <= 199:
            vibes = (VibeFrame.new_override(tip_amount *  2, 0.75),)
        elif tip_amount >= 200:
            vibes = (VibeFrame.new_override(tip_amount /  2, 1.00),)

        # Special Commands
        # elif amount == ...:
        #     vibes = ...  # Random Level
        elif tip_amount == 11:
            vibes = parse_vibes("50% 30-90s")  # Random Time
        elif tip_amount == 12:
            vibes = parse_vibes("12s 0%")  # Pause the Queue
        elif tip_amount == 36:
            vibes = parse_vibes("1s 0% 20% 40% 60% 80% 100% 72S")  # Earthquake Pattern
        elif tip_amount == 37:
            vibes = parse_vibes("1s 0% 10% 20% 30% 40% 50% 60% 70% 100% 74S")  # Fireworks Pattern
        elif tip_amount == 38:
            vibes = parse_vibes("1.5s 1..100% 1.5s 100..1% 76S")  # Wave Pattern
        elif tip_amount == 39:
            vibes = parse_vibes("1s 0% 100% 78S")  # Pulse Pattern

        if not vibes:
            return False

        await buttplug.enqueue(VibeGroup(
            vibes,
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        ))

        return False
