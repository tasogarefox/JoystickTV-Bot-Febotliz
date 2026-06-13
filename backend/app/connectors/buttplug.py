from typing import (
    NamedTuple, ClassVar, Any, Union,
    Coroutine, Collection, Iterator, Iterable,
)
from enum import IntEnum
from dataclasses import dataclass
from contextlib import asynccontextmanager
import os
import asyncio
import random
from datetime import datetime, timedelta

from buttplug import (
    Client, WebsocketConnector, ProtocolSpec,
    ServerNotFoundError, DisconnectedError, ConnectorError, DeviceServerError,
)

from app.settings import getenv_list
from app.connector import ConnectorMessage, ConnectorManager, BaseConnector
from app.utils.asyncio import async_select


# ==============================================================================
# Config

ADD_FAKE_DEVICE = False  # Add fake device for testing
CHAT_VIBE_INFO = False
VIBE_CHECK_INTERVAL = 0.1

WS_HOST = os.getenv("BUTTPLUG_WS_HOST")
assert WS_HOST, "Missing environment variable: BUTTPLUG_WS_HOST"

DEVICE_BLACKLIST = getenv_list("BUTTPLUG_DEVICE_BLACKLIST")

NAME = "Buttplug"
URL = WS_HOST


# ==============================================================================
# Functions

def _parse_value_float(
    source: str,
    *,
    name: str,
    suffix: str = "",
) -> float:
    if suffix and source.endswith(suffix):
        source = source[:-len(suffix)]

    try:
        return float(source)
    except ValueError:
        raise ValueError(f"Invalid {name} value {source!r}")

def _parse_value_range(
    source: str,
    *,
    name: str,
    suffix: str = "",
) -> float:
    min_part, _, max_part = source.partition("-")

    value = _parse_value_float(min_part, name=name, suffix=suffix)
    if not max_part:
        return value

    max_value = _parse_value_float(max_part, name=name, suffix=suffix)

    return random.uniform(value, max_value)

def _parse_value_ramps(
    source: str,
    prev_value: float | None = None,
    *,
    name: str,
    suffix: str = "",
) -> list[float]:
    values = []

    parts = source.split("..")
    if not parts:
        raise ValueError(f"Invalid empty {name} value")

    for i, part in enumerate(parts):
        if part == "":  # Leading ".."
            if i != 0:
                raise ValueError(f"Invalid empty {name} segment")

            if prev_value is None:
                raise ValueError(f"Cannot start {name} with '..' without previous value")

            values.append(prev_value)
            continue

        value = _parse_value_range(part, name=name, suffix=suffix)
        values.append(value)

    return values

