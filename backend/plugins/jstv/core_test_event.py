from app.db.enums import AccessLevel
from app.jstv import jstv_web, jstv_error
from app.handlers import HandlerTags
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class TestJSTVEventCommand(JSTVCommand):
    key = "core.test.event"
    title = "Test JSTV Event"
    description = "Ask JoystickTV to send a test event"
    tags = frozenset({HandlerTags.hidden})

    settings = JSTVCommandSettings(
        aliases = ("testevent",),
        min_access_level=AccessLevel.streamer,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        event, _, data = ctx.argument.partition(" ")
        if not event:
            await ctx.reply(
                f"Usage: {ctx.alias} <event> [data]",
                mention=True,
            )
            return False

        try:
            await jstv_web.send_test_event(event, data)
        except jstv_error.JSTVWebError:
            await ctx.reply(
                f"Failed to send test event: {event} {data}",
            )
            return False

        await ctx.reply(
            f"Sent test event: {event} {data}",
        )
        return True
