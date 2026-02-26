from typing import ClassVar, Any, Iterable
import asyncio
# import enum
import logging
import json
import websockets
import html

from sqlalchemy.ext.asyncio import AsyncSession

from app.settings import getenv_list, POINTS_NAME
from app.connector import ConnectorMessage, ConnectorManager, WebSocketConnector
from app.connectors.warudo import QUIRKY_ANIMALS_MAP
from app.handlers.jstv.commands import db as dbcmdhandlers
from app.handlers.jstv.events import db as dbevhandlers

from app.db.database import AsyncSessionMaker

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
    NAME: ClassVar[str] = NAME

    live_channels: dict[str, LiveChannel]

    def __init__(self, manager: ConnectorManager):
        super().__init__(manager)
        self.live_channels = {}

    def _get_url(self) -> str:
        return URL

    def _create_connection(self) -> websockets.connect:
        return websockets.connect(
            self._get_url(),
            subprotocols=[SUBPROTOCOL_ACTIONABLE],
        )

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
        if evmsg.isFake:
            return

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

        elif isinstance(evmsg, evjstv.JSTVStreamDroppedIn):
            await self.on_stream_dropped_in(evmsg)

        async with AsyncSessionMaker.begin() as db:
            channel_id = evmsg.channelId
            username = evmsg.actorname

            channel = await jstv_db.get_or_create_channel(db, channel_id)
            user = await jstv_db.get_or_create_user(db, username) if username else None
            viewer = await jstv_db.get_or_create_viewer(db, channel, user) if user else None

            if viewer is not None:
                await jstv_dbstate.on_viewer_interaction(db, channel, user, viewer)

            await dbevhandlers.invoke_events(
                db=db,
                channel=channel,
                user=user,
                viewer=viewer,
                connector=self,
                message=evmsg,
            )

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

        async with AsyncSessionMaker.begin() as db:
            channel = await jstv_db.get_or_create_channel(db, channel_id)
            user = await jstv_db.get_or_create_user(db, username)
            viewer = await jstv_db.get_or_create_viewer(db, channel, user)

            await jstv_dbstate.on_new_chat(db, channel, user, viewer)

            # TODO: Move these viewer updates to jstv_dbstate somewhere
            viewer.is_streamer = evmsg.author.isStreamer
            viewer.is_moderator = evmsg.author.isModerator
            viewer.is_subscriber = evmsg.author.isSubscriber
            viewer.is_verified = evmsg.author.isVerified
            viewer.is_content_creator = evmsg.author.isContentCreator

            if evmsg.botCommand:
                await dbcmdhandlers.invoke_command(
                    db,
                    channel,
                    user,
                    viewer,
                    self,
                    evmsg,
                    evmsg.botCommand,
                    evmsg.botCommandArg,
                )

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
        channel_id = evmsg.channelId
        username = evmsg.actorname

        async with AsyncSessionMaker.begin() as db:
            points = await jstv_dbstate.on_followed(db, channel_id, username, None)
            if points > 0:
                await self.send_chat(channel_id, (
                    f"Thanks for following!"
                    f" +{points} {POINTS_NAME}"
                ), whisper=username)

    async def on_subscribed(self, evmsg: evjstv.JSTVSubscribed):
        channel_id = evmsg.channelId
        username = evmsg.actorname

        async with AsyncSessionMaker.begin() as db:
            points = await jstv_dbstate.on_subscribed(db, channel_id, username, None)
            if points > 0:
                await self.send_chat(channel_id, (
                    f"Thanks for subscribing!"
                    f" +{points} {POINTS_NAME}"
                ), whisper=username)

    async def on_tipped(self, evmsg: evjstv.JSTVTipped):
        async with AsyncSessionMaker.begin() as db:
            await self._on_tipped_internal(
                db=db,
                channel_id=evmsg.channelId,
                username=evmsg.actorname,
                tip_amount=evmsg.metadata.how_much,
                tip_menu_item=evmsg.metadata.tip_menu_item,
                evmsg=evmsg,
            )

    async def _on_tipped_internal(
        self,
        db: AsyncSession,
        channel_id: str,
        username: str,
        tip_amount: int,
        tip_menu_item: str | None = None,
        *,
        evmsg: evjstv.JSTVMessage | None = None,
        fake: bool = False,
    ):
        fake = fake or evmsg is None or evmsg.isFake

        async with AsyncSessionMaker.begin() as db:
            if not fake:
                points = await jstv_dbstate.on_tipped(db, channel_id, username, None, tip_amount)
                # if points > 0:
                #     tasks.append(self.send_chat(channel_id, (
                #         f"Thanks for the tip!"
                #         f" +{points} {POINTS_NAME}"
                #     ), whisper=username))

    async def on_stream_dropped_in(self, evmsg: evjstv.JSTVStreamDroppedIn):
        channel_id = evmsg.channelId
        username = evmsg.actorname
        number_of_viewers = evmsg.metadata.number_of_viewers

        async with AsyncSessionMaker.begin() as db:
            points = await jstv_dbstate.on_raided(db, channel_id, username, None, number_of_viewers)
            if points > 0:
                await self.send_chat(channel_id, (
                    f"Thanks for the drop-in!"
                    f" +{points} {POINTS_NAME}"
                ), whisper=username)

    async def send_chat(
        self,
        channel_id: str,
        text: str,
        *,
        mention: str | None = None,
        whisper: str | None = None,
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
        mention: str | None = None,
        whisper: str | None = None,
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
        mention: str | None = None,
        whisper: str | None = None,
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