def parse_vibes(
    vibestr: str,
    *,
    max_duration: float = 3600.0,
) -> tuple["VibeFrame", ...]:
    sections: list[tuple[VibeFrame, ...]] = []
    cur_section: list[VibeFrame] = []

    # Previous/starting values (uses class defaults if not specified)
    prev_intensities: tuple[float, ...] = ()
    prev_duration: float = 30
    prev_devices: tuple[str, ...] = ()

    # Values for current action
    cur_intensities: list[float] | None = None
    cur_duration: float | None = None
    cur_devices: list[str] | None = None

    def flush_cur_action() -> bool:
        """Flush the current action into the list."""
        nonlocal prev_intensities, prev_duration, prev_devices
        nonlocal cur_intensities, cur_duration, cur_devices

        # If the current action is empty, do nothing
        if cur_intensities is None and cur_duration is None:
            return False

        # Merge the current action values with the previous
        cur_intensities = cur_intensities if cur_intensities is not None else list(prev_intensities)
        cur_duration = max(0, cur_duration) if cur_duration is not None else prev_duration
        cur_devices = cur_devices if cur_devices is not None else list(prev_devices)

        # Ensure we have at least one intensity
        if not cur_intensities:
            return False

        # Normalize to at least 2 segments
        segments = cur_intensities if len(cur_intensities) > 1 else [cur_intensities[0], cur_intensities[0]]

        seg_count = len(segments) - 1
        seg_duration = cur_duration / seg_count

        for seg_idx in range(seg_count):
            start = segments[seg_idx]
            stop = segments[seg_idx + 1]

            # Determine number of steps for this segment
            count = max(1, int(min(
                abs(stop - start) / 0.05 + 1,
                seg_duration / 0.2,
            )))

            step_intensity = (stop - start) / (count - 1) if count > 1 else 0
            step_duration = seg_duration / count

            # If flat, use midpoint
            if step_intensity == 0:
                start = (start + stop) / 2

            for i in range(count):
                intensity = start + step_intensity * i

                if not cur_devices:
                    action = VibeFrame.new_override(step_duration, intensity)
                else:
                    action = VibeFrame.new_exclusive(
                        step_duration,
                        (VibeTarget(x, intensity) for x in cur_devices),
                    )

                cur_section.append(action)

        # Update previous values
        prev_intensities = tuple(cur_intensities)
        prev_duration = cur_duration
        prev_devices = tuple(cur_devices)

        # Reset current values
        cur_intensities = None
        cur_duration = None
        cur_devices = None

        return True

    def flush_cur_section() -> bool:
        """Flush the current section into the list."""
        nonlocal sections, cur_section

        # Flush the current action
        flush_cur_action()

        # If the current section is empty, do nothing
        if not cur_section:
            return False

        # Add section
        sections.append(tuple(cur_section))

        # Reset current section
        cur_section.clear()

        return True

    # Parse the arguments
    # NOTE: Raise ValueError if the arguments are invalid
    for arg in vibestr.split():
        arg = arg.strip()
        if not arg:
            continue

        if not arg[0].isdigit() and arg[0] != ".":  # This is a device name
            # DISABLED: The following line disables the use of device names.
            raise ValueError(f"Invalid argument {arg!r}")

            arg_lower = arg.lower()
            # NOTE: Devices never flush, instead they are grouped together.
            #       They can however be reset.
            if arg_lower in ["clear", "none", "all"]:
                # NOTE: An empty list will be treated as "all" devices.
                cur_devices = []
                continue

            if cur_devices is None:
                cur_devices = []

            cur_devices.append(arg)
            continue

        elif arg.endswith("%"):  # This is an intensity in percent:
            if cur_intensities is not None:
                flush_cur_action()

            try:
                values = _parse_value_ramps(
                    arg,
                    prev_intensities[-1] if prev_intensities else None,
                    name="intensity",
                    suffix="%",
                )
            except ValueError as e:
                raise ValueError(f"{e}; in {arg!r}")

            cur_intensities = [x / 100 for x in values]

        elif arg.endswith("s"):  # This is a time
            if cur_duration is not None:
                flush_cur_action()

            try:
                cur_duration = _parse_value_range(
                    arg,
                    name="time",
                    suffix="s",
                )
            except ValueError as e:
                raise ValueError(f"{e}; in {arg!r}")

        elif any(arg.endswith(x) for x in "xr"):  # Repeat the last section
            # Note: If current section is empty, the previous section will be used instead
            flush_cur_section()
            if not sections:
                continue

            prev_section = sections[-1]

            repeat = 1
            if len(arg) > 1:
                try:
                    repeat = int(arg[:-1]) - 1
                except ValueError:
                    raise ValueError(f"Invalid repeat format {arg!r}")

            for _ in range(min(100, repeat)):
                sections.append(prev_section)

        elif any(arg.endswith(x) for x in "Sdt"):  # Repeat for the given duration
            # Note: If current section is empty, the previous section will be used instead
            flush_cur_section()
            if not sections:
                continue

            duration = 1
            if len(arg) > 1:
                try:
                    duration = int(arg[:-1]) - 1
                except ValueError:
                    raise ValueError(f"Invalid duration format {arg!r}")
                duration = max(1, duration)

            old_section = sections.pop()
            old_duration = sum(action.duration for action in old_section)
            if old_duration <= 0 or duration / old_duration < 0.01:
                ValueError(
                    f"Section duration ({old_duration}s) is too short for "
                    f"requested repeat duration ({duration}s)"
                )

            time = 0
            new_section = []
            while time < duration:
                for frame in old_section:
                    itime = min(frame.duration, duration - time)

                    # Skip frames that are empty
                    if itime <= 0:
                        continue

                    time += frame.duration

                    # Shorten frame if needed
                    if itime < frame.duration:
                        frame = VibeFrame(
                            duration=itime,
                            intensity=frame.intensity,
                            targets=frame.targets,
                            mode=frame.mode,
                        )

                    # Append frame
                    new_section.append(frame)

            # Insert adjusted section
            if new_section:
                sections.append(tuple(new_section))

        else:  # Invalid argument
            raise ValueError(f"Invalid argument {arg!r}")

    else:
        # Flush the last frame and section, if any
        flush_cur_section()

    if not sections:
        raise ValueError("No actions specified")

    # If there are no sections, there is nothing to do
    if not sections:
        return tuple()

    # Flatten, limit duration and return
    vibes = []
    total_duration: float = 0
    stop = False
    for section in sections:
        for action in section:
            if action.duration <= 0:
                continue

            total_duration += action.duration

            overflow_duration = total_duration - max_duration
            if overflow_duration > 0:
                stop = True
                action = VibeFrame(
                    duration=action.duration - overflow_duration,
                    intensity=action.intensity,
                    targets=action.targets,
                    mode=action.mode,
                )

            if action.duration > 0:
                vibes.append(action)

            if stop:
                break

        if stop:
            break

    return tuple(vibes)


