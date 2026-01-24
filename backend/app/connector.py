from typing import NamedTuple, Optional, Any
from contextlib import asynccontextmanager
import abc
import itertools
import asyncio
import logging
import json
import websockets

from .settings import MAX_INIT_ATTEMPTS, MAX_RECONNECT_DELAY
from .utils.asyncio import async_select


# ==============================================================================
# Config

MANAGER_NAME = "Manager"


# ==============================================================================
# ConnectorMessage

class ConnectorMessage(NamedTuple):
    """
    A message to be sent to a connector.
    WARNING: Auto-incremented message IDs are not thread-safe.
    """
    id: int  # The message ID
    sender: str  # The connector that sent the message
    receiver: str  # The connector to send the message to
    action: str  # The action to perform
    data: Any  # Any data

    _counter = itertools.count(1)  # Used to generate unique message IDs

    def __repr__(self):
        return f"<{type(self).__name__} #{self.id} {self.action} from {self.sender} to {self.receiver}>"

    @classmethod
    def make(cls, sender: str, receiver: str, action: str, data: Any):
        """Create a new message with a unique ID."""
        return cls(cls.next_id(), sender, receiver, action, data)

    @classmethod
    def next_id(cls):
        """Get the next available message ID."""
        return next(cls._counter)


# ==============================================================================
# ConnectorManager

class ConnectorManager:
    """Manage connectors and dispatch messages to and between them."""
    name: str
    logger: logging.Logger

    _connectors: dict[str, "BaseConnector"]
    _shutdown: asyncio.Event

    # A queue of messages to be sent to a connector, usually from another connector.
    # Each message is a tuple of (receiver, action, data).
    _msg_queue: asyncio.Queue[ConnectorMessage]

    def __init__(self, name: Optional[str] = None):
        self.name = name or MANAGER_NAME
        self.logger = logging.getLogger(self.name)

        self._connectors = {}
        self._shutdown = asyncio.Event()
        self._msg_queue = asyncio.Queue()

    def register(self, connector: "BaseConnector"):
        """Register a connector with the manager."""
        if connector.name in self._connectors:
            raise ValueError(f"Connector already registered: {connector.name}")

        self._connectors[connector.name] = connector
        self.logger.info("Registered connector: %s", connector.name)

    async def run(self):
        """Start the manager and all registered connectors."""
        tasks = [conn.connect_loop() for conn in self._connectors.values()]
        tasks.append(self.talk_loop())
        await asyncio.gather(*tasks)

    async def shutdown(self):
        """Shutdown the manager and all registered connectors."""
        self._shutdown.set()
        tasks = (conn.shutdown() for conn in self._connectors.values())
        await asyncio.gather(*tasks)

    async def talk_loop(self):
        """Continuously dispatch messages from the queue."""
        self._shutdown.clear()

        while True:
            try:
                stask = asyncio.create_task(self._shutdown.wait())
                qtask = asyncio.create_task(self._msg_queue.get())

                done = await async_select(stask, qtask)
                if stask in done:
                    break

                msg = qtask.result()
                conn = self._connectors.get(msg.receiver)

                if conn is None:
                    self.logger.warning("Connector not found; message: %r, data: %s", msg, msg.data)

                elif not conn._connected:
                    self.logger.warning("Connector not connected; message: %r, data: %s", msg, msg.data)

                else:
                    try:
                        # self.logger.debug(f"Delivering connector message: %r, data: %s", msg, msg.data)
                        await conn.talk_receive(msg)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        self.logger.exception("Exception processing connector message: %r, data: %s", msg, msg.data)

                self._msg_queue.task_done()

            except asyncio.CancelledError:
                self.logger.info("Received CancelledError, shutting down connector manager...")
                self._shutdown.set()
                raise

    async def talkto(self, sender: str, receiver: str, action: str, data: Any):
        """Queue a message to a specific connector."""
        await self._msg_queue.put(ConnectorMessage.make(sender, receiver, action, data))


# ==============================================================================
# BaseConnector

