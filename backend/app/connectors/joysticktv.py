from typing import Optional, Any, Awaitable, Callable, Iterable
import asyncio
import json
import re
import random
import websockets
import html
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import getenv_list
from app.utils.datetime import utcmin, utcnow
from app.connector import ConnectorMessage, ConnectorManager, WebSocketConnector
from app.connectors.warudo import QUIRKY_ANIMALS_MAP
from app.connectors.buttplug import VibeGroup, VibeFrame, parse_vibes

from app.db.database import get_async_db
from app.db.models import Channel, Viewer

from app.jstv import jstv_db, jstv_web, jstv_auth
from app.jstv.jstv_web import WS_HOST, ACCESS_TOKEN
from app.jstv.jstv_error import JSTVAuthError, JSTVWebError

QUIRKY_ANIMALS_LIST = tuple(QUIRKY_ANIMALS_MAP.items())


# ==============================================================================
# Config

GATEWAY_IDENTIFIER = '{"channel":"GatewayChannel"}'

NAME = "JoystickTV"
URL = f"{WS_HOST}?token={ACCESS_TOKEN}"

SUBPROTOCOL_ACTIONABLE = websockets.Subprotocol("actioncable-v1-json")

REWARD_INTERVAL = 300  # point reward interval in seconds
REWARD_POINTS_PER_MINUTE = 2.0  # points per minute
REWARD_SUBSCRIBER_MULT = 2.0  # points multiplier for subscribers
VIP_USERS = getenv_list("JOYSTICKTV_VIP_USERS")

MAX_RECOVERY_TIME = REWARD_INTERVAL  # max channel/viewer online status recovery time in seconds


# ==============================================================================
# Helper functions