# ==============================================================================
# VibeFrame

class VibeTargetMode(IntEnum):
    OVERRIDE = 0
    EXCLUSIVE = 1

class VibeTarget(NamedTuple):
    device: str
    intensity: float

    def __str__(self) -> str:
        return f"{self.device}={round(self.intensity, 2)}"

@dataclass(frozen=True, slots=True)
class VibeFrame:
    duration: float = 30.0
    intensity: float = 0.5
    targets: tuple[VibeTarget, ...] = tuple()
    mode: VibeTargetMode = VibeTargetMode.OVERRIDE

    @classmethod
    def new_override(
        cls,
        duration: float = duration,
        intensity: float = intensity,
        targets: Iterable[VibeTarget] = tuple(),
    ):
        return cls(
            duration,
            intensity,
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

    def __str__(self) -> str:
        if self.mode == VibeTargetMode.OVERRIDE:
            return (
                f"<{self.__class__.__name__}"
                f" {round(self.duration, 2)}s"
                f" at {round(self.intensity, 2)}"
                f" override {self.targets}"
                f">"
            )

        if self.mode == VibeTargetMode.EXCLUSIVE:
            return (
                f"<{self.__class__.__name__}"
                f" {round(self.duration, 2)}s"
                f" at exclusive"
                f" {self.targets}"
                f">"
            )

        return super().__str__()

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

    channel_id: str | None = None
    username: str | None = None

    def __str__(self) -> str:
        return (
            f"<{self.__class__.__name__}"
            f" {len(self)} items"
            f" for {round(self.get_duration(), 2)}s"
            f">"
        )

    def __bool__(self) -> bool:
        return bool(self.frames)

    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, index: int) -> VibeFrame:
        return self.frames[index]

    def __iter__(self) -> Iterator[VibeFrame]:
        return iter(self.frames)

    def get_duration(self) -> float:
        return sum(item.duration for item in self)


# ==============================================================================
# Buttplug Connector

