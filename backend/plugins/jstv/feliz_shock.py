from dataclasses import dataclass

from app.connectors.pishock import (
    PiShockConnector, ShockFrame, ShockMode,
    parse_shocks, MAX_INTENSITY,
)
from app.db.enums import AccessLevel
from app.events import jstv as evjstv
from app.handlers import HandlerTags
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings
from app.handlers.jstv.events import JSTVEventHandler, JSTVEventHandlerSettings


# ==============================================================================
# Config

COST_PER_SECOND = 30.0
COST_PER_INTENSITY = 3.0

TIP_DURATION_PER_TOKEN = 0.01
TIP_START_DURATION = 0.3
TIP_MAX_DURATION = 1

TIP_INTENSITY_PER_TOKEN = 1
TIP_START_INTENSITY = 0
TIP_MAX_INTENSITY = min(50, MAX_INTENSITY)


# ==============================================================================
# Commands

@dataclass(slots=True)
class Cache:
    pishock: PiShockConnector
    shock: ShockFrame

class ShockCommand(JSTVCommand[None, Cache]):
    key = "feliz.shock.send"
    title = "Shock"
    description = "Send shocks using PiShock"
    # tags = frozenset({HandlerTags.nsfw})

    settings = JSTVCommandSettings(
        aliases = ("shock",),
        min_access_level=AccessLevel.viewer,
        channel_cooldown=10,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return (
            # f"Usage: !{alias} [AMOUNT%] [TIMEs] ...; "
            f"Example: !{alias} 10% 0.3s"
        )

    @classmethod
    async def prepare(cls, ctx) -> bool:
        pishock = ctx.connector_manager.get(PiShockConnector)

        if not pishock:
            await ctx.reply("PiShock not connected")
            return False

        if not pishock.devices:
            await ctx.reply("No shockers available")
            return False

        limit = bool(
            ctx.message and not ctx.message.isFake
            and not ctx.viewer.is_streamer  # Don't limit the streamer
        )

        try:
            if not ctx.argument:
                raise ValueError

            shocks = parse_shocks(ctx.argument, limit=limit)
        except ValueError as e:
            errmsg = str(e)
            errmsg += "; " if errmsg else ""
            await ctx.reply(errmsg + cls.usage(ctx.alias), mention=True)
            return False

        shock = shocks[0] if shocks else None
        if not shock:
            await ctx.reply(f"Failed to parse shock command")
            return False

        ctx.set_cache(Cache(
            pishock=pishock,
            shock=shock,
        ))

        return True

    @classmethod
    async def handle(cls, ctx) -> bool:
        assert ctx.cache
        pishock = ctx.cache.pishock
        shock = ctx.cache.shock

        if not await pishock.send_shock(shock):
            await ctx.reply(f"Failed to send shock command")
            return False

        await ctx.reply(f"Sent shock command: {shock}")
        return True

    @classmethod
    async def variable_costs(cls, ctx) -> dict[str, float]:
        assert ctx.cache
        shock = ctx.cache.shock

        costs = {}

        mod = shock.duration if shock.mode == ShockMode.Shock else 0
        cost = mod * COST_PER_SECOND
        costs[f"for {mod:,.1f} seconds"] = cost

        mod = shock.intensity if shock.mode == ShockMode.Shock else 0
        cost = mod * COST_PER_INTENSITY
        costs[f"for {mod} intensity"] = cost

        return costs


# ==============================================================================
# Event Handlers

class ShockOnTipEventHandler(JSTVEventHandler[evjstv.JSTVTipped]):
    key = "feliz.shock.on_tip"
    title = "Shock On Tip"
    description = "Send shocks when someone tips"
    disabled = True
    priority = 1000
    # tags = frozenset({HandlerTags.nsfw})

    msgtypes = (evjstv.JSTVTipped,)

    settings = JSTVEventHandlerSettings()

    @classmethod
    async def handle(cls, ctx) -> bool:
        pishock = ctx.connector_manager.get(PiShockConnector)

        if not pishock or not pishock.devices:
            await ctx.reply("Error: No shockers available")
            return False

        tip_amount = ctx.message.metadata.how_much

        duration = TIP_START_DURATION + tip_amount * TIP_DURATION_PER_TOKEN
        duration = min(duration, TIP_MAX_DURATION)

        intensity = TIP_START_INTENSITY + tip_amount * TIP_INTENSITY_PER_TOKEN
        intensity = min(intensity, TIP_MAX_INTENSITY)

        if duration <= 0 or intensity <= 0:
            return False

        shock = ShockFrame(ShockMode.Shock, duration, intensity)

        if not await pishock.send_shock(shock):
            await ctx.reply(f"Failed to send shock command")
            return False

        await ctx.reply(f"Sent shock command: {shock}")
        return False
