from typing import TYPE_CHECKING, Generic, TypeVar, ClassVar, Any
from dataclasses import dataclass, field

from app.events import jstv as evjstv
from app.utils import reqcls

from ..base import BaseHandlerSettings, BaseHandlerContext, BaseHandler

if TYPE_CHECKING:
    from app.connectors.joysticktv import JoystickTVConnector
    from app.db.models import Channel, User, Viewer

__all__ = [
    "JSTVHandlerSettings",
    "JSTVHandlerContext",
    "JSTVBaseHandler",
]

ContextT = TypeVar("ContextT", bound="JSTVHandlerContext")
SettingsT = TypeVar("SettingsT", bound="JSTVHandlerSettings")
MessageT = TypeVar("MessageT", bound=evjstv.JSTVMessage)


# ==============================================================================
# Handler Settings

@dataclass(frozen=True, slots=True)
class JSTVHandlerSettings(BaseHandlerSettings):
    channel_cooldown: int = 0
    channel_limit: int = 0

    viewer_cooldown: int = 0
    viewer_limit: int = 0


# ==============================================================================
# Handler Context

@dataclass(frozen=True, slots=True)
class JSTVHandlerContext(
    BaseHandlerContext[SettingsT],
    Generic[MessageT, SettingsT],
):
    connector: "JoystickTVConnector"

    message: MessageT

    channel: "Channel"
    user: "User | None"
    viewer: "Viewer | None"

    extra: dict[Any, Any] = field(default_factory=dict)


# ==============================================================================
# Handler

class JSTVBaseHandler(
    BaseHandler[ContextT, SettingsT],
    Generic[MessageT, ContextT, SettingsT],
    reqcls_check=False,
):
    __slots__ = ()

    msgtype: ClassVar[type[evjstv.JSTVMessage]] = reqcls.required_field()
