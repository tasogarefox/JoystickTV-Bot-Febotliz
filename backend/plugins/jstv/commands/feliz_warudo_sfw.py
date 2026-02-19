from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class NoseBoopCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.noseboop"
    title = "NoseBoop"
    description = "Give nose boops in Warudo <3"

    aliases = ("boop", "boops")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Boop")
        return True

class NoseLickCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.noselick"
    title = "NoseLick"
    description = "Give nose licks in Warudo <3"

    aliases = ("lick", "licks", "noselick", "noselicks", "kiss", "kisses")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("NoseLick")
        return True

class EarLickCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.earlick"
    title = "EarLick"
    description = "Give ear licks in Warudo <3"

    aliases = ("earlick", "earlicks")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("EarLick")
        return True

class BellyLickCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.bellylick"
    title = "BellyLick"
    description = "Give belly licks in Warudo <3"

    aliases = ("bellylick", "bellylicks")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("BellyLick")
        return True

class BonkCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.bonk"
    title = "Bonk"
    description = "Bonk in Warudo"

    aliases = ("bonk",)

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Bonk")
        return True

class LoveCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.love"
    title = "ThrowLove"
    description = "Throw love balls in Warudo <3"

    aliases = ("love",)

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Love")
        return True

class BallsCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.balls"
    title = "ThrowBalls"
    description = "Throw balls in Warudo <3"

    aliases = ("balls",)

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Balls")
        return True

class FeedCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.feed"
    title = "ThrowFood"
    description = "Throw food in Warudo <3"

    aliases = ("feed", "food")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Feed")
        return True

class HydrateCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.hydrate"
    title = "Hydrate"
    description = "Hydrate in Warudo <3"

    aliases = ("hydrate", "water")

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Hydrate")
        return True

class PieCommand(JSTVCommand[evjstv.JSTVNewChatMessage]):
    key = "feliz.pie"
    title = "ThrowPie"
    description = "Throw pie in Warudo <3"

    aliases = ("pie",)

    settings = JSTVCommandSettings(
        min_access_level=CommandAccessLevel.viewer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        await ctx.connector.send_warudo("Pie")
        return True