class ButtplugConnector(BaseConnector):
    NAME: ClassVar[str] = NAME

    client: Client

    _device_cache: set[str]

    _vibe_queue: asyncio.Queue[VibeGroup]
    _cur_vibe_group: VibeGroup | None = None
    _delayed_until: datetime

    def __init__(self, manager: ConnectorManager):
        super().__init__(manager)
        self.client = self._create_client()
        self._device_cache = set()
        self._vibe_queue = asyncio.Queue()
        self._delayed_until = datetime.now()

    def _create_client(self) -> Client:
        logger = self.logger.getChild("Client")
        return Client(logger.name, ProtocolSpec.v3)

    def _create_connection(self) -> WebsocketConnector:
        return WebsocketConnector(URL, logger=self.client.logger)

    @asynccontextmanager
    async def connect(self):
        try:
            self.connector = self._create_connection()
            await self.client.connect(self.connector)
            yield
        finally:
            asyncio.create_task(self.__try_disconnect())

    async def __try_disconnect(self) -> None:
        if self.client.connected:
            try:
                await self.client.disconnect()
            except ConnectorError as e:
                self.logger.warning("Error while disconnecting: %s", e)

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        self.logger.info("Connector message received: %r, data: %s", msg, msg.data)

        if msg.action in ["clear", "stop"]:
            await self.clear()
            return True

        elif msg.action in ["skip", "next"]:
            await self.skip()
            return True

        elif msg.action in ["delay", "disable"]:
            if isinstance(msg.data, (int, float)):
                await self.delay(msg.data)
            return True

        elif msg.action == "vibe":
            if isinstance(msg.data, (VibeGroup, VibeFrame)):
                await self.enqueue(msg.data)
            return True

        return False

    async def on_connected(self):
        await super().on_connected()

    async def on_error(self, error: Exception):
        if isinstance(error, ServerNotFoundError):
            self.logger.warning("Server not found in %s: %s", type(self).__name__, error)
        else:
            return await super().on_error(error)

    def _get_devices(self) -> set[str]:
        return set(
            x.name
            for x in self.client.devices.values()
            if x.name not in DEVICE_BLACKLIST
        )

    @property
    def has_devices(self) -> bool:
        return any(
            x.name not in DEVICE_BLACKLIST
            for x in self.client.devices.values()
        ) or ADD_FAKE_DEVICE

    async def enqueue(self, vibe: VibeGroup | VibeFrame) -> None:
        group = vibe if isinstance(vibe, VibeGroup) else VibeGroup((vibe,))
        await self._vibe_queue.put(group)

    async def clear(self) -> None:
        try:
            while True:
                self._vibe_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        self._cur_vibe_group = None

        await self._vibe([x.name for x in self.client.devices.values()], 0)

    async def skip(self) -> None:
        self._cur_vibe_group = None

    async def delay(self, seconds: float) -> None:
        now = datetime.now()
        until = now + timedelta(seconds=seconds)
        self._delayed_until = max(self._delayed_until, until)

        group = self._cur_vibe_group
        if group:
            delay = (until - now).total_seconds()
            log_msg = f"Vibe: disabled for {delay:.1f} seconds"
            self.logger.info(log_msg)
            await self.talkto("JoystickTV", "chat", {
                "text": log_msg,
                "channelId": group.channel_id or "",
            })

    async def main_loop(self):
        await async_select(
            asyncio.create_task(self._scan_loop()),
            asyncio.create_task(self._vibe_loop()),
        )

    async def _scan_loop(self):
        self.logger.info("Device-scan starting...")
        await self.client.start_scanning()
        await asyncio.sleep(10)
        await self.client.stop_scanning()
        await self._update_device_cache()
        self.logger.info("Device-scan complete")

        shutdown = False
        while not shutdown:
            tshutdown = asyncio.create_task(self._shutdown.wait())
            tsleep = asyncio.create_task(asyncio.sleep(5))

            done = await async_select(tshutdown, tsleep)
            shutdown = tshutdown in done
            if shutdown:
                break

            await self._update_device_cache()

    async def _vibe_loop(self):
        from app.routes.ws import vibegraph

        devices: set[str] = set()

        shutdown = False
        while not shutdown:
            tshutdown = asyncio.create_task(self._shutdown.wait())
            tqueue = asyncio.create_task(self._vibe_queue.get())

            done = await async_select(tshutdown, tqueue)
            shutdown = tshutdown in done
            if shutdown:
                break

            group = self._cur_vibe_group = tqueue.result()

            self.logger.info("VibeGroup: %s; queue remaining: %d", group, self._vibe_queue.qsize())

            if not group:
                continue

            await self._update_device_cache()
            await vibegraph.bcast_update_devices(self._device_cache)
            await vibegraph.bcast_set_group(group)

            for i, vibe in enumerate(x for x in group.frames if x):
                shutdown = await self._handle_vibe_frame(devices, group, None)
                if shutdown:
                    break

                if group is not self._cur_vibe_group:
                    break

                all_devices = self._get_devices()
                new_devices = vibe.resolve_devices(all_devices)
                old_devices = devices - new_devices
                devices = new_devices

                if old_devices:
                    await self._vibe(old_devices, 0)

                self.logger.debug("VibeFrame: %r", vibe)

                if i == 0 and CHAT_VIBE_INFO:
                    await self.talkto("JoystickTV", "chat", {
                        "text": (
                            f"Vibe: {len(group)} items for {round(group.get_duration())}s"
                            + (f" at {round(vibe.intensity*100)}%" if len(group) == 1 else "")
                            + f" by {group.username or 'unknown'}"
                            + f"; queued: {self._vibe_queue.qsize()}"
                        ),
                        "channelId": group.channel_id or "",
                    })

                await asyncio.gather(
                    self._handle_vibe_frame(devices, group, vibe),
                    vibegraph.bcast_advance(vibe.duration),
                )

            self._vibe_queue.task_done()

            if shutdown:
                await self._vibe(devices, 0)
                break

            if not self._vibe_queue.empty():
                continue

            tasks = [
                vibegraph.bcast_reset_group(),
            ]

            if devices:
                tasks.append(self._vibe(devices, 0))

            if CHAT_VIBE_INFO:
                msg = "Vibe: queue is empty"
                self.logger.info(msg)
                tasks.append(self.talkto("JoystickTV", "chat", {
                    "text": msg,
                    "channelId": group.channel_id or "",
                }))

            await asyncio.gather(*tasks)

    async def _handle_vibe_frame(
        self,
        devices: Collection[str],
        group: VibeGroup,
        vibe: VibeFrame | None,
    ) -> bool:
        from app.routes.ws import vibegraph

        vibe_delay: float = vibe.duration if vibe is not None else 0
        shutdown = self._shutdown.is_set()
        active = False
        mult = 1.0

        async def wait_for_shutdown(timeout: float):
            nonlocal shutdown
            shutdown = await self._wait_for_shutdown(timeout)

        while not shutdown:
            tasks: list[Coroutine[Any, Any, None]] = []
            now = datetime.now()
            delay: float = 0

            if vibegraph.config.paused:
                delay = VIBE_CHECK_INTERVAL

                if vibe is not None and active:
                    active = False
                    tasks.append(self._vibe(devices, 0))

            elif self._delayed_until > now:
                total_delay = (self._delayed_until - now).total_seconds()
                delay = min(total_delay, VIBE_CHECK_INTERVAL)

                if vibe is not None and active:
                    active = False
                    tasks.append(self._vibe(devices, 0))

            elif vibe_delay > 0:
                delay = min(vibe_delay, VIBE_CHECK_INTERVAL)
                vibe_delay -= delay

                if vibe is not None:
                    new_mult = vibegraph.config.strength / 100
                    if not active or new_mult != mult:
                        active = True
                        mult = new_mult
                        tasks.append(self._vibe(devices, vibe.intensity * mult))

            if delay <= 0:
                break

            await asyncio.gather(
                wait_for_shutdown(delay),
                *tasks,
            )

            if shutdown:
                break

            if vibegraph.clear_queue:
                vibegraph.clear_queue = False
                await self.clear()
                break

        return shutdown

    async def _wait_for_shutdown(self, timeout: float) -> bool:
        tshutdown = asyncio.create_task(self._shutdown.wait())
        tsleep = asyncio.create_task(asyncio.sleep(timeout))

        done = await async_select(tshutdown, tsleep)
        return tshutdown in done

    async def _update_device_cache(self) -> set[str]:
        from app.routes.ws import vibegraph
        devices = self._get_devices()

        if ADD_FAKE_DEVICE:
            devices.add("Fake Device")

        if devices != self._device_cache:
            self._device_cache = devices
            self.logger.info("Devices updated: %s", devices)
            await vibegraph.bcast_update_devices(devices)

        return devices

    async def _vibe(self, device_names: Collection[str], intensity: float):
        if not device_names:
            return

        for device in self.client.devices.values():
            if device.name not in device_names:
                continue

            for actuator in device.actuators:
                try:
                    await actuator.command(intensity)
                except (DisconnectedError, DeviceServerError):
                    pass


