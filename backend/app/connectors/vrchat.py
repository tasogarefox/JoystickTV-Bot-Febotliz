from typing import ClassVar, Any, Callable, Coroutine
from contextlib import asynccontextmanager
import os
import asyncio
import threading
import logging

from pythonosc.udp_client import SimpleUDPClient
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from ..connector import ConnectorMessage, ConnectorManager, BaseConnector

OSCArg = float | int | bool
OSCCallback = Callable[[str, *tuple[OSCArg, ...]], Coroutine[Any, Any, None]]


# ==============================================================================
# Config

CLIENT_HOST = os.getenv("VRCHAT_CLIENT_HOST", "")
SERVER_HOST = os.getenv("VRCHAT_SERVER_HOST", "")
assert CLIENT_HOST, "Missing environment variable: VRCHAT_CLIENT_HOST"
assert SERVER_HOST, "Missing environment variable: VRCHAT_SERVER_HOST"

CLIENT_NAME = "VRChat"
SERVER_NAME = "VRChatReceiver"

ENABLE_SERVER = False


# ==============================================================================
# Helper functions

def parse_hostport(value: str) -> tuple[str, int]:
    try:
        host, port = value.rsplit(":", 1)
        port = int(port)
    except ValueError:
        raise ValueError("Invalid host:port format: %s" % value)

    return host, port


# ==============================================================================
# OSC Message

class OSCMessage(ConnectorMessage):
    address: str
    args: tuple

    def __init__(self, address: str, *args: OSCArg):
        self.address = address
        self.args = args

    def __repr__(self):
        return f"{self.__class__.__name__}(address={self.address!r}, args={self.args!r})"


# ==============================================================================
# VRChat Receiver

class VRChatReceiver:
    logger: logging.Logger
    callback: OSCCallback
    server: ThreadingOSCUDPServer
    dispatcher: Dispatcher
    thread: threading.Thread

    _loop: asyncio.AbstractEventLoop | None = None

    def __init__(self, url: str, callback: OSCCallback, *, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(SERVER_NAME)
        self.callback = callback
        self.dispatcher = self._create_dispatcher()
        self.server = self._create_server(url)
        self.thread = self._create_thread()

    def _create_dispatcher(self) -> Dispatcher:
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._on_param_callback)
        return dispatcher

    def _create_server(self, url: str) -> ThreadingOSCUDPServer:
        return ThreadingOSCUDPServer(
            parse_hostport(url),
            self.dispatcher,
        )

    def _create_thread(self) -> threading.Thread:
        return threading.Thread(
            target=self._start_server_thread,
            daemon=True,
        )

    async def start(self):
        self._loop = asyncio.get_event_loop()
        self.thread.start()

    async def shutdown(self):
        self.server.shutdown()

    async def join(self):
        while self.thread.is_alive():
            self.thread.join(timeout=0.1)

    def _start_server_thread(self):
        self.server.serve_forever()

    def _on_param_callback(self, address: str, *args: OSCArg):
        if self._loop is None:
            return

        def runner():
            try:
                asyncio.create_task(self.callback(address, *args))
            except Exception as e:
                self.logger.exception("Exception processing OSC message: address: %s, data: %s", address, args)

        self._loop.call_soon_threadsafe(runner)


# ==============================================================================
# VRChat Connector

class VRChatConnector(BaseConnector):
    NAME: ClassVar[str] = CLIENT_NAME

    _client: SimpleUDPClient
    _server: VRChatReceiver

    def __init__(self, manager: ConnectorManager):
        super().__init__(manager)

        self._client = self._create_client()
        self._server = self._create_server()

    def _create_client(self) -> SimpleUDPClient:
        return SimpleUDPClient(*parse_hostport(CLIENT_HOST))

    def _create_server(self) -> VRChatReceiver:
        logger = self.logger.getChild(SERVER_HOST)
        return VRChatReceiver(SERVER_HOST, self.on_param, logger=logger)

    def _create_connection(self) -> SimpleUDPClient:
        return self._client

    @asynccontextmanager
    async def connect(self):
        if not ENABLE_SERVER:
            yield
            return

        try:
            await self._server.start()
            yield
        finally:
            await self._server.shutdown()
            await self._server.join()

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        self.logger.info("Connector message received: %r, data: %s", msg, msg.data)

        if msg.action == "osc":
            if isinstance(msg.data, OSCMessage):
                await self.sendosc(msg.data.address, *msg.data.args)
            return True

        return False

    async def on_connected(self):
        await super().on_connected()

    async def on_disconnected(self):
        await super().on_disconnected()

    async def main_loop(self):
        await self._shutdown.wait()

    async def on_param(self, address: str, *args: OSCArg):
        if not address.startswith("/avatar/parameters/"):
            return

        self.logger.debug("OSC message received: %r, %r", address, args)

    async def sendosc(self, address: str, *args: OSCArg):
        self.logger.info("Sending OSC message: %r, %r", address, args)
        self._client.send_message(address, *args)