async def reward_viewer(channel: Channel, viewer: Viewer) -> bool:
    """
    Reward a viewer with points and watch time.

    - Only full REWARD_INTERVAL seconds earn points.
    - Fractional seconds are preserved in rewarded_at for precise future calculations.
    - Rewards only time that overlaps with the channel being live.

    WARNING: Make sure that viewer and channel presence/online status are up-to-date before calling.

    Args:
        channel: The Channel instance.
        viewer: The Viewer instance to reward.

    Returns:
        True if updated, False otherwise.
    """
    # Determine reward window
    now = utcnow()
    time_start = max(
        channel.live_at,
        viewer.joined_at,
        viewer.rewarded_at,
    )
    time_end = min(
        now if viewer.is_present else viewer.left_at,
        now if channel.is_live else channel.offline_at,
    )

    # Return if no reward is due
    if time_end <= time_start:
        return False

    # Round down to the nearest REWARD_INTERVAL
    intervals = int((time_end - time_start).total_seconds() // REWARD_INTERVAL)
    time_delta = intervals * REWARD_INTERVAL
    time_end = time_start + timedelta(seconds=time_delta)

    # Return if no reward is due
    if time_delta <= 0:
        return False

    # Calculate points (only complete intervals)
    # NOTE: `time_delta` is already a multiple of REWARD_INTERVAL
    points = time_delta / 60 * REWARD_POINTS_PER_MINUTE

    # # TODO: Reenable when we track subscriber status
    # if viewer.subscribed_at:
    #     points *= REWARD_SUBSCRIBER_MULT

    # Update viewer
    viewer.rewarded_at = time_end
    viewer.watch_time += int(time_delta)
    viewer.points += points

    return True


# ==============================================================================
# JoystickTV Connector

class LiveChannel:
    pass

class JoystickTVConnector(WebSocketConnector):
    live_channels: dict[str, LiveChannel]

    def __init__(self, manager: ConnectorManager, name: Optional[str] = None, url: Optional[str] = None):
        super().__init__(manager, name or NAME, url or URL)
        self.live_channels = {}

    async def __call_with_message_metadata(
        self,
        _callback: Callable[[dict[Any, Any], dict[Any, Any]], Awaitable],
        _message: dict[Any, Any],
    ) -> bool:
        metadata_str = _message.get("metadata") or ""

        try:
            metadata = json.loads(metadata_str)
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON: %s", metadata_str)
            return False

        if not isinstance(metadata, dict):
            self.logger.error("JSON not a dict: %s", metadata_str)
            return False

        await _callback(_message, metadata)
        return True

    def _create_connection(self) -> websockets.connect:
        return websockets.connect(self.url, subprotocols=[SUBPROTOCOL_ACTIONABLE])

    async def talk_receive(self, msg: ConnectorMessage) -> bool:
        if await super().talk_receive(msg):
            return True

        if msg.action == "chat":
            for i, line in enumerate(msg.data["text"].split("\n")):
                line = line.rstrip()
                if not line:
                    continue

                if i == 0:
                    at = msg.data.get("at")
                    if at is not None:
                        line = f"@{at} {line}"

                await self.sendnow({
                    "command": "message",
                    "identifier": GATEWAY_IDENTIFIER,
                    "data": json.dumps({
                        "action": "send_message",
                        "text": html.escape(line),
                        "channelId": msg.data["channelId"],
                    }),
                })

            return True

        return False

    async def on_connected(self):
        """
        Handle (re)connection to the gateway.

        - Subscribes to the gateway.
        - Triggers recovery of channel and viewer state after downtime.
        - Rebuilds the in-memory live channel cache.
        """
        self.logger.info("Subscribing to gateway...")

        async with get_async_db() as db:
            await asyncio.gather(
                self.sendnow({"command": "subscribe", "identifier": GATEWAY_IDENTIFIER}),
                self._update_live_channels(db),
            )

        # WARNING: Must send messages AFTER _update_live_channels() is done to ensure consistent state
        await self.send_live_chats("おはよう世界 Good Morning World <3")

    async def _update_live_channels(self, db: AsyncSession):
        """
        Synchronize live channel state and recover viewer presence.

        - Rebuilds the live channel cache from current stream state.
        - Reconciles channel live/offline state with the database.
        - If downtime exceeds `MAX_RECOVERY_TIME`, marks all present viewers
          offline at a safe cutoff time and rewards them up to that point.
        """
        self.logger.info("Updating live channels...")

        self.live_channels.clear()

        now = utcnow()
        last_event_at = await jstv_db.get_last_event_received_time(db) or utcmin

        gap_seconds = (now - last_event_at).total_seconds()
        within_recovery_window = gap_seconds <= MAX_RECOVERY_TIME  # Are we within the recovery window?

        cutoff_at = min(now, last_event_at + timedelta(seconds=MAX_RECOVERY_TIME))

        # Load all channels and their access tokens
        result = await db.execute(select(Channel))

        # Fetch stream settings for all channels in parallel
        async def get_live_status_helper(channel: Channel) -> tuple[bool, Channel]:
            try:
                access_token = await jstv_auth.get_access_token(channel.channel_id)
                settings = await jstv_web.fetch_stream_settings(access_token)
            except (JSTVAuthError, JSTVWebError):
                return False, channel

            return settings.live, channel

        tasks = [
            get_live_status_helper(channel)
            for channel in result.scalars().all()
        ]

        # Process results as they come
        for task in asyncio.as_completed(tasks):
            is_live, channel = await task

            # Maintain live channel cache
            if is_live:
                self.live_channels[channel.channel_id] = LiveChannel()

            # Trusted reconnection: no forced recovery
            if within_recovery_window:
                if is_live:
                    channel.set_live(now)
                else:
                    channel.set_offline(now)
                continue

            # Untrusted state: force reconciliation
            if is_live != channel.is_live:
                if is_live:  # channel.is_live == False
                    channel.set_live(now)
                else:  # channel.is_live == True
                    channel.force_offline(max(channel.live_at, cutoff_at))

            result = await db.execute(
                select(Viewer).filter_by(channel_id=channel.id, is_present=True),
            )
            viewers = result.scalars().all()

            if viewers:
                self.logger.info(
                    "Fail-safe: Cannot reconcile channel %s viewer presence after %d minutes of disconnection - "
                    "marking %d viewers as offline",
                    channel.channel_id,
                    gap_seconds // 60,
                    len(viewers),
                )

                # Mark all present viewers as offline and reward them up until `cutoff_at`
                for viewer in viewers:
                    viewer.force_offline(max(viewer.joined_at, cutoff_at))
                    await reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

        await db.commit()

    async def on_disconnected(self):
        """
        Handle loss of connection or shutdown.

        - Rewards all currently-present viewers **only if their channel is live**.
        - Does NOT mark viewers offline or modify channel state.
        - Viewer cleanup and offline inference are deferred to recovery on reconnect.
        """
        self.logger.info("Connection closed")

        async with get_async_db() as db:
            # Select viewers who are currently present and in a live channel
            result = await db.execute(
                select(Viewer)
                .join(Viewer.channel)
                .options(joinedload(Viewer.channel))
                .filter(Viewer.is_present == True, Channel.is_live == True),
            )
            viewers = result.scalars().all()
            if viewers:
                self.logger.info(
                    "Fail-safe: Disconnected with %d viewers - rewarding viewers up until now",
                    len(viewers),
                )

                for viewer in viewers:
                    # NOTE: We rely on recovery to mark viewers as offline later, if needed
                    await reward_viewer(viewer.channel, viewer)  # WARNING: Channel and viewer must be up-to-date

            await db.commit()

    async def on_message(self, data: dict[Any, Any]):
        async with get_async_db() as db:
            await jstv_db.update_last_event_received_time(db)
            await db.commit()

        if 'type' in data:
            if data["type"] == "reject_subscription":
                self.logger.error("Subscription rejected")
                self._connected = False
                return

            elif data["type"] == "confirm_subscription":
                self.logger.info(f"Subscription confirmed")
                return

            elif data["type"] == "welcome":
                self.logger.info("Received welcome")
                return

            elif data["type"] == "ping":
                self.logger.debug("Received ping")
                return

        self.logger.info("Received: %s", data)

        if not self._connected:
            return

        if "message" in data:
            message = data["message"]

            if message["type"] == "Started":
                await self.on_stream_started(message)

            elif message["type"] == "Ended":
                await self.on_stream_ended(message)

            elif message["type"] == "StreamResuming":
                await self.on_stream_resuming(message)

            elif message["type"] == "new_message":
                await self.on_new_chat(message)

            elif message["type"] == "enter_stream":
                await self.on_enter_stream(message)

            elif message["type"] == "leave_stream":
                await self.on_leave_stream(message)

            elif message["type"] == "Followed":
                await self.__call_with_message_metadata(
                    self.on_followed, message)

            elif message["type"] == "Subscribed":
                await self.__call_with_message_metadata(
                    self.on_subscribed, message)

            elif message["type"] == "Tipped":
                await self.__call_with_message_metadata(
                    self.on_tipped, message)

            elif message["type"] == "TipGoalIncreased":
                await self.__call_with_message_metadata(
                    self.on_tip_goal_increased, message)

            elif message["type"] == "MilestoneCompleted":
                await self.__call_with_message_metadata(
                    self.on_milestone_completed, message)

            elif message["type"] == "TipGoalMet":
                await self.__call_with_message_metadata(
                    self.on_tip_goal_met, message)

            elif message["type"] == "StreamDroppedIn":
                await self.__call_with_message_metadata(
                    self.on_stream_dropped_in, message)

    async def on_stream_started(self, message: dict[Any, Any]):
        """
        Handle a channel transitioning to live.

        - Updates in-memory live channel cache.
        """
        channel_id = message.get("channelId")
        if not channel_id:
            return

        self.logger.info("Stream started: %s", channel_id)

        # Ensure live channel cache exists
        live_channel = self.live_channels.get(channel_id)
        if live_channel is None:
            live_channel = self.live_channels[channel_id] = LiveChannel()

        async with get_async_db() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)

            # Mark channel live
            channel.set_live()

            await db.commit()

    async def on_stream_resuming(self, message: dict[Any, Any]):
        """
        Handle a channel resuming its stream after a short disconnect.

        - Updates in-memory live channel cache.
        """
        channel_id = message.get("channelId")
        if not channel_id:
            return

        self.logger.info("Stream resuming: %s", channel_id)

        # Ensure live channel cache exists
        live_channel = self.live_channels.get(channel_id)
        if live_channel is None:
            live_channel = self.live_channels[channel_id] = LiveChannel()

        async with get_async_db() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)

            # Mark channel live
            channel.set_live()

            await db.commit()

    async def on_stream_ended(self, message: dict[Any, Any]):
        """
        Handle a channel transitioning to offline.

        - Removes the channel from the live cache.
        - Marks the channel as offline in the database.
        - Rewards all currently-present viewers up to the end of the stream.

        Viewer presence cleanup is deferred to leave events or recovery logic.
        """
        channel_id = message.get("channelId")
        if not channel_id:
            return

        self.logger.info("Stream ended: %s", channel_id)

        # Remove channel from in-memory live cache
        self.live_channels.pop(channel_id, None)

        async with get_async_db() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)

            # Mark channel offline; timestamps are handled by the model
            channel.set_offline()

            # Reward all viewers still marked as present
            result = await db.execute(
                select(Viewer).filter_by(channel_id=channel_id, is_present=True),
            )
            viewers = result.scalars().all()

            if viewers:
                self.logger.info(
                    "Fail-safe: Stream %s ended with %d viewers - rewarding viewers up until now",
                    channel_id, len(viewers),
                )

                for viewer in viewers:
                    # NOTE: We do NOT mark viewers offline here.
                    #       Offline inference is handled by leave events or recovery.
                    await reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

            await db.commit()

    async def on_new_chat(self, message: dict[Any, Any]):
        text_lower = (message.get("text") or "").lower()
        bot_command_lower = (message.get("botCommand") or "").lower()
        channel_id = message.get("channelId")
        username = message.get("author", {}).get("username")

        if not channel_id or not username:
            return

        async with get_async_db() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)
            viewer = await jstv_db.get_or_create_viewer(db, channel, username)

            # Update last message time
            viewer.chatted_at = utcnow()

            # Fail-safe: set viewer to online
            if not viewer.is_present:
                self.logger.info(
                    "Fail-safe: Offline viewer %s chatted in channel %s - marking as online",
                    username, channel_id,
                )

                viewer.join()

            if bot_command_lower in ["points", "p"]:
                await reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date
                await self.send_chat_reply(message, f"has {int(viewer.points)} points", at=True)

            elif bot_command_lower == "test_tip":
                slug = message["author"]["slug"]
                if slug != message["streamer"]["slug"]:
                    await self.send_chat_reply(
                        message,
                        f"You do not have the necessary permissions to use the {bot_command_lower} command",
                        at=True,
                    )
                    return

                amount = 0

                arg = message.get("botCommandArg")
                if arg is not None:
                    try:
                        amount = int(arg)
                    except ValueError:
                        pass

                metadata = {
                    "who": "TEST",
                    "what": "Tipped",
                    "how_much": amount,
                    "tip_menu_item": None,
                }

                await asyncio.gather(
                    self.send_chat_reply(message, f"Sending test tip of {amount} tokens"),
                    self.on_tipped(message, metadata),
                )

            elif any(x == bot_command_lower for x in ["pet", "pets", "pat", "pats"]) or any(x in text_lower for x in [":felizpet:"]):
                await asyncio.gather(
                    self.send_chat_reply(message, f"Pet that fluff-ball <3"),
                    self.send_warudo("HeadPets"),
                )

            elif any(x == bot_command_lower for x in ["pet1", "pets1", "pat1", "pats1"]):
                await asyncio.gather(
                    self.send_chat_reply(message, f"Pet that fluff-ball <3"),
                    self.send_warudo("HeadPets1"),
                )

            elif any(x == bot_command_lower for x in ["pet2", "pets2", "pat2", "pats2"]):
                await asyncio.gather(
                    self.send_chat_reply(message, f"Pet that fluff-ball <3"),
                    self.send_warudo("HeadPets2"),
                )

            elif any(x == bot_command_lower for x in ["pet3", "pets3", "pat3", "pats3"]):
                await asyncio.gather(
                    self.send_chat_reply(message, f"Pet that fluff-ball <3"),
                    self.send_warudo("HeadPets3"),
                )

            elif any(x == bot_command_lower for x in ["boop", "boops"]):
                await self.send_warudo("Boop")

            elif any(x == bot_command_lower for x in ["lick", "licks", "noselick", "noselicks", "kiss", "kisses"]):
                await self.send_warudo("NoseLick")

            elif any(x == bot_command_lower for x in ["earlick", "earlicks"]):
                await self.send_warudo("EarLick")

            elif any(x == bot_command_lower for x in ["bellylick", "bellylicks"]):
                await self.send_warudo("BellyLick")

            elif bot_command_lower == "bonk":
                await self.send_warudo("Bonk")

            elif any(x == bot_command_lower for x in ["lewdpet", "lewdpets", "lewdpat", "lewdpats"]):
                vibes = (VibeFrame.new_override(10, random.uniform(0.1, 0.5)),)

                await asyncio.gather(
                    self.talkto("Buttplug", "vibe", VibeGroup(vibes, channel_id=channel_id, username=username)),
                    self.send_warudo("LewdPets"),
                )

            elif any(x == bot_command_lower for x in ["lewdboop", "lewdboops"]):
                vibes = (VibeFrame.new_override(10, random.uniform(0.1, 0.5)),)

                await asyncio.gather(
                    self.talkto("Buttplug", "vibe", VibeGroup(vibes, channel_id=channel_id, username=username)),
                    self.send_warudo("LewdBoop"),
                )

            elif any(x == bot_command_lower for x in ["niplick", "niplicks", "nipplelick", "nipplelicks"]):
                vibes = (VibeFrame.new_override(10, random.uniform(0.1, 0.5)),)

                await asyncio.gather(
                    self.talkto("Buttplug", "vibe", VibeGroup(vibes, channel_id=channel_id, username=username)),
                    self.send_warudo("NippleLick"),
                )

            elif any(x == bot_command_lower for x in ["beanlick", "beanlicks", "pawlick", "pawlicks"]):
                vibes = (VibeFrame.new_override(10, random.uniform(0.1, 0.5)),)

                await asyncio.gather(
                    self.talkto("Buttplug", "vibe", VibeGroup(vibes, channel_id=channel_id, username=username)),
                    self.send_warudo("BeanLick"),
                )

            elif any(x == bot_command_lower for x in ["lewdlick", "lewdlicks", "vulvalick", "vulvalicks", "cookielick", "cookielicks"]):
                vibes = (VibeFrame.new_override(10, random.uniform(0.1, 0.5)),)

                await asyncio.gather(
                    self.talkto("Buttplug", "vibe", VibeGroup(vibes, channel_id=channel_id, username=username)),
                    self.send_warudo("LewdLick"),
                )

            elif bot_command_lower == "spank":
                vibes = tuple(v for v in [
                    VibeFrame.new_override(0.5, random.uniform(0.5, 1.0)),
                    VibeFrame.new_override(0.5, 0)
                ] for _ in range(random.randint(3, 10)))

                await asyncio.gather(
                    self.talkto("Buttplug", "vibe", VibeGroup(vibes, channel_id=channel_id, username=username)),
                    self.send_warudo("Spank"),
                )

            elif bot_command_lower == "hearts":
                await self.send_warudo("Hearts")

            elif bot_command_lower == "love":
                await self.send_warudo("Love")

            elif bot_command_lower == "balls":
                await self.send_warudo("Balls")

            elif any(x == bot_command_lower for x in ["feed", "food"]):
                await self.send_warudo("Feed")

            elif any(x == bot_command_lower for x in ["hydrate", "water"]):
                await self.send_warudo("Hydrate")

            elif bot_command_lower == "pie":
                await self.send_warudo("Pie")

            elif any(x == bot_command_lower for x in ["cum", "coom", "nut"]):
                await self.send_warudo("Cum")

            elif any(x == bot_command_lower for x in ["plush", "plushify"]):
                animal, prop = random.choice(QUIRKY_ANIMALS_LIST)

                await asyncio.gather(
                    self.send_chat_reply(message, f"has been plushified into a {animal}", at=True),
                    self.send_warudo("Plushify", [username, prop]),
                )

            elif any(x == bot_command_lower for x in ["viewersign", "sign", "showsign"]):
                text = message.get("botCommandArg")
                if not text:
                    await self.send_chat_reply(message, f"Usage: !{bot_command_lower} <TEXT>", at=True)
                else:
                    await self.send_warudo("ViewerSign", text)

            elif bot_command_lower == "clip":
                await asyncio.gather(
                    self.talkto("OBS", "clip", None),
                    self.send_chat_reply(message, f"Creating a clip of the last 2 minutes"),
                )

            elif bot_command_lower in ["vibe_disable", "vibe_delay"]:
                slug = message["author"]["slug"]
                if slug != message["streamer"]["slug"]:
                    await self.send_chat_reply(
                        message,
                        f"You do not have the necessary permissions to use the {bot_command_lower} command",
                        at=True,
                    )
                    return

                try:
                    delay = float(message["botCommandArg"])
                except (KeyError, TypeError, ValueError):
                    await self.send_chat_reply(
                        message,
                        f"Usage: !{bot_command_lower} [SECONDS]",
                        at=True,
                    )
                    return

                await self.talkto("Buttplug", "disable", delay)
                return

            elif bot_command_lower in ["vibe_stop", "vibe_clear"]:
                slug = message["author"]["slug"]
                if slug != message["streamer"]["slug"]:
                    await self.send_chat_reply(
                        message,
                        f"You do not have the necessary permissions to use the {bot_command_lower} command",
                        at=True,
                    )
                    return

                await self.talkto("Buttplug", "stop", None)
                return

            elif bot_command_lower == "vibe":
                # slug = message["author"]["slug"]
                # if slug != message["streamer"]["slug"] and slug.lower() not in VIP_USERS:
                #     await self.send_chat_reply(
                #         message,
                #         f"You do not have the necessary permissions to use the {bot_command_lower} command",
                #         at=True,
                #     )
                #     return

                vibestr = message.get("botCommandArg") or ""
                try:
                    if not vibestr:
                        raise ValueError

                    vibes = parse_vibes(vibestr)

                except ValueError as e:
                    # Show the usage
                    errmsg = str(e) if isinstance(e, Exception) else ""
                    await self.send_chat_reply(message, errmsg + (
                        # f"\nUsage: !{bot_command_lower} [AMOUNT%] [TIMEs] [DEVICE] ..."
                        f"\nExamples: !{bot_command_lower} 20% 5s"
                        f"; !{bot_command_lower} 5s 10% 50% 100%"
                        f"; !{bot_command_lower} 0.5s 50% 0% 5r"
                        # f"; !{bot_command_lower} deviceA 5s 50%"
                        # f\n"Tokens may appear in any order. Percent and seconds pair automatically. Devices are optional."
                    ).strip(), at=True)

                else:
                    await self.talkto("Buttplug", "vibe", VibeGroup(
                        frames=vibes,
                        channel_id=channel_id,
                        username=username,
                    ))

                return

            elif "trobbio" in text_lower:
                await self.send_warudo("Trobbio")

            elif "blahaj" in text_lower:
                await self.send_warudo("Blahaj")

            elif any(x in text_lower for x in ["cookie", "vulva", "vagina", "pussy"]):
                await self.send_warudo("Cookie")

            elif any(x in text_lower for x in ["dildo", "penis", "dick"]):
                await self.send_warudo("Dildo")

            elif bot_command_lower:
                args = [bot_command_lower]
                args += (message.get("botCommandArg") or "").split(" ")
                await self.send_warudo("OnChatCmd", args)

            await db.commit()  # NOTE: must commit after any usage of db

    async def on_enter_stream(self, message: dict[Any, Any]):
        """
        Handle a viewer joining a channel.

        - Marks the viewer as present.
        - Does NOT handle rewards; rewarding occurs on leave, stream end or recovery.

        Notes:
        - This event may arrive while the channel is offline.
        """
        username = message.get("text")
        channel_id = message.get("channelId")
        if not username or not channel_id:
            return

        async with get_async_db() as db:
            viewer = await jstv_db.get_or_create_viewer(db, channel_id, username)

            # Handle viewer join
            viewer.join()

            await db.commit()  # NOTE: must commit after any usage of db

    async def on_leave_stream(self, message: dict[Any, Any]):
        """
        Handle a viewer leaving a channel.

        - Marks the viewer as not present.
        - Rewards the viewer.

        Notes:
        - Viewers who joined while the channel was offline are NOT rewarded here.
          Their potential reward (if any) is handled by `on_stream_ended` or recovery.
        """
        username = message.get("text")
        channel_id = message.get("channelId")
        if not username or not channel_id:
            return

        async with get_async_db() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)
            viewer = await jstv_db.get_or_create_viewer(db, channel, username)

            if not viewer.is_present:
                # Viewer has already left
                self.logger.info(
                    "Fail-safe: Viewer already left channel %s at %s - ignoring",
                    channel_id, viewer.left_at,
                )

            else:
                # Handle viewer leaving and reward
                viewer.leave()
                await reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

            await db.commit()  # NOTE: must commit after any usage of db

    async def on_followed(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        await self.send_warudo("OnFollowed", metadata.get("number_of_followers") or 0)

        # TODO: reward points

    async def on_subscribed(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        await self.send_warudo("OnSubscribed", str(metadata.get("who")))

    async def on_tipped(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        OVERRIDE_VIBES = True

        channel_id = message.get("channelId") or ""
        username = metadata.get("who") or ""
        amount = metadata.get("how_much") or 0
        tasks = []

        if not OVERRIDE_VIBES:
            tasks.append(self.talkto("Buttplug", "disable", 180))

        else:
            vibes: tuple[VibeFrame, ...] | None = None

            # Basic Levels
            if 1 <= amount <= 1:
                vibes = (VibeFrame.new_override(amount +  2, 1.00),)
            elif 2 <= amount <= 3:
                vibes = (VibeFrame.new_override(amount *  5, 0.50),)
            elif 4 <= amount <= 10:
                vibes = (VibeFrame.new_override(amount * 10, .025),)
            elif 13 <= amount <= 35:
                vibes = (VibeFrame.new_override(amount *  3, 0.50),)
            elif 40 <= amount <= 199:
                vibes = (VibeFrame.new_override(amount *  2, 0.75),)
            elif amount >= 200:
                vibes = (VibeFrame.new_override(amount /  2, 1.00),)

            # Special Commands
            # elif amount == ...:
            #     vibes = ...  # Random Level
            elif amount == 11:
                vibes = parse_vibes("50% 30-90s")  # Random Time
            elif amount == 12:
                vibes = parse_vibes("12s 0%")  # Pause the Queue
            elif amount == 36:
                vibes = parse_vibes("1s 0% 20% 40% 60% 80% 100% 72t")  # Earthquake Pattern
            elif amount == 37:
                vibes = parse_vibes("1s 0% 10% 20% 30% 40% 50% 60% 70% 100% 74t")  # Fireworks Pattern
            elif amount == 38:
                vibes = parse_vibes("1.5s 1..100% 1.5s 100..1% 76t")  # Wave Pattern
            elif amount == 39:
                vibes = parse_vibes("1s 0% 100% 78t")  # Pulse Pattern

            if vibes:
                vibe_group = VibeGroup(vibes, channel_id=channel_id, username=username)
                tasks.append(self.talkto("Buttplug", "vibe", vibe_group))

        tasks.append(self.send_warudo("OnTipped", amount))

        tip_menu_item = str(metadata.get("tip_menu_item") or "")
        if tip_menu_item:
            tasks.append(self.send_warudo("OnRedeemed", tip_menu_item))

        await asyncio.gather(*tasks)

        # TODO: reward points

    async def on_tip_goal_increased(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        step = 100
        current = metadata.get("current") or 0
        previous = metadata.get("previous") or 0

        tasks = [
            self.send_warudo("OnTipGoalIncreased", [current, previous]),
        ]

        steps_increased = current // step - previous // step
        if steps_increased > 0:
            tasks.append(self.send_warudo("OnTipGoalPeriodicStep", steps_increased))

        await asyncio.gather(*tasks)

    async def on_milestone_completed(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        await self.send_warudo("OnMilestoneCompleted", metadata.get("amount") or 0)

    async def on_tip_goal_met(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        await self.send_warudo("OnTipGoalMet", metadata.get("amount") or 0)

    async def on_stream_dropped_in(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        await self.send_warudo("OnStreamDroppedIn", metadata.get("number_of_viewers") or 0)

        # TODO: reward points?

    async def send_chat(self, channel_id: str, text: str, *, at: Optional[str] = None):
        await self.talk("chat", {
            "text": text,
            "channelId": channel_id,
            "at": at,
        })

    async def send_channel_chats(self, channel_ids: Iterable[str], text: str, *, at: Optional[str] = None):
        await asyncio.gather(*[
            self.send_chat(channel_id, text, at=at)
            for channel_id in channel_ids
        ])

    async def send_live_chats(self, text: str, *, at: Optional[str] = None):
        await self.send_channel_chats(self.live_channels.keys(), text, at=at)

    async def send_chat_reply(self, ctxmsg: dict[Any, Any], text: str, *, at: bool = False):
        await self.send_chat(
            channel_id=ctxmsg["channelId"],
            text=text,
            at=ctxmsg["author"]["username"] if at else None,
        )

    async def send_warudo(self, action: str, data: Any = None):
        await self.talkto("Warudo", "action", {"action": action, "data": data})

    async def send_streamerbot(self, action: str, args: dict[str, Any] = {}):
        await self.talkto("StreamerBot", "action", {"name": action, "args": args})