# ==============================================================================
# Buttplug Proxy Connector

import itertools
import json
import websockets

from app.connector import WebSocketConnector

IntifaceMessage = list[dict[str, Any]]

INTIFACE_URL = "ws://127.0.0.1:12346"
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 12345  # clients connect here instead

class ButtplugProxyClients:
    _clients: dict[int | None, "ClientInfo"]
    """Map client ID to client info."""

    _messages: dict[int, "MessageInfo"]
    """Map message ID to client message info."""

    _internal_messages: dict[int, "MessageInfo"]
    """Map message ID to message info for internal messages."""

    __message_id: itertools.count

    def __init__(self):
        self._clients = {}
        self._messages = {}
        self._internal_messages = {}

        self.__message_id = itertools.count(1)

    @staticmethod
    def get_id(client: websockets.ServerConnection) -> int:
        return id(client)

    def next_message_id(self) -> int:
        return next(self.__message_id)

    def iter_clients(self) -> Iterator["ClientInfo"]:
        return iter(self._clients.values())

    def register_client(self, client: websockets.ServerConnection) -> int:
        client_id = self.get_id(client)

        self._clients[client_id] = self.ClientInfo(
            client=client,
            internal_msg_ids=set(),
        )

        return client_id

    def cleanup_client(self, client: websockets.ServerConnection) -> None:
        client_id = self.get_id(client)

        client_info = self._clients.pop(client_id, None)
        if client_info is None:
            return

        for internal_id in client_info.internal_msg_ids:
            self._messages.pop(internal_id, None)

    def register_message(
        self,
        client: websockets.ServerConnection,
        client_msg_id: int,
    ) -> int:
        client_id = self.get_id(client)
        client_info = self._clients[client_id]

        internal_id = self.next_message_id()

        client_info.internal_msg_ids.add(internal_id)

        self._messages[internal_id] = self.MessageInfo(
            client_id=client_id,
            client_msg_id=client_msg_id,
        )

        return internal_id

    def pop_message(
        self,
        internal_msg_id: int,
    ) -> Union[
        tuple["ClientInfo", "MessageInfo"],
        tuple[None, None],
    ]:
        msg_info = self._messages.pop(internal_msg_id, None)
        if msg_info is None:
            return None, None

        assert msg_info.client_id is not None

        client_info = self._clients.get(msg_info.client_id, None)
        if client_info is None:
            return None, None

        client_info.internal_msg_ids.discard(internal_msg_id)

        return client_info, msg_info

    def register_internal_message(self) -> int:
        internal_id = self.next_message_id()

        self._internal_messages[internal_id] = self.MessageInfo(
            client_id=None,
            client_msg_id=internal_id,
        )

        return internal_id

    def pop_internal_message(self, internal_id: int) -> "MessageInfo | None":
        return self._internal_messages.pop(internal_id, None)

    class ClientInfo(NamedTuple):
        client: websockets.ServerConnection  # client itself
        internal_msg_ids: set[int]  # pending messages

    class MessageInfo(NamedTuple):
        client_id: int | None  # id(client) for forwarded messages or None for own messages
        client_msg_id: int  # client message ID

