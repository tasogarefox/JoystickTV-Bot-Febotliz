from typing import TypeGuard, Generic, TypeVar, ClassVar, Literal
from datetime import datetime

from pydantic import Field, AliasChoices, field_validator

from app.utils.pydantic import ParsedJSON

from .shared import JSTVEvent, JSTVLoggedModel, JSTVIdentifier
from .errors import JSTVValidationError

JSTVMessageT = TypeVar(
    "JSTVMessageT",
    bound="JSTVMessage",
    default="JSTVMessage",
    covariant=True,
)

__all__ = [
    "evmsgisinstance",

    "JSTVMessageEvent",

    "JSTVMessage",
    # "JSTVBaseMessageWithId",
    # "JSTVBaseMessageWithMessageId",
    "JSTVBaseUser",
    "JSTVAuthor",
    "JSTVStreamer",
    "JSTVBaseStreamLivespan",
    "JSTVSteamStarted",
    "JSTVStreamEnded",
    "JSTVStreamEnding",
    "JSTVStreamResuming",
    "JSTVFollowed",
    "JSTVFollowerCountUpdated",
    "JSTVSubscribed",
    "JSTVSubscriberCountUpdated",
    "JSTVTipped",
    "JSTVBaseTipMenuItemLockStateChanged",
    "JSTVTipMenuItemLocked",
    "JSTVTipMenuItemUnlocked",
    "JSTVTipGoalIncreased",
    "JSTVTipGoalUpdated",
    "JSTVMilestoneCompleted",
    "JSTVTipGoalMet",
    "JSTVStreamDropin",
    "JSTVStreamDroppedIn",
    "JSTVSettingsUpdated",
    "JSTVBaseDeviceConnection",
    "JSTVDeviceConnected",
    "JSTVDeviceDisconnected",
    "JSTVBaseUserPresence",
    "JSTVUserEnteredStream",
    "JSTVUserLeftStream",
    "JSTVChatEmote",
    "JSTVBaseChatMessage",
    "JSTVNewChatMessage",
]


# ==============================================================================
# Helpers

def evmsgisinstance(
    event: JSTVEvent, cls: type[JSTVMessageT]
) -> TypeGuard["JSTVMessageEvent[JSTVMessageT]"]:
    """
    Type guard for `JSTVMessageEvent`.

    Returns True if `event` is a `JSTVMessageEvent` and `event.message` is an instance of `cls`.
    Enables type narrowing for both the event and its message.
    """
    return isinstance(event, JSTVMessageEvent) and isinstance(event.message, cls)


# ==============================================================================
# Events

class JSTVMessageEvent(JSTVEvent, JSTVLoggedModel, Generic[JSTVMessageT]):
    identifier: ParsedJSON[JSTVIdentifier]
    message: JSTVMessageT

    @classmethod
    def getsubcls(cls, data: dict) -> type[JSTVEvent] | None:
        if "message" not in data:
            return None
        return cls

    @field_validator("message", mode="before")
    @classmethod
    def parse_message(cls, v):
        if isinstance(v, dict):
            return JSTVMessage.parse(v)
        return v

    def __str__(self) -> str:
        return f"message: {self.message}"

    @property
    def actor(self) -> str | None:
        """
        Username of the primary user associated with this event, if any.

        Convenience proxy to `self.message.actor`.
        """
        return self.message.actorname

# ==============================================================================
# Data Models

