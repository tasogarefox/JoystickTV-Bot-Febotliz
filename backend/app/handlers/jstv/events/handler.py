from typing import Generic, TypeVar
from dataclasses import dataclass

from app.events import jstv as evjstv

from ..base import JSTVHandlerSettings, JSTVHandlerContext, JSTVBaseHandler

__all__ = [
    "JSTVEventHandlerSettings",
    "JSTVEventHandlerContext",
    "JSTVEventHandler",
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
    pass


# =============================================================================
# Handler

class JSTVEventHandler(
    JSTVBaseHandler[
        MessageT,
        JSTVEventHandlerContext[MessageT, JSTVEventHandlerSettings],
        JSTVEventHandlerSettings,
    ],
    reqcls_check=False,
):
    __slots__ = ()
