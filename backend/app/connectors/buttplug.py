from typing import NamedTuple, Optional, Any, Collection, Iterator, Iterable
from enum import IntEnum
from dataclasses import dataclass
from contextlib import asynccontextmanager
import os
import asyncio
from datetime import datetime, timedelta

from buttplug import (
    Client, WebsocketConnector, ProtocolSpec,
    ServerNotFoundError, DisconnectedError,
)

from app.utils.asyncio import async_select
from app.connector import ConnectorMessage, ConnectorManager, BaseConnector
from app.routes.ws import vibegraph


# ==============================================================================
# Config

WS_HOST = os.getenv("BUTTPLUG_WS_HOST")
assert WS_HOST, "Missing environment variable: BUTTPLUG_WS_HOST"

NAME = "Buttplug"
URL = WS_HOST


# ==============================================================================
# VibeFrame

class VibeTargetMode(IntEnum):
    OVERRIDE = 0
    EXCLUSIVE = 1

class VibeTarget(NamedTuple):
    device: str
    value: float

@dataclass(frozen=True, slots=True)
class VibeFrame:
    duration: float = 30.0
    value: float = 0.5
    targets: tuple[VibeTarget, ...] = tuple()
    mode: VibeTargetMode = VibeTargetMode.OVERRIDE

    @classmethod
    def new_override(
        cls,
        duration: float = duration,
        value: float = value,
        targets: Iterable[VibeTarget] = tuple(),
    ):
        return cls(
            duration,
            value,
            tuple(targets),
            VibeTargetMode.OVERRIDE,
        )

    @classmethod
    def new_exclusive(
        cls,
        duration: float,
        targets: Iterable[VibeTarget],
    ):
        return cls(
            duration,
            0,
            tuple(targets),
            VibeTargetMode.EXCLUSIVE,
        )

    def __post_init__(self):
        if self.mode == VibeTargetMode.EXCLUSIVE and not self.targets:
            raise ValueError("Exclusive frame must have targets")

    def __repr__(self) -> str:
        if self.mode == VibeTargetMode.OVERRIDE:
            return f"<{self.__class__.__name__} {self.duration}s to {self.value} override {self.targets}>"
        if self.mode == VibeTargetMode.EXCLUSIVE:
            return f"<{self.__class__.__name__} {self.duration}s to exclusive {self.targets}>"
        return super().__repr__()

    def __bool__(self) -> bool:
        if self.mode == VibeTargetMode.EXCLUSIVE and not self.targets:
            return False
        return self.duration > 0

    @property
    def is_override(self) -> bool:
        return self.mode == VibeTargetMode.OVERRIDE

    @property
    def is_exclusive(self) -> bool:
        return self.mode == VibeTargetMode.EXCLUSIVE

    def get_devices(self) -> set[str]:
        return {x.device for x in self.targets}

    def resolve_devices(self, all_devices: Iterable[str]) -> set[str]:
        return (
            set(all_devices) if self.is_override else
            set(x.device for x in self.targets if x.device in all_devices)
        )

@dataclass(frozen=True, slots=True)
class VibeGroup:
    frames: tuple[VibeFrame, ...]

    channel_id: str = ""
    username: str = ""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {len(self.frames)} items for {self.get_duration()}s>"

    def __bool__(self) -> bool:
        return bool(self.frames)

    def __len__(self) -> int:
        return len(self.frames)

    def __iter__(self) -> Iterator[VibeFrame]:
        return iter(self.frames)

    def get_duration(self) -> float:
        return sum(item.duration for item in self.frames)


# ==============================================================================
# Buttplug Connector

