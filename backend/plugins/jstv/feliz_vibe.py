from typing import NamedTuple, Any
from dataclasses import dataclass
import os

from app.connectors.buttplug import ButtplugConnector, VibeGroup, VibeFrame
from app.db.enums import AccessLevel
from app.events import jstv as evjstv
from app.handlers import HandlerTags
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings, JSTVCommandContext
from app.handlers.jstv.events import JSTVEventHandler, JSTVEventHandlerSettings
from app import signals

signal_builder = signals.ExprBuilder()


# ==============================================================================
# Config

OVERRIDE_VIBES = True

MAX_DURATION = float(os.getenv("BUTTPLUG_MAX_DURATION", 120.0))

COST_PER_SECOND = float(os.getenv("BUTTPLUG_COST_PER_SECOND", 10.0))


# ==============================================================================
# Vibe Patterns

PATTERNS: dict[str, signals.SignalExpr] = {}

# Lovense Patterns
PATTERNS["pause"] = signal_builder.parse("1s 0%")
PATTERNS["earthquake"] = signal_builder.parse("1s 0% 20% 40% 60% 80% 100%")
PATTERNS["quake"] = PATTERNS["earthquake"]
PATTERNS["fireworks"] = signal_builder.parse("1s 0% 10% 20% 30% 40% 50% 60% 70% 100%")
# PATTERNS["fire"] = PATTERNS["fireworks"]
PATTERNS["wave"] = signal_builder.parse("3s 1..100..1%")
PATTERNS["pulse"] = signal_builder.parse("1s 0% 100%")

# Custom patterns
PATTERNS["hills"] = signal_builder.parse("3s 20-100..30-70..80-0% 0.2s 0%")
PATTERNS["ocean"] = signal_builder.parse("1.5s 50..50-100% mirror 50..50-0% mirror")


# ==============================================================================
# Tip Vibe Patterns

class TipPatternLevel(NamedTuple):
    min_tip_amount: int
    expr: signals.SignalExpr

TIP_PATTERNS_LEVELS: list[TipPatternLevel] = [
    TipPatternLevel(200, signal_builder.parse("100% * 0.5sec-per-token")),
    TipPatternLevel(40, signal_builder.parse("50% * 2sec-per-token")),
    TipPatternLevel(13, signal_builder.parse("25% * 3sec-per-token")),
    TipPatternLevel(4, signal_builder.parse("50% * 10sec-per-token")),
    TipPatternLevel(2, signal_builder.parse("75% * 5sec-per-token")),
    TipPatternLevel(1, signal_builder.parse("100% * 1sec-per-token + 2s")),
]

TIP_PATTERNS_SPECIAL: dict[int, signals.SignalExpr] = {
    # 10: signals.ChoiceExpr(x.expr for x in TIP_PATTERNS_LEVELS),  # Random Level
    # 11: signal_builder.parse("50% 30-90s"),  # Random Time
    # 12: signal_builder.parse(":pause * 1sec-per-token"),  # Pause the Queue
    # 36: signal_builder.parse(":earthquake * 2sec-per-token"),  # Earthquake Pattern
    # 37: signal_builder.parse(":fireworks * 2sec-per-token"),  # Fireworks Pattern
    # 38: signal_builder.parse(":wave * 2sec-per-token"),  # Wave Pattern
    # 39: signal_builder.parse(":pulse * 2sec-per-token"),  # Pulse Pattern
}


# ==============================================================================
# Commands

@dataclass(slots=True)
class VibeCommandCache:
    buttplug: ButtplugConnector
    vibe_group: VibeGroup

