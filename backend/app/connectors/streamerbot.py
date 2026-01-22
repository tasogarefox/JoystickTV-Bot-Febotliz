from typing import Optional, Any
import os
import uuid

from ..connector import ConnectorMessage, ConnectorManager, WebSocketConnector


# ==============================================================================
# Config

WS_HOST = os.getenv("STREAMERBOT_WS_HOST")
assert WS_HOST, "Missing environment variable: STREAMERBOT_WS_HOST"

NAME = "StreamerBot"
URL = WS_HOST


# ==============================================================================
# StreamerBot Connector

class StreamerBotConnector(WebSocketConnector):
    def __init__(self, manager: ConnectorManager, name: Optional[str] = None, url: Optional[str] = None):
        super().__init__(manager, name or NAME, url or URL)

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        if await super().talk_receive(msg):
            return True

        if msg.action == "action":
            await self.sendnow({
                "request": "DoAction",
                "id": str(uuid.uuid4()),
                "action": {
                    "name": msg.data["name"],
                },
                "args": msg.data.get("args") or {},
            })
            return True

        elif msg.action == "trigger":
            await self.sendnow({
                "request": "Trigger",
                "id": str(uuid.uuid4()),
                "trigger": {
                    "name": msg.data["name"],
                },
                "args": msg.data.get("args") or {},
            })
            return True

        return False

    async def on_message(self, data: dict[Any, Any]):
        if 'request' in data:
            if data["request"] == "Hello":
                self.logger.info("Received Hello")
                return

        self.logger.info("Received: %s", data)

        if not self._connected:
            return

        ...