class JSTVMessage(JSTVLoggedModel):
    __subclsmap: ClassVar[dict[str, type["JSTVMessage"]]] = {}

    discriminator: ClassVar[str]

    event: str
    type: str

    text: str
    channelId: str
    createdAt: datetime

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        discriminator: str | None = cls.__dict__.get("discriminator")
        if discriminator is None:
            return

        if discriminator in cls.__subclsmap:
            raise TypeError(
                f"Same discriminator in {cls.__name__}"
                f" and {cls.__subclsmap[discriminator].__name__}"
                f": {discriminator}"
            )

        cls.__subclsmap[discriminator] = cls

    def __str__(self) -> str:
        return (
            f"{self.discriminator}"
            f" @{self.shortChannelId}"
            f" {self.shortText!r}"
        )

    @classmethod
    def parse(cls, data: dict) -> "JSTVMessage":
        discriminator_parts = []
        for key in ["event", "type"]:
            value = data.get(key)
            if value is None:
                raise JSTVValidationError(f"Missing field: {key}")
            discriminator_parts.append(value)

        discriminator = ":".join(discriminator_parts)
        subcls = cls.__subclsmap.get(discriminator)
        if subcls is None:
            raise JSTVValidationError(f"Unknown message type: {discriminator}")

        return subcls(**data)

    @property
    def shortChannelId(self) -> str:
        return self.channelId[:7]

    @property
    def shortText(self) -> str:
        return self.getShortText()

    def getShortText(self, maxlen: int = 40) -> str:
        text = self.text
        if len(text) > maxlen:
            text = text[:maxlen-3] + "..."
        return text

    @property
    def actorname(self) -> str | None:
        """
        Username of the primary user associated with this message, if any.

        Subclasses should override this property when applicable.
        """
        return None

class JSTVBaseMessageWithId(JSTVMessage):
    id: str

class JSTVBaseMessageWithMessageId(JSTVBaseMessageWithId):
    id: str = Field(validation_alias=AliasChoices("id", "messageId"))

    @property
    def messageId(self) -> str:
        return self.id

class JSTVBaseUser(JSTVLoggedModel):
    slug: str
    username: str
    usernameColor: str | None = None
    signedPhotoUrl: str | None = None
    signedPhotoThumbUrl: str | None = None

class JSTVAuthor(JSTVBaseUser):
    nickname: str | None
    displayNameWithFlair: str
    isStreamer: bool
    isModerator: bool
    isSubscriber: bool
    isVerified: bool
    isContentCreator: bool

class JSTVStreamer(JSTVBaseUser):
    pass

class JSTVBaseStreamLivespan(JSTVBaseMessageWithId):
    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.who

    class Metadata(JSTVLoggedModel):
        who: str

class JSTVSteamStarted(JSTVBaseStreamLivespan):
    discriminator = "StreamEvent:Started"

class JSTVStreamEnded(JSTVBaseStreamLivespan):
    discriminator = "StreamEvent:Ended"

class JSTVStreamEnding(JSTVBaseStreamLivespan):
    discriminator = "StreamEvent:StreamEnding"

class JSTVStreamResuming(JSTVBaseStreamLivespan):
    discriminator = "StreamEvent:StreamResuming"

