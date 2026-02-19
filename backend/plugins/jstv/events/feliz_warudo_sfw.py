from app.handlers.jstv.events import JSTVChatTriggerHandler, JSTVEventHandlerSettings


# ==============================================================================
# Hnadlers

class TrobbioTriggerHandler(JSTVChatTriggerHandler):
    key = "feliz.trobbio"
    title = "Trobbio!"
    description = "use Trobbio action in Warudo <3"

    triggers = ("trobbio",)

    settings = JSTVEventHandlerSettings(
        priority=0,
    )

    @classmethod
    async def handle_trigger(cls, ctx, trigger) -> bool:
        await ctx.connector.send_warudo("Trobbio")
        return False

class BlahajTriggerHandler(JSTVChatTriggerHandler):
    key = "feliz.blahaj"
    title = "Blahaj!"
    description = "Throw blahaj in Warudo <3"

    triggers = ("blahaj",)

    settings = JSTVEventHandlerSettings(
        priority=0,
    )

    @classmethod
    async def handle_trigger(cls, ctx, trigger) -> bool:
        await ctx.connector.send_warudo("Blahaj")
        return False
