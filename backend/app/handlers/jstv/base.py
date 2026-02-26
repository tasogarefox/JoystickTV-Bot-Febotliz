from typing import TYPE_CHECKING, Generic, TypeVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.events import jstv as evjstv

from ..base import BaseHandlerSettings, BaseHandlerContext, BaseHandler

if TYPE_CHECKING:
    from app.connector import ConnectorManager, BaseConnector
    from app.connectors.joysticktv import JoystickTVConnector
    from app.db.models import Channel, User, Viewer

__all__ = [
    "JSTVHandlerSettings",
    "JSTVHandlerContext",
    "JSTVBaseHandler",
]

MemoryT = TypeVar("MemoryT")
CacheT = TypeVar("CacheT")
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
    BaseHandlerContext[SettingsT, MemoryT, CacheT],
    Generic[MessageT, SettingsT, MemoryT, CacheT],
):
    connector: "BaseConnector"

    message: MessageT | None

    db: AsyncSession
    channel: "Channel"
    user: "User | None"
    viewer: "Viewer | None"

    @property
    def connector_manager(self) -> "ConnectorManager":
        return self.connector.manager

    @property
    def jstv_connector(self) -> "JoystickTVConnector | None":
        from app.connectors.joysticktv import JoystickTVConnector
        return self.connector_manager.get(JoystickTVConnector)

    async def reply(
        self,
        text: str,
        *,
        mention: bool = False,
        whisper: bool = False,
    ) -> bool:
        if self.channel is None or self.user is None:
            return False

        jstv = self.jstv_connector
        if jstv is None:
            return False

        await jstv.send_chat(
            self.channel.channel_id,
            text,
            mention=self.user.username if mention else None,
            whisper=self.user.username if whisper else None,
        )

        return True


# ==============================================================================
# Handler

class JSTVBaseHandler(
    BaseHandler[ContextT, SettingsT],
):
    __slots__ = ()
    __reqcheck__ = False