class JSTVFollowed(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:Followed"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.who

    class Metadata(JSTVLoggedModel):
        who: str
        what: Literal["followed"]

class JSTVFollowerCountUpdated(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:FollowerCountUpdated"

    metadata: ParsedJSON["Metadata"]

    class Metadata(JSTVLoggedModel):
        number_of_followers: int

class JSTVSubscribed(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:Subscribed"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.who

    class Metadata(JSTVLoggedModel):
        who: str
        what: Literal["subscribed"]
        how_much: int

class JSTVSubscriberCountUpdated(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:SubscriberCountUpdated"

    metadata: ParsedJSON["Metadata"]

    class Metadata(JSTVLoggedModel):
        number_of_subscribers: int

class JSTVTipped(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:Tipped"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.who

    class Metadata(JSTVLoggedModel):
        who: str
        what: Literal["Tipped"]
        how_much: int
        tip_menu_item: str | None

class JSTVBaseTipMenuItemLockStateChanged(JSTVBaseMessageWithId):
    metadata: ParsedJSON["Metadata"]

    class Metadata(JSTVLoggedModel):
        title: str
        amount: int

class JSTVTipMenuItemLocked(JSTVBaseTipMenuItemLockStateChanged):
    discriminator = "StreamEvent:TipMenuItemLocked"

class JSTVTipMenuItemUnlocked(JSTVBaseTipMenuItemLockStateChanged):
    discriminator = "StreamEvent:TipMenuItemUnlocked"

class JSTVTipGoalIncreased(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:TipGoalIncreased"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.by_user

    class Metadata(JSTVLoggedModel):
        by_user: str
        what: Literal["TipGoalIncreased"]
        amount: int
        current: int
        previous: int

class JSTVTipGoalUpdated(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:TipGoalUpdated"

    metadata: ParsedJSON["Metadata"]

    class Metadata(JSTVLoggedModel):
        title: str
        amount: int

class JSTVMilestoneCompleted(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:MilestoneCompleted"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.who

    class Metadata(JSTVLoggedModel):
        who: str
        what: Literal["MilestoneCompleted"]
        title: str
        amount: int

class JSTVTipGoalMet(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:TipGoalMet"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.who

    class Metadata(JSTVLoggedModel):
        who: str
        what: Literal["TipGoalMet"]
        title: str
        amount: int

class JSTVStreamDropin(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:DropinStream"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.origin

    class Metadata(JSTVLoggedModel):
        origin: str
        destination: str
        destination_username: str
        number_of_viewers: int

class JSTVStreamDroppedIn(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:StreamDroppedIn"

    metadata: ParsedJSON["Metadata"]

    @property
    def actorname(self) -> str:
        return self.metadata.who

    class Metadata(JSTVLoggedModel):
        who: str
        what: Literal["dropped in"]
        number_of_viewers: int

class JSTVSettingsUpdated(JSTVBaseMessageWithId):
    discriminator = "StreamEvent:SettingsUpdated"

    metadata: ParsedJSON["Metadata"]

    class Metadata(JSTVLoggedModel):
        pass

class JSTVBaseDeviceConnection(JSTVBaseMessageWithId):
    metadata: ParsedJSON["Metadata"]

    class Metadata(JSTVLoggedModel):
        pass

class JSTVDeviceConnected(JSTVBaseDeviceConnection):
    discriminator = "StreamEvent:DeviceConnected"

class JSTVDeviceDisconnected(JSTVBaseDeviceConnection):
    discriminator = "StreamEvent:DeviceDisconnected"

class JSTVBaseUserPresence(JSTVBaseMessageWithId):
    @property
    def actorname(self) -> str:
        return self.username

    @property
    def username(self) -> str:
        return self.text

class JSTVUserEnteredStream(JSTVBaseUserPresence):
    discriminator = "UserPresence:enter_stream"

class JSTVUserLeftStream(JSTVBaseUserPresence):
    discriminator = "UserPresence:leave_stream"

class JSTVChatEmote(JSTVLoggedModel):
    code: str
    signedUrl: str
    signedThumbnailUrl: str

class JSTVBaseChatMessage(JSTVBaseMessageWithMessageId):
    visibility: str
    botCommand: str | None = None
    botCommandArg: str | None = None
    emotesUsed: tuple[JSTVChatEmote, ...]
    author: JSTVAuthor
    streamer: JSTVStreamer
    mention: bool
    mentionedUsername: str | None = None
    highlight: bool

    def __str__(self) -> str:
        return (
            f"{self.discriminator}"
            f" @{self.shortChannelId}"
            f" {self.author.username}: {self.shortText}"
        )

    @property
    def actorname(self) -> str:
        return self.author.username

    @property
    def sameAuthorAsStreamer(self) -> bool:
        """Whether the author is the same as the streamer."""
        return self.author.slug == self.streamer.slug

    def splitBotCommandArg(self) -> list[str]:
        if self.botCommandArg is None:
            return []
        return self.botCommandArg.split()

class JSTVNewChatMessage(JSTVBaseChatMessage):
    discriminator = "ChatMessage:new_message"