class ButtplugProxyConnector(WebSocketConnector):
    NAME: ClassVar[str] = "ButtplugProxy"

    clients: ButtplugProxyClients

    def __init__(self, manager: ConnectorManager):
        super().__init__(manager)
        self.clients = ButtplugProxyClients()

    def _get_url(self) -> str:
        return INTIFACE_URL

    async def _request_server_info(self) -> None:
        data = [{
            "RequestServerInfo": {
                "ClientName": self.logger.name,
                "MessageVersion": 3,
                "Id": self.clients.register_internal_message(),
            },
        }]

        self.logger.debug("[P -> S]: %s", data)
        await self.sendnow(data)

    def next_message_id(self) -> int:
        return self.clients.next_message_id()

    async def on_connected(self) -> None:
        await super().on_connected()
        await self._request_server_info()

    async def main_loop(self) -> None:
        await async_select(
            asyncio.create_task(super().main_loop()),
            asyncio.create_task(self._server_loop()),
        )

    async def _server_loop(self) -> None:
        async with websockets.serve(self.handle_client, PROXY_HOST, PROXY_PORT):
            self.logger.info((
                "Buttplug proxy listening on %s:%d"
            ), PROXY_HOST, PROXY_PORT)

            await self._shutdown.wait()

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        self.logger.info((
            "Connector message received: %r, data: %s"
        ), msg, msg.data)

        return False

    async def handle_client(self, ws_client: websockets.ServerConnection) -> None:
        self.logger.info("Client connected")

        self.clients.register_client(ws_client)

        try:
            async for msg in ws_client:
                try:
                    data = self._parse_message(msg)
                    await self.on_client_message(ws_client, data)

                except Exception:
                    self.logger.exception((
                        "Exception processing client message: %s"
                    ), msg)

        except websockets.ConnectionClosedError:
            pass

        except Exception:
            self.logger.exception("Exception processing client")

        finally:
            self.clients.cleanup_client(ws_client)
            self.logger.info("Client disconnected")

    async def on_message(self, data: Any) -> None:
        await self.on_server_message(data)

    async def on_client_message(
        self,
        client: websockets.ServerConnection,
        data: Any,
    ) -> None:
        if not isinstance(data, list):
            self.logger.warning((
                "Received non-list client message: %r"
            ), data)
            return

        self.logger.debug(f"[C -> P] {data}")

        forward_request: IntifaceMessage = []
        immediate_reply: IntifaceMessage = []

        for item in data:
            if not isinstance(item, dict):
                self.logger.warning((
                    "Received non-dict client message item: %r"
                ), item)
                continue

            reqtype: str
            req: dict[str, Any]
            for reqtype, req in item.items():
                if not isinstance(req, dict):
                    self.logger.warning((
                        "Received non-dict client request: type=%r, item=%r"
                    ), reqtype, req)
                    continue

                client_req_id = req.get("Id")
                if not isinstance(client_req_id, int):
                    self.logger.warning((
                        "Received client request without ID: type=%r, item=%r"
                    ), reqtype, req)
                    continue

                if reqtype == "RequestServerInfo":
                    immediate_reply.append({
                        "ServerInfo": {
                            "Id": client_req_id,
                            "MessageVersion": req.get("MessageVersion", 3),
                            "MaxPingTime": 0,
                            "ServerName": self.logger.name,
                        },
                    })

                    self.logger.info("Received RequestServerInfo; ClientName: %s", req.get("ClientName"))

                else:
                    internal_req_id = self.clients.register_message(client, client_req_id)
                    req["Id"] = internal_req_id
                    forward_request.append({
                        reqtype: req,
                    })

        if forward_request:
            self.logger.debug("[P -> S]: %s", forward_request)
            await self.sendnow(forward_request)

        if immediate_reply:
            self.logger.debug("[P -> C]: %s", immediate_reply)
            msg = json.dumps(immediate_reply)
            await client.send(msg)

    async def on_server_message(self, data: Any) -> None:
        if not isinstance(data, list):
            self.logger.warning("Received non-list server message: %r", data)
            return

        self.logger.debug(f"[S -> P] {data}")

        replies: dict[websockets.ServerConnection, IntifaceMessage] = {}
        broadcast: IntifaceMessage = []

        for item in data:
            if not isinstance(item, dict):
                self.logger.warning((
                    "Received non-dict server message item: %r"
                ), item)
                continue

            resptype: str
            resp: dict[str, Any]
            for resptype, resp in item.items():
                if not isinstance(resp, dict):
                    self.logger.warning((
                        "Received non-dict server message response: type=%r, item=%r"
                    ), resptype, resp)
                    continue

                internal_req_id = resp.get("Id")
                if not isinstance(internal_req_id, int):
                    self.logger.warning((
                        "Received server response without or invalid ID: "
                        "id=%r, type=%r, item=%r"
                    ), internal_req_id, resptype, resp)
                    continue

                if internal_req_id == 0:
                    # Broadcast

                    broadcast.append({
                        resptype: resp,
                    })

                    continue

                client_info, msg_info = self.clients.pop_message(internal_req_id)
                if client_info is not None and msg_info is not None:
                    # Response for client

                    assert msg_info.client_id is not None

                    resp["Id"] = msg_info.client_msg_id
                    replies.setdefault(client_info.client, []).append({
                        resptype: resp,
                    })

                    continue

                msg_info = self.clients.pop_internal_message(internal_req_id)
                if msg_info is not None:
                    # Response for proxy

                    if resptype == "ServerInfo":
                        self.logger.debug("Received server info: %s", resp)

                    else:
                        self.logger.warning((
                            "Received unexpected server response: "
                            "id=%r, type=%r, item=%r"
                        ), internal_req_id, resptype, resp)

                    continue

                self.logger.warning((
                    "Received unexpected server response: "
                    "id=%r, type=%r, item=%r"
                ), internal_req_id, resptype, resp)

        for client, reply in replies.items():
            self.logger.debug("[P -> C]: %s", reply)

            for client, reply in replies.items():
                try:
                    msg = json.dumps(reply)
                    await client.send(msg)
                except websockets.ConnectionClosedError:
                    self.logger.debug("Client closed, skipping reply")
                except Exception as e:
                    self.logger.exception("Failed to send message to client: %s", e)

        if broadcast:
            self.logger.debug("[P -> C]: %s", broadcast)

            try:
                msg = json.dumps(broadcast)
            except Exception as e:
                self.logger.exception("Failed to send message to client: %s", e)
            else:
                for client_info in self.clients.iter_clients():
                    try:
                        await client_info.client.send(msg)
                    except websockets.ConnectionClosedError:
                        self.logger.debug("Client closed, skipping broadcast")
                    except Exception as e:
                        self.logger.exception("Failed to broadcast to client: %s", e)


