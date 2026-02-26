from typing import TYPE_CHECKING, TypeVar, ClassVar, Any, overload
from dataclasses import dataclass
import logging
import bisect

from app.events import jstv as evjstv
from app.db.enums import AccessLevel
from app.utils import reqcls

from ..base import JSTVHandlerSettings, JSTVHandlerContext, JSTVBaseHandler

if TYPE_CHECKING:
    from app.db.models import (
        Channel, User, Viewer,
        ChannelCommandCooldown, ViewerCommandCooldown,
    )

__all__ = [
    "JSTVCommandSettings",
    "JSTVCommandContext",
    "JSTVCommand",
]

T = TypeVar("T")
MemoryT = TypeVar("MemoryT", default=None)
CacheT = TypeVar("CacheT", default=None)

MISSING = object()

logger = logging.getLogger(__name__)


# ==============================================================================
# Handler Settings

@dataclass(frozen=True, slots=True)
class JSTVCommandSettings(JSTVHandlerSettings):
    aliases: tuple[str, ...] = ()

    min_access_level: AccessLevel = AccessLevel.viewer

    base_cost: int = 0


# ==============================================================================
# Handler Context

@dataclass(frozen=True, slots=True)
class JSTVCommandContext(
    JSTVHandlerContext[evjstv.JSTVMessage, JSTVCommandSettings, MemoryT, CacheT],
):
    alias: str
    argument: str

    channel: "Channel"
    user: "User"
    viewer: "Viewer"

    channel_cooldown: "ChannelCommandCooldown"
    viewer_cooldown: "ViewerCommandCooldown"

    @property
    def channel_id(self) -> str:
        return self.channel.channel_id

    @property
    def actorname(self) -> str:
        return self.user.username


# ==============================================================================
# Handler

class JSTVCommand(
    JSTVBaseHandler[JSTVCommandContext[MemoryT, CacheT], JSTVCommandSettings],
):
    __slots__ = ()
    __reqcheck__ = False

    _subclasses_by_alias: ClassVar[dict[str, list[type["JSTVCommand[Any, Any]"]]]] = {}

    def __init_subclass__(cls):
        super().__init_subclass__()

        # Skip if not implemented
        if not reqcls.is_implemented(cls):
            return

        subclasses = cls._subclasses_by_alias

        # effective_aliases = set()
        for alias in cls.settings.aliases:
            alias = alias.casefold()
            lst = subclasses.setdefault(alias, [])

            # if not lst:
            #     effective_aliases.add(alias)

            bisect.insort_right(
                lst,
                cls,
                key=lambda h: -h.priority
            )

        # if effective_aliases:
        #     logger.info(
        #         "Registered command %s with aliases: %s",
        #         cls.key,
        #         ', '.join(sorted(effective_aliases)),
        #     )

    @overload
    @classmethod
    def get_handler_by_alias(cls, key: str) -> type["JSTVCommand"]: ...

    @overload
    @classmethod
    def get_handler_by_alias(cls, key: str, default: T) -> type["JSTVCommand"] | T: ...

    @classmethod
    def get_handler_by_alias(cls, key: str, default: T = MISSING) -> type["JSTVCommand"] | T:
        key = key.casefold()
        try:
            return cls._subclasses_by_alias[key][0]
        except (KeyError, IndexError) as e:
            if default is MISSING:
                raise e
            return default

    @classmethod
    async def reply_usage(cls, ctx: JSTVCommandContext[MemoryT, CacheT]) -> None:
        await ctx.reply(cls.usage(ctx.alias), mention=True)

    @classmethod
    def usage(cls, alias: str) -> str:
        return cls.description

    @classmethod
    async def variable_costs(cls, ctx: JSTVCommandContext[MemoryT, CacheT]) -> dict[str, float]:
        """
        Return a mapping of variable cost components.
        Values must be >= 0.
        Must be pure and have no side effects.
        """
        return {}
