from typing import TypeVar, ClassVar, Any, Iterator, final
from dataclasses import dataclass
import logging
import re
import bisect

from app.events import jstv as evjstv
from app.utils import reqcls

from ..base import JSTVHandlerSettings, JSTVHandlerContext, JSTVBaseHandler

__all__ = [
    "JSTVEventHandlerSettings",
    "JSTVEventHandlerContext",
    "JSTVEventHandler",
    "JSTVChatTriggerHandler",
    "JSTVChatEmoteHandler",
]

T = TypeVar("T")
MemoryT = TypeVar("MemoryT", default=None)
CacheT = TypeVar("CacheT", default=None)
ContextT = TypeVar("ContextT", bound="JSTVEventHandlerContext[Any, Any, Any]", default="JSTVEventHandlerContext[Any, Any, Any]")
SettingsT = TypeVar("SettingsT", bound="JSTVEventHandlerSettings", default="JSTVEventHandlerSettings")
MessageT = TypeVar("MessageT", bound=evjstv.JSTVMessage, default=evjstv.JSTVMessage)

MISSING = object()

logger = logging.getLogger(__name__)


# =============================================================================
# Handler Settings

@dataclass(frozen=True, slots=True)
class JSTVEventHandlerSettings(JSTVHandlerSettings):
    pass


# =============================================================================
# Handler Context

@dataclass(frozen=True, slots=True)
class JSTVEventHandlerContext(
    JSTVHandlerContext[MessageT, JSTVEventHandlerSettings, MemoryT, CacheT],
):
    message: MessageT


# =============================================================================
# Handlers

class JSTVEventHandler(
    JSTVBaseHandler[
        JSTVEventHandlerContext[MessageT, MemoryT, CacheT],
        JSTVEventHandlerSettings,
    ],
):
    __slots__ = ()
    __reqcheck__ = False

    _subclasses_by_type: ClassVar[dict[type[evjstv.JSTVMessage], list[type["JSTVEventHandler[Any, Any, Any]"]]]] = {}

    msgtypes: ClassVar[tuple[type[evjstv.JSTVMessage], ...]] = reqcls.required_field()

    def __init_subclass__(cls):
        super().__init_subclass__()

        # Skip if not implemented
        if not reqcls.is_implemented(cls):
            return

        subclasses = cls._subclasses_by_type

        for msgtype in cls.msgtypes:
            bisect.insort_right(
                subclasses.setdefault(msgtype, []),
                cls,
                key=lambda h: -h.priority
            )

        # if cls.msgtypes:
        #     logger.info(
        #         "Registered event handler %s for events: %s",
        #         cls.key,
        #         ', '.join(sorted(x.discriminator for x in cls.msgtypes)),
        #     )

    @classmethod
    def iter_handlers_by_type(cls, msgtype: type[evjstv.JSTVMessage]) -> Iterator[type["JSTVEventHandler[Any, Any, Any]"]]:
        return iter(cls._subclasses_by_type.get(msgtype, ()))

class JSTVChatTriggerHandler(
    JSTVEventHandler[evjstv.JSTVNewChatMessage, MemoryT, CacheT],
):
    __slots__ = ()
    __reqcheck__ = False

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
        ctx: JSTVEventHandlerContext[evjstv.JSTVNewChatMessage, MemoryT, CacheT],
        trigger: str | re.Match[str],
    ) -> bool:
        ...

class JSTVChatEmoteHandler(
    JSTVEventHandler[evjstv.JSTVNewChatMessage, MemoryT, CacheT],
):
    __slots__ = ()
    __reqcheck__ = False

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
        ctx: JSTVEventHandlerContext[evjstv.JSTVNewChatMessage, MemoryT, CacheT],
        emote: evjstv.JSTVChatEmote,
    ) -> bool:
        ...
