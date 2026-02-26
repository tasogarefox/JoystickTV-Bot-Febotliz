from datetime import datetime

from app.db.enums import AccessLevel
from app.events import jstv as evjstv
from app.handlers import HandlerTags
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings
from app.handlers.jstv.events import db as dbevhandlers


# ==============================================================================
# Commands

class TestJSTVEventCommand(JSTVCommand):
    key = "core.test.tip"
    title = "Test Tip"
    description = "Send test tips"
    tags = frozenset({HandlerTags.hidden})

    settings = JSTVCommandSettings(
        aliases = ("testtip",),
        min_access_level=AccessLevel.streamer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        amount, _, tip_menu_item = ctx.argument.partition(" ")
        try:
            amount = int(amount)
        except ValueError:
            amount = 0

        await ctx.reply(
            f"Sending test tip of {amount} tokens",
        )

        evmsg = evjstv.JSTVTipped(
            isFake=True,
            event="StreamEvent",
            type="Tipped",
            id="FAKE",
            text="Test Tip",
            channelId=ctx.channel_id,
            createdAt=datetime.now(),
            metadata=evjstv.JSTVTipped.Metadata(
                who=ctx.actorname,
                what="Tipped",
                how_much=amount,
                tip_menu_item=tip_menu_item,
            )
        )

        await dbevhandlers.invoke_events(
            db=ctx.db,
            channel=ctx.channel,
            user=ctx.user,
            viewer=ctx.viewer,
            connector=ctx.connector,
            message=evmsg,
        )

        return True
