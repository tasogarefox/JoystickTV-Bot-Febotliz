from app.connectors.obs import OBSConnector
from app.db.enums import AccessLevel
from app.handlers.jstv.commands import JSTVCommand, JSTVCommandSettings


# ==============================================================================
# Commands

class ViewerSignCommand(JSTVCommand):
    key = "feliz.clip"
    title = "Clip"
    description = "Create a clip by requesting OBS to save its replay buffer"

    settings = JSTVCommandSettings(
        aliases = ("clip",),
        min_access_level=AccessLevel.viewer,
        channel_cooldown=30,
    )

    @classmethod
    async def handle(cls, ctx) -> bool:
        obs = ctx.connector_manager.get(OBSConnector)
        if not obs:
            await ctx.reply("OBS not connected")
            return False

        success = await obs.save_replay_buffer()
        if not success:
            await ctx.reply("Failed to save replay buffer")
            return False

        await ctx.reply(f"Clip saved")
        return True
