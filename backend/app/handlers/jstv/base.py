from typing import TYPE_CHECKING, Generic, TypeVar, ClassVar
from dataclasses import dataclass

from app.events import jstv as evjstv
from app.utils import reqcls

from ..base import BaseHandlerSettings, BaseHandlerContext, BaseHandler

if TYPE_CHECKING:
    from app.connector import ConnectorManager
    from app.connectors.joysticktv import JoystickTVConnector

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

    @property
    def connector_manager(self) -> "ConnectorManager":
        return self.connector.manager


# ==============================================================================
# Handler

class JSTVBaseHandler(
    BaseHandler[ContextT, SettingsT],
    Generic[MessageT, ContextT, SettingsT],
    reqcls_check=False,
):
    __slots__ = ()

    msgtypes: ClassVar[tuple[type[evjstv.JSTVMessage], ...]] = reqcls.required_field()