class VibeCommand(JSTVCommand[None, VibeCommandCache]):
    key = "feliz.vibe.send"
    title = "Vibe"
    description = "Send vibes using Buttplug"
    tags = frozenset({HandlerTags.nsfw})

    settings = JSTVCommandSettings(
        aliases = ("vibe", "buzz"),
        min_access_level=AccessLevel.viewer,
    )

    last_message: evjstv.JSTVMessage | None = None
    """Last message that was successfully handled by this command."""

    @classmethod
    def usage(cls, alias: str) -> str:
        return (
            # f"Usage: !{alias} [AMOUNT%] [TIMEs] [DEVICE] ...; "
            f"Examples: !{alias} 20% 5s"
            f"; !{alias} 5s 10% 50% 100%"
            f"; !{alias} 0.5s 50% 0% 5x"
            # f"; !{alias} deviceA 5s 50%"
            # f\n"Percent and seconds pair automatically. Devices are optional."
        )

    @classmethod
    async def prepare(cls, ctx) -> bool:
        buttplug = ctx.connector_manager.get(ButtplugConnector)

        if not buttplug:
            await ctx.reply("Intiface not connected")
            return False

        if not buttplug.has_devices:
            await ctx.reply("No vibrators available")
            return False

        cfg_kwargs: dict[str, Any] = {
            "patterns": PATTERNS,
            "variables": {},
        }

        if (
            ctx.message is not None and
            not ctx.message.isFake
            and not ctx.viewer.is_streamer  # Don't limit the streamer
        ):
            cfg_kwargs["total_limit"] = round(MAX_DURATION * 1000)

        if isinstance(ctx.message, evjstv.JSTVTipped):
            cfg_kwargs["variables"]["tip_amount"] = ctx.message.metadata.how_much

        try:
            if not ctx.argument:
                raise ValueError

            frames = tuple(signal_builder.eval(
                signal_builder.parse(ctx.argument),
                **cfg_kwargs,
            ))

        except (ValueError, signals.SignalParseError, signals.SignalEvalError) as e:
            errmsg = str(e)
            errmsg += "; " if errmsg else ""
            await ctx.reply(errmsg + cls.usage(ctx.alias), mention=True)
            return False

        if not frames:
            await ctx.reply("Expression did not produce any vibes", mention=True)
            return False

        # Convert to VibeFrames (old system)
        vibes = tuple(
            VibeFrame.new_override(
                duration=frame.duration / 1000,
                intensity=frame.intensity / 100,
            )
            for frame in frames
        )

        group = VibeGroup(
            frames=vibes,
            channel_id=ctx.channel_id,
            username=ctx.actorname,
        )

        ctx.set_cache(VibeCommandCache(
            buttplug=buttplug,
            vibe_group=group,
        ))

        return True

    @classmethod
    async def handle(cls, ctx) -> bool:
        assert ctx.cache

        await ctx.cache.buttplug.enqueue(ctx.cache.vibe_group)

        if ctx.message is not None:
            cls.last_message = ctx.message

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

class VibePatternCommand(JSTVCommand):
    key = "feliz.vibe.pattern"
    title = "Vibe Pattern"
    description = "Inspect a vibe pattern"
    tags = frozenset({HandlerTags.nsfw})

    settings = JSTVCommandSettings(
        aliases = ("vibepattern", "vibepat"),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return f"Usage: !{alias} list; !{alias} show <NAME>"

    @classmethod
    async def handle(cls, ctx) -> bool:
        command, _, argument = ctx.argument.partition(" ")

        if command == "show":
            name, _, argument = argument.partition(" ")
            return await cls.show_name(ctx, name)

        if command == "list":
            return await cls.list_patterns(ctx)

        await cls.reply_usage(ctx)
        return False

    @classmethod
    async def show_name(cls, ctx: JSTVCommandContext, name: str) -> bool:
        name.strip()

        if not name:
            await cls.reply_usage(ctx)
            return False

        expr = PATTERNS.get(name)
        if expr is None:
            await ctx.reply((
                f"Unknown pattern: {ctx.argument}"
            ), mention=True)
            return False

        await ctx.reply(f"pattern {name}: {expr}")
        return True

    @classmethod
    async def list_patterns(cls, ctx: JSTVCommandContext) -> bool:
        if not PATTERNS:
            await ctx.reply("No patterns defined")
            return False

        patterns = sorted(PATTERNS.keys())

        s = ", ".join(patterns)
        await ctx.reply(f"patterns: {s}")
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
        # Skip if already handled
        if ctx.message is VibeCommand.last_message:
            return False

        buttplug = ctx.connector_manager.get(ButtplugConnector)

        if not buttplug or not buttplug.has_devices:
            await ctx.reply("Error: No vibrators available")
            return False

        if not OVERRIDE_VIBES:
            await buttplug.delay(180)
            return False

        tip_amount = ctx.message.metadata.how_much

        expr: signals.SignalExpr | None = None

        if expr is None:
            expr = TIP_PATTERNS_SPECIAL.get(tip_amount)

        if expr is None:
            for item in TIP_PATTERNS_LEVELS:
                if tip_amount >= item.min_tip_amount:
                    expr = item.expr
                    break

        if expr is None:
            return False

        try:
            frames = tuple(signal_builder.eval(
                expr,
                patterns=PATTERNS,
                variables=dict(
                    tip_amount=tip_amount,
                ),
            ))
        except signals.SignalEvalError as e:
            await ctx.reply(f"Error: {e}")
            return False

        if not frames:
            return False

        # Convert to VibeFrames (old system)
        vibes = tuple(
            VibeFrame.new_override(
                duration=frame.duration / 1000,
                intensity=frame.intensity / 100,
            )
            for frame in frames
        )

        group = VibeGroup(
            frames=vibes,
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        )

        await buttplug.enqueue(group)
        return False
