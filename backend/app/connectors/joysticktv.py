from typing import Optional, Any, Coroutine, Iterable
import asyncio
# import enum
import logging
import json
import random
import websockets
import html

from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import getenv_list
from app.connector import ConnectorMessage, ConnectorManager, WebSocketConnector
from app.connectors.warudo import QUIRKY_ANIMALS_MAP
from app.connectors.buttplug import VibeGroup, VibeFrame, parse_vibes
from app.handlers.jstv import (
    events as event_handlers,
    commands as command_handlers,
)

from app.db.database import AsyncSessionMaker
from app.db.enums import CommandAccessLevel

from app.events import jstv as evjstv

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

VIP_USERS = tuple(x.casefold() for x in getenv_list("JOYSTICKTV_VIP_USERS"))


# ==============================================================================
# Enums

# class ReplyMode(enum.Enum):
#     CHAT = enum.auto()
#     MENTION = enum.auto()
#     WHISPER = enum.auto()


# ==============================================================================
# JoystickTV Connector

class LiveChannel:
    pass

class JoystickTVConnector(WebSocketConnector):
    live_channels: dict[str, LiveChannel]

    def __init__(self, manager: ConnectorManager, name: Optional[str] = None, url: Optional[str] = None):
        super().__init__(manager, name or NAME, url or URL)
        self.live_channels = {}

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

            for line in text.split("\n"):
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

        async with AsyncSessionMaker.begin() as db:
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

        async with AsyncSessionMaker.begin() as db:
            await jstv_dbstate.on_disconnected(db)

    async def on_message(self, data: dict[Any, Any]):
        async with AsyncSessionMaker.begin() as db:
            await jstv_dbstate.on_server_message(db)

        try:
            event = evjstv.JSTVEvent.parse(data)
        except evjstv.JSTVParseError:
            return  # NOTE: Parser handles logging

        iscontrol = isinstance(event, evjstv.JSTVControlEvent)
        isdebug = self.logger.getEffectiveLevel() <= logging.DEBUG

        if isdebug:  # Log full event if debugging
            self.logger.debug("Received: %r", event)

        if iscontrol:
            if isinstance(event, evjstv.JSTVPingEvent):
                return

        if not isdebug:  # Log summary event if not debugging
            self.logger.info("Received: %s", event)

        if iscontrol:
            if isinstance(event, evjstv.JSTVRejectSubscriptionEvent):
                self._connected = False

            elif isinstance(event, evjstv.JSTVConfirmSubscriptionEvent):
                self._connected = True

            # elif isinstance(event, evjstv.JSTVWelcomeEvent):
            #     ...

            return

        if not self._connected:
            return

        if not evjstv.evmsgisinstance(event, evjstv.JSTVMessage):
            return

        evmsg = event.message

        if isinstance(evmsg, evjstv.JSTVSteamStarted):
            await self.on_stream_started(evmsg)

        elif isinstance(evmsg, evjstv.JSTVStreamEnded):
            await self.on_stream_ended(evmsg)

        elif isinstance(evmsg, evjstv.JSTVStreamResuming):
            await self.on_stream_resuming(evmsg)

        elif isinstance(evmsg, evjstv.JSTVNewChatMessage):
            await self.on_new_chat(evmsg)

        elif isinstance(evmsg, evjstv.JSTVUserEnteredStream):
            await self.on_enter_stream(evmsg)

        elif isinstance(evmsg, evjstv.JSTVUserLeftStream):
            await self.on_leave_stream(evmsg)

        elif isinstance(evmsg, evjstv.JSTVFollowed):
            await self.on_followed(evmsg)

        elif isinstance(evmsg, evjstv.JSTVSubscribed):
            await self.on_subscribed(evmsg)

        elif isinstance(evmsg, evjstv.JSTVTipped):
            await self.on_tipped(evmsg)

        elif isinstance(evmsg, evjstv.JSTVTipGoalIncreased):
            await self.on_tip_goal_increased(evmsg)

        elif isinstance(evmsg, evjstv.JSTVMilestoneCompleted):
            await self.on_milestone_completed(evmsg)

        elif isinstance(evmsg, evjstv.JSTVTipGoalMet):
            await self.on_tip_goal_met(evmsg)

        elif isinstance(evmsg, evjstv.JSTVStreamDroppedIn):
            await self.on_stream_dropped_in(evmsg)

        async with AsyncSessionMaker.begin() as db:
            channel_id = evmsg.channelId
            username = evmsg.actorname

            channel = await jstv_db.get_or_create_channel(db, channel_id)
            user = await jstv_db.get_or_create_user(db, username) if username else None
            viewer = await jstv_db.get_or_create_viewer(db, channel, user) if user else None

            for handler in event_handlers.iter_by_type(type(evmsg)):
                settings = handler.settings

                ctx = event_handlers.JSTVEventHandlerContext(
                    settings=settings,
                    connector=self,
                    message=evmsg,
                    channel=channel,
                    user=user,
                    viewer=viewer,
                )

                self.logger.debug("Invoking event handler %r", handler.key)

                try:
                    if not await handler.handle(ctx):
                        return
                except Exception as e:
                    self.logger.exception("Failed to handle command %r: %s", handler.key, e)

    async def on_stream_started(self, evmsg: evjstv.JSTVSteamStarted):
        """Handle a channel transitioning to live."""
        channel_id = evmsg.channelId

        # Ensure live channel cache exists
        live_channel = self.live_channels.get(channel_id)
        if live_channel is None:
            live_channel = self.live_channels[channel_id] = LiveChannel()

        async with AsyncSessionMaker.begin() as db:
            await jstv_dbstate.on_stream_started(db, channel_id)

    async def on_stream_resuming(self, evmsg: evjstv.JSTVStreamResuming):
        """Handle a channel resuming its stream after a short disconnect."""
        channel_id = evmsg.channelId

        # Ensure live channel cache exists
        live_channel = self.live_channels.get(channel_id)
        if live_channel is None:
            live_channel = self.live_channels[channel_id] = LiveChannel()

        async with AsyncSessionMaker.begin() as db:
            await jstv_dbstate.on_stream_resuming(db, channel_id)

    async def on_stream_ended(self, evmsg: evjstv.JSTVStreamEnded):
        """Handle a channel transitioning to offline."""
        channel_id = evmsg.channelId

        # Remove channel from in-memory live cache
        self.live_channels.pop(channel_id, None)

        async with AsyncSessionMaker.begin() as db:
            await jstv_dbstate.on_stream_ended(db, channel_id)

    async def on_new_chat(self, evmsg: evjstv.JSTVNewChatMessage) -> None:
        channel_id = evmsg.channelId
        username = evmsg.author.username

        bot_command_fold = (evmsg.botCommand or "").casefold()

        async with AsyncSessionMaker.begin() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)
            user = await jstv_db.get_or_create_user(db, username)
            viewer = await jstv_db.get_or_create_viewer(db, channel, user)

            await jstv_dbstate.on_new_chat(db, channel, user, viewer)

            cmd = command_handlers.get_by_alias(bot_command_fold)
            if cmd is not None:
                settings = cmd.settings

                access_level = CommandAccessLevel.viewer
                if evmsg.sameAuthorAsStreamer:
                    access_level = CommandAccessLevel.broadcaster
                elif evmsg.author.isModerator:
                    access_level = CommandAccessLevel.moderator
                elif evmsg.author.slug.casefold() in VIP_USERS:
                    access_level = CommandAccessLevel.vip
                elif evmsg.author.isSubscriber:
                    access_level = CommandAccessLevel.subscriber
                elif viewer.followed_at is not None:
                    if evmsg.author.isVerified:
                        access_level = CommandAccessLevel.verified_follower
                    else:
                        access_level = CommandAccessLevel.follower
                elif evmsg.author.isVerified:
                    access_level = CommandAccessLevel.verified

                if access_level < settings.min_access_level:
                    await self.send_chat_reply(evmsg, (
                        f"You do not have permission to"
                        f" use the !{bot_command_fold} command"
                    ), mention=True)
                    return

                await jstv_dbstate.reward_viewer(channel, viewer)  # WARNING: Channel and viewer must be up-to-date

                ctx = command_handlers.JSTVCommandContext(
                    settings=settings,
                    connector=self,
                    message=evmsg,
                    alias=bot_command_fold,
                    channel=channel,
                    user=user,
                    viewer=viewer,
                )

                if settings.point_cost > viewer.points:
                    await self.send_chat_reply(
                        evmsg,
                        f"You do not have enough points to use the {bot_command_fold} command",
                        whisper=True,
                    )
                    return

                self.logger.info("Invoking command handler %r", cmd.key)

                try:
                    if not await cmd.handle(ctx):
                        return
                except Exception as e:
                    self.logger.exception("Failed to handle command %r: %s", cmd.key, e)

                if settings.point_cost > 0:
                    viewer.points = max(0, viewer.points - settings.point_cost)

            elif bot_command_fold == "test_tip":
                if not evmsg.sameAuthorAsStreamer:
                    await self.send_chat_reply(
                        evmsg,
                        f"You do not have the necessary permissions to use the {bot_command_fold} command",
                        mention=True,
                    )
                    return

                amount = 0

                if evmsg.botCommandArg:
                    try:
                        amount = int(evmsg.botCommandArg)
                    except ValueError:
                        pass

                tipped_evmsg = evjstv.JSTVTipped(
                    event="StreamEvent",
                    type="Tipped",
                    id=evmsg.id,
                    text=evmsg.text,
                    createdAt=evmsg.createdAt,
                    channelId=channel_id,
                    metadata=evjstv.JSTVTipped.Metadata(
                        who="TEST",
                        what="Tipped",
                        how_much=amount,
                        tip_menu_item=None,
                    ),
                )

                await asyncio.gather(
                    self.send_chat_reply(evmsg, f"Sending test tip of {amount} tokens"),
                    self.on_tipped(tipped_evmsg),
                )

            elif bot_command_fold:
                args = evmsg.splitBotCommandArg()
                args.insert(0, bot_command_fold)
                await self.send_warudo("OnChatCmd", args)

    async def on_enter_stream(self, evmsg: evjstv.JSTVUserEnteredStream):
        """Handle a viewer joining a channel."""
        channel_id = evmsg.channelId
        username = evmsg.username

        async with AsyncSessionMaker.begin() as db:
            await jstv_dbstate.on_enter_stream(db, channel_id, username, None)

    async def on_leave_stream(self, evmsg: evjstv.JSTVUserLeftStream):
        """Handle a viewer leaving a channel."""
        channel_id = evmsg.channelId
        username = evmsg.username

        async with AsyncSessionMaker.begin() as db:
            await jstv_dbstate.on_leave_stream(db, channel_id, username, None)

    async def on_followed(self, evmsg: evjstv.JSTVFollowed):
        metadata = evmsg.metadata
        channel_id = evmsg.channelId
        username = metadata.who

        async with AsyncSessionMaker.begin() as db:
            points = await jstv_dbstate.on_followed(db, channel_id, username, None)
            if points > 0:
                # tasks.append(self.send_chat_reply(evmsg, (
                #     f"Thanks for following, {username}!"
                #     f" You've been rewarded {points} points."
                # ), whisper=True))
                pass

            await self.send_warudo("OnFollowed")

    async def on_subscribed(self, evmsg: evjstv.JSTVSubscribed):
        metadata = evmsg.metadata
        channel_id = evmsg.channelId
        username = metadata.who

        async with AsyncSessionMaker.begin() as db:
            points = await jstv_dbstate.on_subscribed(db, channel_id, username, None)
            if points > 0:
                # tasks.append(self.send_chat_reply(evmsg, (
                #     f"Thanks for subscribing, {username}!"
                #     f" You've been rewarded {points} points."
                # ), whisper=True))
                pass

            await self.send_warudo("OnSubscribed", username)

    async def on_tipped(self, evmsg: evjstv.JSTVTipped):
        OVERRIDE_VIBES = True

        metadata = evmsg.metadata
        channel_id = evmsg.channelId
        username = metadata.who
        amount = metadata.how_much

        async with AsyncSessionMaker.begin() as db:
            tasks: list[Coroutine[Any, Any, None]] = []

            points = await jstv_dbstate.on_tipped(db, channel_id, username, None, amount)
            if points > 0:
                # tasks.append(self.send_chat_reply(evmsg, (
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

            tip_menu_item: str = str(metadata.tip_menu_item or "")
            if tip_menu_item:
                tasks.append(self.send_warudo("OnRedeemed", tip_menu_item))

            await asyncio.gather(*tasks)

    async def on_tip_goal_increased(self, evmsg: evjstv.JSTVTipGoalIncreased):
        STEP = 100

        metadata = evmsg.metadata
        current = metadata.current
        previous = metadata.previous

        tasks = [
            self.send_warudo("OnTipGoalIncreased", [current, previous]),
        ]

        steps_increased = current // STEP - previous // STEP
        if steps_increased > 0:
            tasks.append(self.send_warudo("OnTipGoalPeriodicStep", steps_increased))

        await asyncio.gather(*tasks)

    async def on_milestone_completed(self, evmsg: evjstv.JSTVMilestoneCompleted):
        metadata = evmsg.metadata
        amount: int = metadata.amount
        await self.send_warudo("OnMilestoneCompleted", amount)

    async def on_tip_goal_met(self, evmsg: evjstv.JSTVTipGoalMet):
        metadata = evmsg.metadata
        amount: int = metadata.amount
        await self.send_warudo("OnTipGoalMet", amount)

    async def on_stream_dropped_in(self, evmsg: evjstv.JSTVStreamDroppedIn):
        metadata = evmsg.metadata
        channel_id = evmsg.channelId
        username = metadata.who
        number_of_viewers = metadata.number_of_viewers

        async with AsyncSessionMaker.begin() as db:
            points = await jstv_dbstate.on_raided(db, channel_id, username, None, number_of_viewers)
            if points > 0:
                # tasks.append(self.send_chat_reply(evmsg, (
                #     f"Thanks for the drop-in, {username}!"
                #     f" You've been rewarded {points} points."
                # ), whisper=True))
                pass

            await self.send_warudo("OnStreamDroppedIn", number_of_viewers)

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
        evmsg: evjstv.JSTVBaseChatMessage,
        text: str,
        *,
        mention: bool = False,
        whisper: bool = False,
    ):
        await self.send_chat(
            channel_id=evmsg.channelId,
            text=text,
            mention=evmsg.author.username if mention else None,
            whisper=evmsg.author.username if whisper else None,
        )

    async def send_warudo(self, action: str, data: Any = None):
        await self.talkto("Warudo", "action", {"action": action, "data": data})

    async def send_streamerbot(self, action: str, args: dict[str, Any] | None = None):
        await self.talkto("StreamerBot", "action", {"name": action, "args": args or {}})
