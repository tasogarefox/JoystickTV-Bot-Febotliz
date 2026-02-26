from typing import Any, Sequence
from dataclasses import dataclass
import random

from app.settings import POINTS_NAME
from app.jstv import jstv_db, jstv_dbstate
from app.db.models import Viewer
from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandContext, JSTVCommandSettings


# ==============================================================================
# Config

STREAMER_EXEMPT = True


# ==============================================================================
# Replies

REPLIES_INVALID_TARGET: list[str] = [
    "@{sender} I looked everywhere, but @{receiver} doesn't seem to exist.",
    "@{sender} Who is @{receiver}? I can't find them.",
    "@{sender} @{receiver}? Never heard of them.",
]

REPLIES_TARGET_SELF: list[str] = [
    "@{sender} You already have your own {currency}, silly.",
    "@{sender} Donating {currency} to yourself huh? Such generosity.",
    "@{sender} Really? You're giving {currency} to yourself? You must be a genius.",
    "@{sender} tried donating {currency} to themselves. Very efficient.",
    "@{sender} That's just your {currency} taking a short walk.",
    "@{sender} Self-love is the greatest gift of all.",
]

REPLIES_NOT_ENOUGH_POINTS: list[str] = [
    "@{sender} You don't have that many {currency}. Nice imagination though.",
    "@{sender} You tried to donate more {currency} than you actually own, silly.",
    "@{sender} Those {currency} exist only in your dreams, darling.",
    "@{sender} Computer says no. You don't have that many {currency}.",
]

REPLIES_NEGATIVE_AMOUNT: list[str] = [
    "@{sender} Nice try. {currency} are not a loan service.",
    "@{sender} You can't donate negative {currency}. That's called stealing.",
    "@{sender} That's not a donation, that's a robbery.",
    "@{sender} I admire the creativity, but no.",
    "@{sender} Trying to reverse-donate {currency}? Suspicious.",
]

DEFAULT_AMOUNT_REPLY: str = "{sender} gives {amount:,} {currency} to {receiver}."

# NOTE: Has to be ordered by highest to lowest threshold
REPLIES_AMOUNT: list[tuple[int, list[str]]] = [
    (9000, [
        "IT'S OVER 9000 {currency}! {sender} just donated {amount:,} to {receiver}!",
        "The {currency} counter exploded. {sender} sent {amount:,} {currency} to {receiver}.",
        "Legendary donation! {sender} gives {receiver} {amount:,} {currency}.",
    ]),
    (2, [
        "{sender} donated {amount:,} {currency} to {receiver}.",
        "{sender} sends {amount:,} {currency} over to {receiver}.",
        "{receiver} receives {amount:,} shiny {currency} from {sender}.",
        "{sender} shares {amount:,} {currency} with {receiver}.",
    ]),
    (1, [
        "{sender} donated exactly {amount:,} heroic {currency} to {receiver}.",
        "{amount:,} brave {currency} begin their journey from {sender} to {receiver}.",
        "{sender} gives {receiver} exactly {amount:,} {currency}. Every legend starts somewhere.",
        "A tiny but heartfelt {amount:,} {currency} donation from {sender} to {receiver}.",
        "{receiver} receives a humble {amount:,} {currency} from {sender}.",
    ]),
    (0, [
        "{sender} is donating absolutely nothing. Generous!",
        "Wow, such generosity. {sender} just donated zero whole {currency}.",
        "What a kind soul {sender} is. Donating nothing to {receiver}.",
        "{sender} heroically donated 0 {currency} to {receiver}.",
        "Breaking news: {sender} donates absolutely nothing.",
    ]),
]


# ==============================================================================
# Helpers

def has_streamer_exempt(viewer: Viewer) -> bool:
    return STREAMER_EXEMPT and viewer.is_streamer

async def formatted_reply(
    ctx: JSTVCommandContext[Any, Any],
    template: str,
    receiver: str,
    amount: int,
) -> None:
    await ctx.reply(template.format(
        currency=POINTS_NAME,
        sender=ctx.actorname,
        receiver=receiver,
        amount=amount,
    ))

async def random_reply(
    ctx: JSTVCommandContext[Any, Any],
    templates: Sequence[str],
    receiver: str,
    amount: int,
) -> None:
    await formatted_reply(ctx, random.choice(templates), receiver, amount)

async def random_amount_reply(
    ctx: JSTVCommandContext[Any, Any],
    sorted_templates: Sequence[tuple[int, list[str]]],
    receiver: str,
    amount: int,
) -> None:
    for threshold, replies in sorted_templates:
        if amount >= threshold:
            await random_reply(ctx, replies, receiver, amount)
            return

    await formatted_reply(ctx, DEFAULT_AMOUNT_REPLY, receiver, amount)


# ==============================================================================
# Commands

@dataclass(slots=True)
class Cache:
    target_name: str
    target: Viewer
    amount: int

class GivePointsCommand(JSTVCommand[None, Cache]):
    key = "core.points.give"
    title = "Give Points"
    description = "Give someone points"

    settings = JSTVCommandSettings(
        aliases = ("givepoints", "give_points", "pgive"),
        min_access_level=AccessLevel.viewer,
    )

    @classmethod
    def usage(cls, alias: str) -> str:
        return (
            # f"Usage: !{alias} <@USERNAME> <AMOUNT>; "
            f"Example: !{alias} @Bob 100"
        )

    @classmethod
    async def prepare(cls, ctx) -> bool:
        args = ctx.argument.split()
        try:
            target_name, amount = args
        except ValueError:
            await cls.reply_usage(ctx)
            return False

        if target_name.startswith("@"):
            target_name = target_name[1:]

        if not target_name:
            await cls.reply_usage(ctx)
            return False

        amount = amount.replace(",", "")
        try:
            amount = int(amount)
        except ValueError:
            await cls.reply_usage(ctx)
            return False

        target = await jstv_db.get_viewer(ctx.db, ctx.channel, target_name)
        if target is None:
            await random_reply(ctx, REPLIES_INVALID_TARGET, target_name, amount)
            return False

        if not has_streamer_exempt(ctx.viewer):
            if target.id == ctx.viewer.id:
                await random_reply(ctx, REPLIES_TARGET_SELF, target_name, amount)
                return False

            if amount < 0:
                await random_reply(ctx, REPLIES_NEGATIVE_AMOUNT, target_name, amount)
                return False

            if amount == 0:
                await random_amount_reply(ctx, REPLIES_AMOUNT, target_name, amount)
                return False

        ctx.set_cache(Cache(
            target_name=target_name,
            target=target,
            amount=amount,
        ))

        return True

    @classmethod
    async def handle(cls, ctx) -> bool:
        assert ctx.cache
        target_name = ctx.cache.target_name
        target = ctx.cache.target
        amount = ctx.cache.amount

        if not has_streamer_exempt(ctx.viewer):
            # Make sure we have enough points
            if ctx.settings.base_cost + amount > ctx.viewer.points:
                await random_reply(ctx, REPLIES_NOT_ENOUGH_POINTS, target_name, amount)
                return False

            jstv_dbstate.adjust_viewer_points(ctx.viewer, -amount, (
                f"command {cls.key}: {amount} from {ctx.actorname} -> {target_name}"
            ))

        jstv_dbstate.adjust_viewer_points(target, amount, (
            f"command {cls.key}: {amount} from {ctx.actorname} -> {target_name}"
        ))

        await random_amount_reply(ctx, REPLIES_AMOUNT, target_name, amount)
        return True
