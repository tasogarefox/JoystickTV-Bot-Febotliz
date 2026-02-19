from app.handlers.jstv.events import JSTVChatTriggerHandler, JSTVEventHandlerSettings


# ==============================================================================
# Hnadlers

class CookieTriggerHandler(JSTVChatTriggerHandler):
    key = "feliz.cookie"
    title = "Throw Cookie"
    description = "Throw a cookie in Warudo"

    triggers = ("cookie",)

    settings = JSTVEventHandlerSettings(
        priority=0,
    )

    @classmethod
    async def handle_trigger(cls, ctx, trigger) -> bool:
        await ctx.connector.send_warudo("Cookie")
        return False

class DildoTriggerHandler(JSTVChatTriggerHandler):
    key = "feliz.dildo"
    title = "Throw Dildo"
    description = "Throw a dildo in Warudo"

    triggers = ("dildo", "penis", "dick")

    settings = JSTVEventHandlerSettings(
        priority=0,
    )

    @classmethod
    async def handle_trigger(cls, ctx, trigger) -> bool:
        await ctx.connector.send_warudo("Dildo")
        return False
