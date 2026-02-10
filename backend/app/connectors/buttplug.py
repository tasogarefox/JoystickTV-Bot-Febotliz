from typing import NamedTuple, Optional, Any, Coroutine, Collection, Iterator, Iterable
from enum import IntEnum
from dataclasses import dataclass
from contextlib import asynccontextmanager
import os
import asyncio
import re
import random
from datetime import datetime, timedelta

from buttplug import (
    Client, WebsocketConnector, ProtocolSpec,
    ServerNotFoundError, DisconnectedError, ConnectorError,
)

from app.utils.asyncio import async_select
from app.connector import ConnectorMessage, ConnectorManager, BaseConnector
from app.routes.ws import vibegraph


# ==============================================================================
# Config

CHAT_VIBE_INFO = False
VIBE_CHECK_INTERVAL = 0.1

WS_HOST = os.getenv("BUTTPLUG_WS_HOST")
assert WS_HOST, "Missing environment variable: BUTTPLUG_WS_HOST"

NAME = "Buttplug"
URL = WS_HOST


# ==============================================================================
# Functions

def parse_vibes(vibestr: str) -> tuple["VibeFrame", ...]:
    sections: list[tuple[VibeFrame, ...]] = []
    cur_section: list[VibeFrame] = []

    # Default/starting values (uses class defaults if not specified)
    prev_action = VibeFrame.new_override()
    prev_section = (prev_action,)

    # Values for current action
    cur_start_value: float | None = None
    cur_stop_value: float | None = None  # NOTE: Defaults to cur_start_amount
    cur_duration: float | None = None
    cur_devices: list[str] | None = None

    def flush_cur_action() -> bool:
        """Flush the current action into the list."""
        nonlocal prev_action, cur_start_value, cur_stop_value, cur_duration, cur_devices

        # If the current action is empty, do nothing
        if cur_start_value is None and cur_duration is None:
            return False

        # Merge the current action values with the previous
        cur_start_value = abs(cur_start_value) if cur_start_value is not None else prev_action.value
        cur_stop_value = abs(cur_stop_value) if cur_stop_value is not None else cur_start_value
        cur_duration = abs(cur_duration) if cur_duration is not None else prev_action.duration
        cur_devices = cur_devices if cur_devices is not None else list(prev_action.get_devices())

        # Determine the number of actions to add
        count = max(1, int(min(
            abs(cur_stop_value - cur_start_value) / 0.05 + 1,
            cur_duration / 0.2,
        )))
        step_value = (cur_stop_value - cur_start_value) / (count - 1) if count > 1 else 0
        step_time = cur_duration / count

        # If the step value is 0, use the average of the start and stop value
        if step_value == 0:
            cur_start_value = (cur_start_value + cur_stop_value) / 2

        # Add actions
        for i in range(count):
            value = cur_start_value + step_value * i
            if not cur_devices:
                prev_action = VibeFrame.new_override(
                    step_time,
                    value,
                )
            else:
                prev_action = VibeFrame.new_exclusive(
                    step_time,
                    (VibeTarget(d, value) for d in cur_devices),
                )
            cur_section.append(prev_action)

        # Reset the current action
        cur_start_value = None
        cur_stop_value = None
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

        # Save as previous section
        prev_section = tuple(cur_section)

        # Add section
        sections.append(prev_section)

        # Reset current section
        cur_section.clear()

        return True

    # Parse the arguments
    # NOTE: Raise ValueError if the arguments are invalid
    for arg in vibestr.split(" "):
        arg = arg.strip()
        if not arg:
            continue

        if not arg[0].isdigit():  # This is a device name
            # DISABLED: The following line disables the use of device names.
            raise ValueError(f"Invalid argument: {arg}")

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

        elif arg.endswith("%"):  # This is an amount in percent
            if cur_start_value is not None:
                flush_cur_action()

            try:
                cur_start_value = int(arg[:-1]) / 100
                continue
            except ValueError:
                pass

            m = re.fullmatch(r'(\d+)%?-(\d+)%', arg)
            if m:
                low = int(m.group(1)) / 100
                high = int(m.group(2) or low) / 100
                cur_start_value = random.uniform(low, high)
                continue

            m = re.fullmatch(r'(\d+)%?\.{2,}(\d+)%', arg)
            if m:
                cur_start_value = int(m.group(1)) / 100
                cur_stop_value = int(m.group(2) or cur_start_value) / 100
                continue

            raise ValueError(f"Invalid percent format: {arg}")

        elif arg.endswith("s"):  # This is a time
            if cur_duration is not None:
                flush_cur_action()

            try:
                cur_duration = float(arg[:-1])
                continue
            except ValueError:
                pass

            m = re.fullmatch(r'((?:\d+?\.)?\d+)s?-((?:\d+?\.)?\d+)s', arg)
            if m:
                low = float(m.group(1))
                high = float(m.group(2) or low)
                cur_duration = random.uniform(low, high)
                continue

            raise ValueError(f"Invalid time format: {arg}")

        elif arg.endswith("r") or arg.endswith("x"):  # Repeat the last section
            # Note: If current section is empty, the previous section will be used instead
            flush_cur_section()
            if not sections or not prev_section:
                continue

            repeat = 1
            if len(arg) > 1:
                try:
                    repeat = int(arg[:-1]) - 1
                except ValueError:
                    raise ValueError(f"Invalid repeat format: {arg}")

            for _ in range(min(100, repeat)):
                sections.append(prev_section)

        elif arg.endswith("d") or arg.endswith("t"):  # Repeat for the given duration
            # Note: If current section is empty, the previous section will be used instead
            flush_cur_section()
            if not sections:
                continue

            duration = 1
            if len(arg) > 1:
                try:
                    duration = int(arg[:-1]) - 1
                except ValueError:
                    raise ValueError(f"Invalid duration format: {arg}")
                duration = max(1, duration)

            old_section = sections.pop()
            old_duration = sum(action.duration for action in old_section)
            if old_duration <= 0 or duration / old_duration < 0.01:
                ValueError(
                    f"Section duration ({old_duration}s) is too short for "
                    "requested repeat duration ({duration}s)"
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
                            value=frame.value,
                            targets=frame.targets,
                            mode=frame.mode,
                        )

                    # Append frame
                    new_section.append(frame)

            # Insert adjusted section
            if new_section:
                sections.append(tuple(new_section))

        else:  # Invalid argument
            raise ValueError(f"Invalid argument: {arg}")

    else:
        # Flush the last frame and section, if any
        flush_cur_section()

    if not sections:
        raise ValueError("No actions specified")

    # If there are no sections, there is nothing to do
    if not sections:
        return tuple()

    # Flatten and return
    return tuple(v for s in sections for v in s)


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

    def __getitem__(self, index: int) -> VibeFrame:
        return self.frames[index]

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
    _cur_vibe_group: VibeGroup | None = None
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
            await self._clear()
            return True

        elif msg.action == "disable":
            if isinstance(msg.data, (int, float)):
                now = datetime.now()
                until = now + timedelta(seconds=msg.data)
                self._disabled_until = max(self._disabled_until, until)

                group = self._cur_vibe_group
                if group:
                    delay = (until - now).total_seconds()
                    log_msg = f"Vibe: disabled for {delay:.2f} seconds"
                    self.logger.info(log_msg)
                    await self.talkto("JoystickTV", "chat", {
                        "text": log_msg,
                        "channelId": group.channel_id,
                    })

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
        await async_select(
            asyncio.create_task(self._scan_loop()),
            asyncio.create_task(self._vibe_loop()),
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

            await self._update_devices()
            await vibegraph.bcast_update_devices(self._devices)
            await vibegraph.bcast_set_group(group)

            for i, vibe in enumerate(x for x in group.frames if x):
                shutdown = await self._handle_vibe_frame(devices, group, None)
                if shutdown:
                    break

                if group is not self._cur_vibe_group:
                    break

                all_devices = set(x.name for x in self.client.devices.values())
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
                            + (f" at {round(vibe.value*100)}%" if len(group) == 1 else "")
                            + f" by {group.username}"
                            + f"; queued: {self._vibe_queue.qsize()}"
                        ),
                        "channelId": group.channel_id,
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
                    "channelId": group.channel_id,
                }))

            await asyncio.gather(*tasks)

    async def _handle_vibe_frame(
        self,
        devices: Collection[str],
        group: VibeGroup,
        vibe: VibeFrame | None,
    ) -> bool:
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

            elif self._disabled_until > now:
                total_delay = (self._disabled_until - now).total_seconds()
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
                        tasks.append(self._vibe(devices, vibe.value * mult))

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
                await self._clear()
                break

        return shutdown

    async def _wait_for_shutdown(self, timeout: float) -> bool:
        tshutdown = asyncio.create_task(self._shutdown.wait())
        tsleep = asyncio.create_task(asyncio.sleep(timeout))

        done = await async_select(tshutdown, tsleep)
        return tshutdown in done

    async def _update_devices(self) -> set[str]:
        devices = set(x.name for x in self.client.devices.values())
        if devices != self._devices:
            self._devices = devices
            self.logger.info("Devices updated: %s", devices)
            await vibegraph.bcast_update_devices(devices)
        return devices

    async def _vibe(self, device_names: Collection[str], amount: float):
        if not device_names:
            return

        for device in self.client.devices.values():
            if device.name not in device_names:
                continue

            for actuator in device.actuators:
                try:
                    await actuator.command(amount)
                except DisconnectedError:
                    pass

    async def _clear(self):
        try:
            while True:
                self._vibe_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        self._cur_vibe_group = None

        await self._vibe([x.name for x in self.client.devices.values()], 0)
