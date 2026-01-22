from typing import Any, Callable, Coroutine, Iterable
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.connectors.buttplug import VibeGroup, VibeFrame, VibeTarget

router = APIRouter(prefix="/vibegraph", tags=["vibegraph"])

clients: set[WebSocket] = set()

DEVICE_NAMES = {
    "default",
    "lovense ambi",
    "lovense calor",
    "lovense diamo",
    "lovense dolce",
    "lovense domi 2",
    "lovense edge 2",
    "lovense exomoon",
    "lovense ferri",
    "lovense flexer",
    "lovense gemini",
    "lovense gravity",
    "lovense gush",
    "lovense gush 2",
    "lovense hush 2",
    "lovense hyphy",
    "lovense lapis",
    "lovense lush 3",
    "lovense lush 4",
    "lovense lush 4 mini",
    "lovense max 2",
    "lovense mission 2",
    "lovense nora",
    "lovense osci 3",
    "lovense ridge",
    "lovense solace",
    "lovense solace pro",
    "lovense spinel",
    "lovense tenera",
    "lovense tenera 2",
    "lovense vulse",
}

# WARNING: Frontend expects all times to be in milliseconds


# ==============================================================================
# Helper functions

def encode_frame(frame: VibeFrame) -> dict[str, Any]:
    return {
        "duration": frame.duration * 1000,
        "value": frame.value,
        "mode": frame.mode.name,
        "targets": [{
            "device": target.device,
            "value": target.value,
        } for target in frame.targets],
    }


# ==============================================================================
# Interface

async def broadcast(callback: Callable[..., Coroutine[Any, Any, None]], *args, **kwargs) -> None:
    dead = set()

    for ws in clients:
        try:
            await callback(ws, *args, **kwargs)
        except WebSocketDisconnect:
            dead.add(ws)

    for ws in dead:
        clients.remove(ws)

async def ping(ws: WebSocket) -> None:
    await ws.send_json({
        "type": "ping",
    })

async def update_devices(ws: WebSocket, devices: Iterable[str]) -> None:
    await ws.send_json({
        "type": "update-devices",
        "devices": [{
            "name": name,
        } for name in devices],
    })

async def bcast_update_devices(devices: Iterable[str]) -> None:
    await broadcast(update_devices, devices)

async def reset_group(ws: WebSocket) -> None:
    await ws.send_json({
        "type": "reset-group",
    })

async def bcast_reset_group() -> None:
    await broadcast(reset_group)

async def set_group(ws: WebSocket, group: VibeGroup) -> None:
    await ws.send_json({
        "type": "set-group",
        "group": {
            # "channel_id": group.channel_id,
            "username": group.username,
            "frames": [encode_frame(frame) for frame in group.frames],
        },
    })

async def bcast_set_group(group: VibeGroup) -> None:
    await broadcast(set_group, group)

async def add_frame(ws: WebSocket, frame: VibeFrame) -> None:
    await ws.send_json({
        "type": "add-frame",
        "frame": encode_frame(frame),
    })

async def bcast_add_frame(frame: VibeFrame) -> None:
    await broadcast(add_frame, frame)

async def advance(ws: WebSocket, amount: float) -> None:
    await ws.send_json({
        "type": "advance",
        "amount": amount * 1000,
    })

async def bcast_advance(amount: float) -> None:
    await broadcast(advance, amount)


# ==============================================================================
# Endpoints

@router.websocket("/")
async def ws_vibegraph(ws: WebSocket) -> None:
    await ws.accept()

    clients.add(ws)
    try:
        while True:
            await asyncio.sleep(60)
            await ping(ws)

    except WebSocketDisconnect:
        pass

    finally:
        clients.discard(ws)
        try:
            await ws.close()
        except RuntimeError:
            pass

# @router.websocket("/")
async def ws_vibegraph_test_groups(ws: WebSocket) -> None:
    import random

    DEVICE_COUNT = 2
    MAX_DURATION = 2.0
    MAX_DELTA = 0.5

    await ws.accept()

    # clients.add(ws)
    try:
        devices = random.sample(tuple(DEVICE_NAMES), DEVICE_COUNT)
        await update_devices(ws, devices)

        # while True:
        #     await asyncio.sleep(60)

        groups: list[VibeGroup] = []
        i = 0
        while True:
            i += 1
            frames: list[VibeFrame] = []

            for _ in range(random.randint(0, 3)):
                if len(groups) > 10:
                    break

                for _ in range(random.randint(1, 10)):
                    overrides = []

                    for j in range(DEVICE_COUNT):
                        # smooth random walk
                        try:
                            value = frames[-1].targets[j + 1].value
                        except IndexError:
                            value = 0
                        value += random.uniform(-MAX_DELTA, MAX_DELTA)
                        value = max(0, min(1, value))  # clamp 0–1

                        overrides.append(VibeTarget(devices[j], value))

                    frames.append(VibeFrame.new_exclusive(
                        random.uniform(0, MAX_DURATION),
                        overrides,
                    ))

                group = VibeGroup(tuple(frames), username=f"test-groups-{i}")
                groups.append(group)

            try:
                group = groups.pop(0)
            except IndexError:
                await asyncio.sleep(1)
                continue

            await set_group(ws, group)
            for frame in group:
                await advance(ws, frame.duration)
                await asyncio.sleep(frame.duration)

    except WebSocketDisconnect:
        pass

# @router.websocket("/")
async def ws_vibegraph_test_frames(ws: WebSocket) -> None:
    import random

    DEVICE_COUNT = 2
    MAX_DURATION = 2.0
    MAX_DELTA = 0.5

    await ws.accept()

    # clients.add(ws)
    try:
        devices = random.sample(tuple(DEVICE_NAMES), DEVICE_COUNT)
        await update_devices(ws, devices)

        group = VibeGroup(tuple(), username="test-frames")
        await set_group(ws, group)

        frames: list[VibeFrame] = []
        while True:
            if len(frames) > 10:
                break

            for _ in range(1):
                overrides = []

                for j in range(DEVICE_COUNT):
                    # smooth random walk
                    try:
                        value = frames[-1].targets[j + 1].value
                    except IndexError:
                        value = 0
                    value += random.uniform(-MAX_DELTA, MAX_DELTA)
                    value = max(0, min(1, value))  # clamp 0–1

                    overrides.append(VibeTarget(devices[j], value))

                frames.append(VibeFrame.new_exclusive(
                    random.uniform(0, MAX_DURATION),
                    overrides,
                ))

            try:
                frame = frames.pop(0)
            except IndexError:
                await asyncio.sleep(1)
                continue

            await advance(ws, frame.duration)
            await asyncio.sleep(frame.duration)

    except WebSocketDisconnect:
        pass
