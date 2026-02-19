import asyncio
import random

from app.connectors.buttplug import VibeGroup, VibeFrame
from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Helpers

def get_default_vibes() -> tuple[VibeFrame, ...]:
    return (VibeFrame.new_override(10, random.uniform(0.1, 0.5)),)


# ==============================================================================
# Commands

class LewdPetCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.lewdpet"
    title = "LewdPet"
    description = "Give lewd pets in Warudo <3"

    aliases = ("lewdpet", "lewdpets", "lewdpat", "lewdpats")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        vibe_group = VibeGroup(
            get_default_vibes(),
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        )

        await asyncio.gather(
            ctx.connector.talkto("Buttplug", "vibe", vibe_group),
            ctx.connector.send_warudo("LewdPets"),
        )
        return True

class LewdBoopCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.lewdboop"
    title = "LewdBoop"
    description = "Give lewd boops in Warudo <3"

    aliases = ("lewdboop", "lewdboops")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        vibe_group = VibeGroup(
            get_default_vibes(),
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        )

        await asyncio.gather(
            ctx.connector.talkto("Buttplug", "vibe", vibe_group),
            ctx.connector.send_warudo("LewdBoop"),
        )
        return True

class LewdLickCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.lewdlick"
    title = "LewdLick"
    description = "Give lewd licks in Warudo <3"

    aliases = ("lewdlick", "lewdlicks")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        vibe_group = VibeGroup(
            get_default_vibes(),
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        )

        await asyncio.gather(
            ctx.connector.talkto("Buttplug", "vibe", vibe_group),
            ctx.connector.send_warudo("LewdLick"),
        )
        return True

class NipLickCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.niplick"
    title = "NippleLick"
    description = "Give nipple licks in Warudo <3"

    aliases = ("niplick", "niplicks", "nipplelick", "nipplelicks")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        vibe_group = VibeGroup(
            get_default_vibes(),
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        )

        await asyncio.gather(
            ctx.connector.talkto("Buttplug", "vibe", vibe_group),
            ctx.connector.send_warudo("NippleLick"),
        )
        return True

class BeanLickCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.beanlick"
    title = "BeanLick"
    description = "Give bean licks in Warudo <3"

    aliases = ("beanlick", "beanlicks", "pawlick", "pawlicks")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        vibe_group = VibeGroup(
            get_default_vibes(),
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        )

        await asyncio.gather(
            ctx.connector.talkto("Buttplug", "vibe", vibe_group),
            ctx.connector.send_warudo("BeanLick"),
        )
        return True

class SpankCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.spank"
    title = "Spank"
    description = "Spank in Warudo"

    aliases = ("spank", "spanks")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        vibes = tuple(v for v in [
            VibeFrame.new_override(0.5, random.uniform(0.5, 1.0)),
            VibeFrame.new_override(0.5, 0)
        ] for _ in range(random.randint(3, 10)))
        vibe_group = VibeGroup(
            vibes,
            channel_id=ctx.message.channelId,
            username=ctx.message.actorname,
        )

        await asyncio.gather(
            ctx.connector.talkto("Buttplug", "vibe", vibe_group),
            ctx.connector.send_warudo("Spank"),
        )
        return True

class CumCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.cum"
    title = "Cum"
    description = "Cum on me in Warudo <3"

    aliases = ("cum", "coom", "nut")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Cum")
        return True
