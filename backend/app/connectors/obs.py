from typing import Optional
from contextlib import asynccontextmanager
import os
import asyncio
from datetime import datetime, timedelta

from obswsc.client import ObsWsClient
from obswsc.data import Request

from ..utils.datetime import utcnow, utcmin
from ..utils.asyncio import async_select
from ..connector import ConnectorMessage, ConnectorManager, BaseConnector


# ==============================================================================
# Config

WS_HOST = os.getenv("OBS_WS_HOST")
WS_PASSWORD = os.getenv("OBS_WS_PASSWORD", "")
assert WS_HOST, "Missing environment variable: OBS_WS_HOST"
# assert WS_PASSWORD, "Missing environment variable: OBS_WS_PASSWORD"

NAME = "OBS"
URL = WS_HOST

CLIP_COOLDOWN = 30  # clip command cooldown in seconds


# ==============================================================================
# OBS Connector

class OBSConnector(BaseConnector):
    url: str
    _client: ObsWsClient
    _last_clip: datetime = utcmin

    def __init__(self, manager: ConnectorManager, name: Optional[str] = None, url: Optional[str] = None):
        super().__init__(manager, name or NAME)
        self.url = url or URL
        self._client = self._create_client()

    def _create_client(self) -> ObsWsClient:
        return ObsWsClient(self.url, WS_PASSWORD)

    def _create_connection(self) -> ObsWsClient:
        return self._client

    @asynccontextmanager
    async def connect(self):
        async with self._create_connection() as client:
            self._client = client
            yield

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        self.logger.info("Connector message received: %r, data: %s", msg, msg.data)

        if msg.action == "clip":
            await self.save_replay_buffer()
            return True

        return False

    async def on_connected(self):
        await super().on_connected()

        # Start replay buffer
        resp = await self.request(Request("StartReplayBuffer"))
        self.logger.info("Replay buffer started: %s", resp)

    async def on_disconnected(self):
        await self._client.disconnect()

    # async def on_error(self, error: Exception):
    #     if isinstance(error, ...):
    #         self.logger.warning("... in %s: %s", type(self).__name__, error)
    #     else:
    #         return await super().on_error(error)

    async def main_loop(self):
        await self._shutdown.wait()

    async def save_replay_buffer(self):
        now = utcnow()
        if (now - self._last_clip).total_seconds() < CLIP_COOLDOWN:
            return
        self._last_clip = now

        resp = await self.request(Request("SaveReplayBuffer"))
        self.logger.info("Replay buffer saved: %s", resp)

        # resp = await self.request(Request("GetLastReplayBufferReplay"))
        # self.logger.info("Last replay: %s", resp)
        # file = resp.res_data.get("savedReplayPath")

    async def request(self, req: Request) -> dict:
        return await self._client.request(req)
