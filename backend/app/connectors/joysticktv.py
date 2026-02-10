from typing import Optional, Any, Awaitable, Coroutine, Callable, Iterable
import asyncio
import json
import random
import websockets
import html

from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import getenv_list
from app.connector import ConnectorMessage, ConnectorManager, WebSocketConnector
from app.connectors.warudo import QUIRKY_ANIMALS_MAP
from app.connectors.buttplug import VibeGroup, VibeFrame, parse_vibes
from app import commands

from app.db.database import get_async_db

from app.jstv import jstv_db
from app.jstv.jstv_web import WS_HOST, ACCESS_TOKEN
from app.jstv import jstv_dbstate

QUIRKY_ANIMALS_LIST = tuple(QUIRKY_ANIMALS_MAP.items())


# ==============================================================================
# Config

GATEWAY_IDENTIFIER = '{"channel":"GatewayChannel"}'

NAME = "JoystickTV"
URL = f"{WS_HOST}?token={ACCESS_TOKEN}"

SUBPROTOCOL_ACTIONABLE = websockets.Subprotocol("actioncable-v1-json")

VIP_USERS = getenv_list("JOYSTICKTV_VIP_USERS")


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
        metadata_str: str = _message.get("metadata") or ""

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
            text: str = msg.data["text"].strip()
            channelId: str = msg.data["channelId"]
            mention: str | None = msg.data.get("mention")
            whisper: str | None = msg.data.get("whisper")

            if mention:
                text = f"@{mention} {text}"

            for line in msg.data["text"].split("\n"):
                line = line.rstrip()
                if not line:
                    continue

                data = {
                    "action": "send_message",
                    "text": html.escape(line),
                    "channelId": channelId,
                }

                if whisper:
                    data["action"] = "send_whisper"
                    data["username"] = whisper

                await self.sendnow({
                    "command": "message",
                    "identifier": GATEWAY_IDENTIFIER,
                    "data": json.dumps(data),
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

            await db.commit()

        # WARNING: Must send messages AFTER _update_live_channels() is done to ensure consistent state
        await self.send_live_chats("おはよう世界 Good Morning World <3")

    async def _update_live_channels(self, db: AsyncSession):
        """
        Synchronize live channel state and recover viewer presence.

        - Rebuilds the live channel cache from current stream state.
        - Reconciles channel live/offline state with the database.
        """
        # Clear live channel state
        self.live_channels.clear()

        # Reconcile channel state
        channels = await jstv_dbstate.on_connected(db)

        # Rebuild live channel cache
        for channel in channels:
            if channel.is_live:
                self.live_channels[channel.channel_id] = LiveChannel()

    async def on_disconnected(self):
        """Handle loss of connection or shutdown."""
        self.logger.info("Connection closed")

        async with get_async_db() as db:
            await jstv_dbstate.on_disconnected(db)
            await db.commit()

    async def on_message(self, data: dict[Any, Any]):
        async with get_async_db() as db:
            await jstv_dbstate.on_server_message(db)
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
        """Handle a channel transitioning to live."""
        channel_id: str | None = message.get("channelId")
        if not channel_id:
            return

        self.logger.info("Stream started: %s", channel_id)

        # Ensure live channel cache exists
        live_channel = self.live_channels.get(channel_id)
        if live_channel is None:
            live_channel = self.live_channels[channel_id] = LiveChannel()

        async with get_async_db() as db:
            await jstv_dbstate.on_stream_started(db, channel_id)
            await db.commit()

    async def on_stream_resuming(self, message: dict[Any, Any]):
        """Handle a channel resuming its stream after a short disconnect."""
        channel_id: str | None = message.get("channelId")
        if not channel_id:
            return

        self.logger.info("Stream resuming: %s", channel_id)

        # Ensure live channel cache exists
        live_channel = self.live_channels.get(channel_id)
        if live_channel is None:
            live_channel = self.live_channels[channel_id] = LiveChannel()

        async with get_async_db() as db:
            await jstv_dbstate.on_stream_resuming(db, channel_id)
            await db.commit()

    async def on_stream_ended(self, message: dict[Any, Any]):
        """Handle a channel transitioning to offline."""
        channel_id: str | None = message.get("channelId")
        if not channel_id:
            return

        self.logger.info("Stream ended: %s", channel_id)

        # Remove channel from in-memory live cache
        self.live_channels.pop(channel_id, None)

        async with get_async_db() as db:
            await jstv_dbstate.on_stream_ended(db, channel_id)
            await db.commit()

    async def on_new_chat(self, message: dict[Any, Any]):
        channel_id: str | None = message.get("channelId")
        username: str | None = message.get("author", {}).get("username")
        if not channel_id or not username:
            return

        text_lower: str = (message.get("text") or "").lower()
        bot_command_lower: str = (message.get("botCommand") or "").lower()

        async with get_async_db() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)
            user = await jstv_db.get_or_create_user(db, username)
            viewer = await jstv_db.get_or_create_viewer(db, channel, user)

            await jstv_dbstate.on_new_chat(db, channel, user, viewer)

            cmd = commands.get_by_alias(bot_command_lower)
            if cmd is not None:
                await jstv_dbstate.reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

                settings = cmd.settings

                ctx = commands.CommandContext(
                    connector=self,
                    channel=channel,
                    user=user,
                    viewer=viewer,
                    settings=settings,
                    event=message,
                    fields={},
                )

                if settings.point_cost > viewer.points:
                    await self.send_chat_reply(
                        message,
                        f"You do not have enough points to use the {bot_command_lower} command",
                        whisper=True,
                    )
                    return

                try:
                    if not await cmd.handle(ctx):
                        return
                except Exception as e:
                    self.logger.exception("Failed to handle command %r: %s", cmd.key, e)

                viewer.points -= max(0, settings.point_cost)

            elif bot_command_lower in ["points", "p"]:
                await jstv_dbstate.reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date
                await self.send_chat_reply(
                    message,
                    f"has {int(viewer.points)} points",
                    mention=True,
                )

            elif bot_command_lower == "test_tip":
                slug: str = message["author"]["slug"]
                if slug != message["streamer"]["slug"]:
                    await self.send_chat_reply(
                        message,
                        f"You do not have the necessary permissions to use the {bot_command_lower} command",
                        mention=True,
                    )
                    return

                amount = 0

                arg: str | None = message.get("botCommandArg")
                if arg:
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
                    self.send_chat_reply(
                        message,
                        f"has been plushified into a {animal}",
                        mention=True,
                    ),
                    self.send_warudo("Plushify", [username, prop]),
                )

            elif any(x == bot_command_lower for x in ["viewersign", "sign", "showsign"]):
                text: str | None = message.get("botCommandArg")
                if not text:
                    await self.send_chat_reply(
                        message,
                        f"Usage: !{bot_command_lower} <TEXT>",
                        mention=True,
                    )
                    return

                await self.send_warudo("ViewerSign", text)

            elif bot_command_lower == "clip":
                await asyncio.gather(
                    self.talkto("OBS", "clip", None),
                    self.send_chat_reply(message, f"Creating a clip of the last 2 minutes"),
                )

            elif bot_command_lower in ["vibe_disable", "vibe_delay"]:
                slug: str = message["author"]["slug"]
                if slug != message["streamer"]["slug"]:
                    await self.send_chat_reply(
                        message,
                        f"You do not have the necessary permissions to use the {bot_command_lower} command",
                        mention=True,
                    )
                    return

                try:
                    delay = float(message["botCommandArg"])
                except (KeyError, TypeError, ValueError):
                    await self.send_chat_reply(
                        message,
                        f"Usage: !{bot_command_lower} [SECONDS]",
                        mention=True,
                    )
                    return

                await self.talkto("Buttplug", "disable", delay)
                return

            elif bot_command_lower in ["vibe_stop", "vibe_clear"]:
                slug: str = message["author"]["slug"]
                if slug != message["streamer"]["slug"]:
                    await self.send_chat_reply(
                        message,
                        f"You do not have the necessary permissions to use the {bot_command_lower} command",
                        mention=True,
                    )
                    return

                await self.talkto("Buttplug", "stop", None)
                return

            elif bot_command_lower == "vibe":
                # slug: str = message["author"]["slug"]
                # if slug != message["streamer"]["slug"] and slug.lower() not in VIP_USERS:
                #     await self.send_chat_reply(
                #         message,
                #         f"You do not have the necessary permissions to use the {bot_command_lower} command",
                #         mention=True,
                #     )
                #     return

                vibestr: str | None = message.get("botCommandArg")
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
                    ).strip(), mention=True)

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
                args: list[str] = str(message.get("botCommandArg") or "").split(" ")
                args.insert(0, bot_command_lower)
                await self.send_warudo("OnChatCmd", args)

            await db.commit()  # NOTE: must commit after any usage of db

    async def on_enter_stream(self, message: dict[Any, Any]):
        """Handle a viewer joining a channel."""
        channel_id: str | None = message.get("channelId")
        username: str | None = message.get("text")
        if not channel_id or not username:
            return

        async with get_async_db() as db:
            await jstv_dbstate.on_enter_stream(db, channel_id, username, None)
            await db.commit()  # NOTE: must commit after any usage of db

    async def on_leave_stream(self, message: dict[Any, Any]):
        """Handle a viewer leaving a channel."""
        channel_id: str | None = message.get("channelId")
        username: str | None = message.get("text")
        if not channel_id or not username:
            return

        async with get_async_db() as db:
            await jstv_dbstate.on_leave_stream(db, channel_id, username, None)
            await db.commit()  # NOTE: must commit after any usage of db

    async def on_followed(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        channel_id: str | None = message.get("channelId")
        username: str | None = metadata.get("who")
        if not channel_id or not username:
            return

        async with get_async_db() as db:
            points = await jstv_dbstate.on_followed(db, channel_id, username, None)
            if points > 0:
                # tasks.append(self.send_chat_reply(message, (
                #     f"Thanks for following, {username}!"
                #     f" You've been rewarded {points} points."
                # ), whisper=True))
                pass

            await self.send_warudo("OnFollowed")

            await db.commit()  # NOTE: must commit after any usage of db

    async def on_subscribed(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        channel_id: str | None = message.get("channelId")
        username: str | None = metadata.get("who")
        if not channel_id or not username:
            return

        async with get_async_db() as db:
            points = await jstv_dbstate.on_subscribed(db, channel_id, username, None)
            if points > 0:
                # tasks.append(self.send_chat_reply(message, (
                #     f"Thanks for subscribing, {username}!"
                #     f" You've been rewarded {points} points."
                # ), whisper=True))
                pass

            await self.send_warudo("OnSubscribed", username)

            await db.commit()  # NOTE: must commit after any usage of db

    async def on_tipped(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        OVERRIDE_VIBES = True

        channel_id: str | None = message.get("channelId")
        username: str | None = metadata.get("who")
        if not channel_id or not username:
            return

        amount: int = metadata.get("how_much") or 0

        async with get_async_db() as db:
            tasks: list[Coroutine[Any, Any, None]] = []

            points = await jstv_dbstate.on_tipped(db, channel_id, username, None, amount)
            if points > 0:
                # tasks.append(self.send_chat_reply(message, (
                #     f"Thanks for tipping, {username}!"
                #     f" You've been rewarded {points} points."
                # ), whisper=True))
                pass

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

            tip_menu_item: str = str(metadata.get("tip_menu_item") or "")
            if tip_menu_item:
                tasks.append(self.send_warudo("OnRedeemed", tip_menu_item))

            await asyncio.gather(*tasks)
            await db.commit()

    async def on_tip_goal_increased(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        step = 100
        current: int = metadata.get("current") or 0
        previous: int = metadata.get("previous") or 0

        tasks = [
            self.send_warudo("OnTipGoalIncreased", [current, previous]),
        ]

        steps_increased = current // step - previous // step
        if steps_increased > 0:
            tasks.append(self.send_warudo("OnTipGoalPeriodicStep", steps_increased))

        await asyncio.gather(*tasks)

    async def on_milestone_completed(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        amount: int = metadata.get("amount") or 0
        await self.send_warudo("OnMilestoneCompleted", amount)

    async def on_tip_goal_met(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        amount: int = metadata.get("amount") or 0
        await self.send_warudo("OnTipGoalMet", amount)

    async def on_stream_dropped_in(self, message: dict[Any, Any], metadata: dict[Any, Any]):
        channel_id: str | None = message.get("channelId")
        username: str | None = metadata.get("who")
        if not channel_id or not username:
            return

        number_of_viewers: int = metadata.get("number_of_viewers") or 0

        async with get_async_db() as db:
            points = await jstv_dbstate.on_raided(db, channel_id, username, None, number_of_viewers)
            if points > 0:
                # tasks.append(self.send_chat_reply(message, (
                #     f"Thanks for the drop-in, {username}!"
                #     f" You've been rewarded {points} points."
                # ), whisper=True))
                pass

            await self.send_warudo("OnStreamDroppedIn", number_of_viewers)

            await db.commit()

    async def send_chat(
        self,
        channel_id: str,
        text: str,
        *,
        mention: Optional[str] = None,
        whisper: Optional[str] = None,
    ):
        await self.talk("chat", {
            "text": text,
            "channelId": channel_id,
            "mention": mention,
            "whisper": whisper,
        })

    async def send_channel_chats(
        self,
        channel_ids: Iterable[str],
        text: str,
        *,
        mention: Optional[str] = None,
        whisper: Optional[str] = None,
    ):
        await asyncio.gather(*[
            self.send_chat(
                channel_id,
                text,
                mention=mention,
                whisper=whisper,
            )
            for channel_id in channel_ids
        ])

    async def send_live_chats(
        self,
        text: str,
        *,
        mention: Optional[str] = None,
        whisper: Optional[str] = None,
    ):
        await self.send_channel_chats(
            self.live_channels.keys(),
            text,
            mention=mention,
            whisper=whisper,
        )

    async def send_chat_reply(
        self,
        ctxmsg: dict[Any, Any],
        text: str,
        *,
        mention: bool = False,
        whisper: bool = False,
    ):
        await self.send_chat(
            channel_id=ctxmsg["channelId"],
            text=text,
            mention=ctxmsg["author"]["username"] if mention else None,
            whisper=ctxmsg["author"]["username"] if whisper else None,
        )

    async def send_warudo(self, action: str, data: Any = None):
        await self.talkto("Warudo", "action", {"action": action, "data": data})

    async def send_streamerbot(self, action: str, args: dict[str, Any] | None = None):
        await self.talkto("StreamerBot", "action", {"name": action, "args": args or {}})
