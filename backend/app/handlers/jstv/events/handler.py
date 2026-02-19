from typing import TYPE_CHECKING, Generic, TypeVar, ClassVar, final
from dataclasses import dataclass
import re

from app.events import jstv as evjstv
from app.utils import reqcls

from ..base import JSTVHandlerSettings, JSTVHandlerContext, JSTVBaseHandler

if TYPE_CHECKING:
    from app.db.models import Channel, User, Viewer

__all__ = [
    "JSTVEventHandlerSettings",
    "JSTVEventHandlerContext",
    "JSTVEventHandler",
    "JSTVChatTriggerHandler",
    "JSTVChatEmoteHandler",
]

ContextT = TypeVar("ContextT", bound="JSTVEventHandlerContext", default="JSTVEventHandlerContext")
SettingsT = TypeVar("SettingsT", bound="JSTVEventHandlerSettings", default="JSTVEventHandlerSettings")
MessageT = TypeVar("MessageT", bound=evjstv.JSTVMessage, default=evjstv.JSTVMessage)


# =============================================================================
# Handler Settings

@dataclass(frozen=True, slots=True)
class JSTVEventHandlerSettings(JSTVHandlerSettings):
    priority: int = 1000


# =============================================================================
# Handler Context

@dataclass(frozen=True, slots=True)
class JSTVEventHandlerContext(
    JSTVHandlerContext[MessageT, SettingsT],
    Generic[MessageT, SettingsT],
):
    channel: "Channel"
    user: "User | None"
    viewer: "Viewer | None"


# =============================================================================
# Handlers

class JSTVEventHandler(
    JSTVBaseHandler[
        MessageT,
        JSTVEventHandlerContext[MessageT, JSTVEventHandlerSettings],
        JSTVEventHandlerSettings,
    ],
    reqcls_check=False,
):
    __slots__ = ()

class JSTVChatTriggerHandler(
    JSTVEventHandler[evjstv.JSTVNewChatMessage],
    reqcls_check=False,
):
    __slots__ = ()

    msgtypes = (evjstv.JSTVNewChatMessage,)

    triggers: ClassVar[tuple[str | re.Pattern, ...]] = reqcls.required_field()

    @classmethod
    @final
    async def handle(cls, ctx) -> bool:
        text = ctx.message.text
        text_casefold = text.casefold()

        for trigger in cls.triggers:
            if isinstance(trigger, re.Pattern):
                match = trigger.match(text)
                if match:
                    return await cls.handle_trigger(ctx, match)

            else:
                if trigger.casefold() in text_casefold:
                    return await cls.handle_trigger(ctx, trigger)

        return False

    @classmethod
    @reqcls.required_method
    async def handle_trigger(
        cls,
        ctx: JSTVEventHandlerContext[evjstv.JSTVNewChatMessage, JSTVEventHandlerSettings],
        trigger: str | re.Match[str],
    ) -> bool:
        ...

class JSTVChatEmoteHandler(
    JSTVEventHandler[evjstv.JSTVNewChatMessage],
    reqcls_check=False,
):
    __slots__ = ()

    msgtypes = (evjstv.JSTVNewChatMessage,)

    emote_codes: ClassVar[frozenset[str]] = reqcls.required_field()

    @classmethod
    @final
    async def handle(cls, ctx) -> bool:
        for emote in ctx.message.emotesUsed:
            if any(emote.code.casefold() == code.casefold() for code in cls.emote_codes):
                return await cls.handle_emote(ctx, emote)

        return False

    @classmethod
    @reqcls.required_method
    async def handle_emote(
        cls,
        ctx: JSTVEventHandlerContext[evjstv.JSTVNewChatMessage, JSTVEventHandlerSettings],
        emote: evjstv.JSTVChatEmote,
    ) -> bool:
        ...
