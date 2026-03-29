from typing import NamedTuple, ClassVar, Any, Coroutine, Collection, Iterator, Iterable
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
            if cur_intensities is not None:
                flush_cur_action()

            try:
                cur_intensities = [int(arg[:-1]) / 100]
                continue
            except ValueError:
                pass

            m = re.fullmatch(r'(\d+)%?-(\d+)%', arg)
            if m:
                low = int(m.group(1)) / 100
                high = int(m.group(2)) / 100
                cur_intensities = [random.uniform(low, high)]
                continue

            m = re.fullmatch(r'(?:\d+%?)?(?:\.{2,}\d+%?)+', arg)
            if m:
                cur_intensities = []

                parts = arg.split("..")
                for i, part in enumerate(parts):
                    if part == "":
                        # Leading ".."
                        if i == 0:
                            if not prev_intensities:
                                raise ValueError("Cannot start with '..' without previous intensities")

                            cur_intensities.append(prev_intensities[-1])
                            continue

                        raise ValueError(f"Invalid empty percent segment in: {arg}")

                    if part.endswith('%'):
                        part = part[:-1]

                    try:
                        value = int(part) / 100
                    except ValueError:
                        raise ValueError(f"Invalid percent value: {part}")

                    cur_intensities.append(value)

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
                    raise ValueError(f"Invalid repeat format: {arg}")

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
            raise ValueError(f"Invalid argument: {arg}")

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

    _devices: set[str]

    _vibe_queue: asyncio.Queue[VibeGroup]
    _cur_vibe_group: VibeGroup | None = None
    _delayed_until: datetime

    def __init__(self, manager: ConnectorManager):
        super().__init__(manager)
        self.client = self._create_client()
        self._devices = set()
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

    @property
    def has_devices(self) -> bool:
        return bool(self.client.devices)

    async def enqueue(self, vibe: VibeGroup | VibeFrame) -> None:
        group = vibe if isinstance(vibe, VibeGroup) else VibeGroup((vibe,))
        await self._vibe_queue.put(group)

    async def clear(self):
        try:
            while True:
                self._vibe_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        self._cur_vibe_group = None

        await self._vibe([x.name for x in self.client.devices.values()], 0)

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

    def _get_devices(self) -> set[str]:
        return set(x.name for x in self.client.devices.values())

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

            await self._update_devices()
            await vibegraph.bcast_update_devices(self._devices)
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

    async def _update_devices(self) -> set[str]:
        from app.routes.ws import vibegraph
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
