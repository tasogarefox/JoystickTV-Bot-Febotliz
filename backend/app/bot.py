import asyncio

from app import log
from app.connector import ConnectorManager
from app.connectors.joysticktv import JoystickTVConnector
from app.connectors.warudo import WarudoConnector
from app.connectors.streamerbot import StreamerBotConnector
from app.connectors.obs import OBSConnector
from app.connectors.buttplug import ButtplugConnector
from app.connectors.vrchat import VRChatConnector


# ==============================================================================
# Bot

class Bot(ConnectorManager):
    _initialized: bool = False

    def __init__(self):
        super().__init__(log.get_logger().name)

    async def init(self):
        if self._initialized:
            return

        self._initialized = True

        # Create and register connectors
        JoystickTVConnector(self)
        WarudoConnector(self)
        StreamerBotConnector(self)
        OBSConnector(self)
        ButtplugConnector(self)
        VRChatConnector(self)

    async def run(self):
        await self.init()
        await super().run()


# ==============================================================================
# __main__

if __name__ == "__main__":
    try:
        asyncio.run(Bot().run())
    except asyncio.exceptions.CancelledError:
        pass