class ButtplugConnector(BaseConnector):
    url: str
    client: Client

    _devices: set[str]

    _vibe_queue: asyncio.Queue[VibeGroup]
    _disabled_until: datetime

    def __init__(self, manager: ConnectorManager, name: Optional[str] = None, url: Optional[str] = None):
        super().__init__(manager, name or NAME)
        self.url = url or URL
        self.client = self._create_client()
        self._devices = set()
        self._vibe_queue = asyncio.Queue()
        self._disabled_until = datetime.now()

    def _create_client(self) -> Client:
        logger = self.logger.getChild("Client")
        return Client(logger.name, ProtocolSpec.v3)

    def _create_connection(self) -> WebsocketConnector:
        return WebsocketConnector(self.url, logger=self.client.logger)

    async def _update_devices(self) -> set[str]:
        devices = set(x.name for x in self.client.devices.values())
        if devices != self._devices:
            self._devices = devices
            self.logger.info("Devices updated: %s", devices)
            await vibegraph.bcast_update_devices(devices)
        return devices

    @asynccontextmanager
    async def connect(self):
        try:
            self.connector = self._create_connection()
            await self.client.connect(self.connector)
            yield
        finally:
            if self.client.connected:
                await self.client.disconnect()

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        self.logger.info("Connector message received: %r, data: %s", msg, msg.data)

        if msg.action == "stop":
            try:
                while True:
                    self._vibe_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            await self._vibe([x.name for x in self.client.devices.values()], 0)
            return True

        elif msg.action == "disable":
            if isinstance(msg.data, (int, float)):
                until = datetime.now() + timedelta(seconds=msg.data)
                self._disabled_until = max(self._disabled_until, until)
            return True

        elif msg.action == "vibe":
            if isinstance(msg.data, VibeFrame):
                await self._vibe_queue.put(VibeGroup((msg.data,)))
            elif isinstance(msg.data, VibeGroup):
                await self._vibe_queue.put(msg.data)
            return True

        return False

    async def on_connected(self):
        await super().on_connected()

    async def on_error(self, error: Exception):
        if isinstance(error, ServerNotFoundError):
            self.logger.warning("Server not found in %s: %s", type(self).__name__, error)
        else:
            return await super().on_error(error)

    async def main_loop(self):
        await asyncio.gather(
            self._scan_loop(),
            self._vibe_loop(),
        )

    async def _scan_loop(self):
        self.logger.info("Device-scan starting...")
        await self.client.start_scanning()
        await asyncio.sleep(10)
        await self.client.stop_scanning()
        await self._update_devices()
        self.logger.info("Device-scan complete")

        shutdown = False
        while not shutdown:
            tshutdown = asyncio.create_task(self._shutdown.wait())
            tsleep = asyncio.create_task(asyncio.sleep(5))

            done = await async_select(tshutdown, tsleep)
            shutdown = tshutdown in done
            if shutdown:
                break

            await self._update_devices()

    async def _vibe_loop(self):
        shutdown = False
        devices = set()
        while not shutdown:
            tshutdown = asyncio.create_task(self._shutdown.wait())
            qtask = asyncio.create_task(self._vibe_queue.get())

            done = await async_select(tshutdown, qtask)
            shutdown = tshutdown in done
            if shutdown:
                break

            group = qtask.result()

            self.logger.info("VibeGroup: %s; queue remaining: %d", group, self._vibe_queue.qsize())

            if not group:
                continue

            await self._update_devices()
            await vibegraph.bcast_set_group(group)

            for i, vibe in enumerate(group.frames):
                if not vibe:
                    continue

                while not shutdown and self._disabled_until > datetime.now():
                    delay = (self._disabled_until - datetime.now()).total_seconds()

                    msg = f"Vibe: disabled for {delay:.2f} seconds"
                    self.logger.info(msg)
                    await self.talkto("JoystickTV", "chat", {
                        "text": msg,
                        "channelId": group.channel_id,
                    })

                    tshutdown = asyncio.create_task(self._shutdown.wait())
                    tshutdown = asyncio.create_task(asyncio.sleep(delay))

                    done = await async_select(tshutdown, tshutdown)
                    shutdown = tshutdown in done

                if shutdown:
                    break

                new_devices = vibe.resolve_devices(
                    x.name for x in self.client.devices.values()
                )

                old_devices = devices - new_devices
                if old_devices:
                    await self._vibe(old_devices, 0)

                devices = new_devices

                self.logger.info("VibeFrame: %r", vibe)

                if i == 0:
                    await self.talkto("JoystickTV", "chat", {
                        "text": (
                            f"Vibe: {len(group)} items for {round(group.get_duration())}s"
                            + (f" at {round(vibe.value*100)}%" if len(group) == 1 else "")
                            + f" by {group.username}"
                            + f"; queued: {self._vibe_queue.qsize()}"
                        ),
                        "channelId": group.channel_id,
                    })

                await self._vibe(devices, vibe.value)
                await vibegraph.bcast_advance(vibe.duration)
                await asyncio.sleep(vibe.duration)

            self._vibe_queue.task_done()

            if self._vibe_queue.empty():
                if devices:
                    await self._vibe(devices, 0)

                await vibegraph.bcast_reset_group()

            if shutdown:
                break

                msg = "Vibe: queue is empty"
                self.logger.info(msg)
                await self.talkto("JoystickTV", "chat", {
                    "text": msg,
                    "channelId": group.channel_id,
                })

    async def _vibe(self, device_names: Collection[str], amount: float):
        for device in self.client.devices.values():
            if device.name not in device_names:
                continue

            for actuator in device.actuators:
                try:
                    await actuator.command(amount)
                except DisconnectedError:
                    pass