class BaseConnector(abc.ABC):
    name: str
    manager: ConnectorManager
    logger: logging.Logger
    _shutdown: asyncio.Event
    _connected: bool = False

    def __init__(self, manager: ConnectorManager, name: str):
        self.name = name
        self.manager = manager
        self.logger = manager.logger.getChild(name)
        self._shutdown = asyncio.Event()

        manager.register(self)

    async def shutdown(self):
        """Shutdown the connector."""
        self._shutdown.set()

    async def connect_loop(self):
        """Connect to the server, reconnecting if necessary."""
        self._shutdown.clear()
        reconnect_attempt = 0
        initializing = True

        while not self._shutdown.is_set():
            reconnect_attempt += 1

            if initializing and reconnect_attempt > MAX_INIT_ATTEMPTS:
                self.logger.info("Unable to connect, shutting down connector...")
                self._shutdown.set()
                break

            if reconnect_attempt > 1:
                delay = min(
                    MAX_RECONNECT_DELAY,
                    2 ** (reconnect_attempt - 1),
                )
                self.logger.info("Reconnecting in %d seconds...", delay)
                await asyncio.sleep(delay)

            if initializing:
                self.logger.info(f"Connecting [attempt {reconnect_attempt} of {MAX_INIT_ATTEMPTS}]...")
            else:
                self.logger.info("Reconnecting...")

            try:
                async with self.connect():
                    self._connected = True
                    reconnect_attempt = 0
                    initializing = False

                    await self.on_connected()
                    await self.main_loop()

            except asyncio.CancelledError:
                self.logger.info("Received CancelledError, shutting down connector...")
                self._shutdown.set()
                raise

            except Exception as e:
                await self.on_error(e)

            finally:
                if self._connected:
                    self._connected = False
                    await self.on_disconnected()

    @abc.abstractmethod
    @asynccontextmanager
    async def connect(self):
        """Connect to the server."""
        yield

    @abc.abstractmethod
    async def main_loop(self):
        """Main loop to run once a connection has been established."""
        ...

    @abc.abstractmethod
    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        """
        Receive a connector message and process it.
        Returns True if the message was handled, False otherwise.
        """
        ...

    async def on_connected(self):
        """Called after a connection has been established."""
        self.logger.info("Connection opened")

    async def on_disconnected(self):
        """Called when the connection has been closed."""
        self.logger.info("Connection closed")

    async def on_error(self, error: Exception):
        """Called when an error occurs while connected or connecting."""
        if isinstance(error, ConnectionError):
            self.logger.warning("Connection error in %s: %s", type(self).__name__, error)
        else:
            self.logger.exception("Error in %s: %s: %s", type(self).__name__, type(error).__name__, error)

    async def talk(self, action: str, data: Any):
        """Queue a message to this connector."""
        await self.manager.talkto(self.name, self.name, action, data)

    async def talkto(self, receiver: str, action: str, data: Any):
        """Queue a message to a specific connector."""
        await self.manager.talkto(self.name, receiver, action, data)


# ==============================================================================
# WebSocket Connector

class WebSocketConnector(BaseConnector):
    url: str
    _ws: Optional[websockets.ClientConnection] = None

    def __init__(self, manager: ConnectorManager, name: str, url: str):
        super().__init__(manager, name)
        self.url = url

    def _create_connection(self) -> websockets.connect:
        return websockets.connect(self.url)

    @asynccontextmanager
    async def connect(self):
        async with self._create_connection() as ws:
            self._ws = ws
            yield

    async def main_loop(self):
        if not self._ws:
            return

        async for message in self._ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                self.logger.exception("Invalid JSON: %s", message)
                continue

            try:
                await self.on_message(data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.exception("Exception processing WebSocket message")

    async def on_message(self, data: dict[Any, Any]):
        """Override in subclasses; can send messages using manager.talkto()."""
        self.logger.info("Received: %s", data)

    async def on_error(self, error: Exception):
        if isinstance(error, websockets.ConnectionClosedError):
            self.logger.error("Connection closed in %s: %s", type(self).__name__, error)
        else:
            await super().on_error(error)

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        self.logger.debug("Connector message received: %r, data: %s", msg, msg.data)

        if msg.action == "raw":
            await self.sendnow(msg.data)
            return True

        return False

    async def sendnow(self, data: Any):
        """Direct send to this connector."""
        if self._connected and self._ws:
            await self._ws.send(json.dumps(data))
            self.logger.info("Sent: %s", data)
