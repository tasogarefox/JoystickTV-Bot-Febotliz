from typing import TYPE_CHECKING, Generic, TypeVar, TypeAlias, ClassVar
from dataclasses import dataclass

from app.events import jstv as evjstv
from app.db.enums import CommandAccessLevel
from app.utils import reqcls

from ..base import JSTVHandlerSettings, JSTVHandlerContext, JSTVBaseHandler

if TYPE_CHECKING:
    from app.db.models import Channel, User, Viewer

__all__ = [
    "JSTVCommandSettings",
    "JSTVCommandContext",
    "JSTVCommand",
]

_JSTVMessageBaseType: TypeAlias = evjstv.JSTVNewChatMessage

ContextT = TypeVar("ContextT", bound="JSTVCommandContext", default="JSTVCommandContext")
SettingsT = TypeVar("SettingsT", bound="JSTVCommandSettings", default="JSTVCommandSettings")
MessageT = TypeVar("MessageT", bound=_JSTVMessageBaseType, default=_JSTVMessageBaseType)


# ==============================================================================
# Handler Settings

@dataclass(frozen=True, slots=True)
class JSTVCommandSettings(JSTVHandlerSettings):
    min_access_level: CommandAccessLevel = CommandAccessLevel.viewer

    point_cost: int = 0


# ==============================================================================
# Handler Context

@dataclass(frozen=True, slots=True)
class JSTVCommandContext(
    JSTVHandlerContext[MessageT, SettingsT],
    Generic[MessageT, SettingsT],
):
    alias: str

    channel: "Channel"
    user: "User"
    viewer: "Viewer"


# ==============================================================================
# Handler

class JSTVCommand(
    JSTVBaseHandler[
        MessageT,
        JSTVCommandContext[MessageT, JSTVCommandSettings],
        JSTVCommandSettings,
    ],
    reqcls_check=False,
):
    __slots__ = ()

    msgtypes = (_JSTVMessageBaseType,)

    aliases: ClassVar[tuple[str, ...]] = reqcls.required_field()