# ==============================================================================
# Buttplug Receiver Connector

import re

from app.connector import WebSocketConnector

class ButtplugReceiverConnector(WebSocketConnector):
    NAME: ClassVar[str] = "ButtplugReceiver"

    FORWARD_TO_BUTTBLUG: bool = True
    FORWARD_TO_PISHOCK: bool = False

    MOD_INTENSITY: float = 0.5
    MIN_INTENSITY: int = 1
    MAX_INTENSITY: int = int(os.getenv("PISHOCK_MAX_INTENSITY", 10))
    MAX_DURATION: float = float(os.getenv("PISHOCK_MAX_DURATION", 2.0))
    MAX_DELAY: float = float(os.getenv("PISHOCK_MAX_DELAY", 60.0))

    device_websocket: ClassVar[str] = "ws://127.0.0.1:54817"
    device_code: ClassVar[str] = "FEBOTLIZ"
    device_address: ClassVar[str] = device_code
    device_identifier: ClassVar[str] = f"LVS-{device_code}"
    """
    Intiface device identifier.
    Make sure to add a WebSocket device with this name and
    protocol type "lovense" in Intiface.
    """

    _intensity: int = 0

    @property
    def handshake_package(self) -> dict[str, Any]:
        return {
            "identifier": self.device_identifier,
            "address": self.device_address,
            "version": 0,
        }

    @property
    def intensity(self) -> int:
        return self._intensity

    def _get_url(self) -> str:
        return self.device_websocket

    async def _send_handshake(self) -> None:
        await self.sendnow(self.handshake_package)
        self.logger.info("Handshake Sent")

    async def set_intensity(self, value: int) -> None:
        value = min(max(value, 0), 100)

        if value == self._intensity:
            return

        self._intensity = value

        await self.on_intensity_changed(value)

    async def on_connected(self) -> None:
        await super().on_connected()
        await self._send_handshake()

    def _parse_message(self, message) -> Any:
        return message

    async def on_message(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            self.logger.warning("Received non-bytes message: %r", data)
            return

        self.logger.info("Received: %s", data)

        if b"DeviceType;" in data:
            self.logger.info("Got device type")

            # Lovense initialization request
            await self.sendnow(f"{self.device_address}:0:{self.device_address};")

        elif b"Battery;" in data:
            self.logger.info("Got battery")

            # Buttplug will wait for a response to Battery so just make something up.
            await self.sendnow("90;")

        else:
            self.logger.info(f"Lovense command: {data}")

            # If it's a vibrate message, get the vibrate level, which will be 0-20.
            m = re.search(rb"Vibrate:([0-9]+)", data)
            if m:
                await self.set_intensity(round(int(m.group(1)) / 20 * 100))

            # If we wanted to conform with the Lovense protocol we'd
            # send "OK;" here, but Buttplug doesn't care.

    async def on_intensity_changed(self, intensity: int) -> None:
        if intensity <= 0:
            return

        from app.connectors.pishock import PiShockConnector, ShockFrame, ShockMode

        tasks = []

        if self.FORWARD_TO_BUTTBLUG:
            buttplug = self.manager.get(ButtplugConnector)
            if buttplug:
                duration = 10
                frame = VibeFrame.new_override(duration, intensity / 100)
                tasks.append(buttplug.enqueue(frame))

        if self.FORWARD_TO_PISHOCK:
            pishock = self.manager.get(PiShockConnector)
            if pishock:
                shock_intensity = intensity * self.MOD_INTENSITY
                shock_intensity = int(min(max(shock_intensity, self.MIN_INTENSITY), self.MAX_INTENSITY))

                frame = ShockFrame(ShockMode.Shock, 0.3, shock_intensity)

                self.logger.info("Converting vibe (intensity=%d) to shock: %s", intensity, frame)
                tasks.append(pishock.send_shock(frame))

        if tasks:
            await asyncio.gather(*tasks)
