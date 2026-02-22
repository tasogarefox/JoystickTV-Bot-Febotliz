from typing import ClassVar
from datetime import datetime

from app.utils.pydantic import ParsedJSON

from .shared import JSTVEvent, JSTVLoggedModel, JSTVIdentifier

JSTVEventType = type[JSTVEvent]

__all__ = [
    "JSTVControlEvent",
    "JSTVPingEvent",
    "JSTVWelcomeEvent",
    "JSTVConfirmSubscriptionEvent",
    "JSTVRejectSubscriptionEvent",
]


# ==============================================================================
# Events

class JSTVControlEvent(JSTVEvent, JSTVLoggedModel):
    __subclsmap: ClassVar[dict[str, type["JSTVControlEvent"]]] = {}

    discriminator: ClassVar[str]

    type: str

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
        return str(self.discriminator)

    @classmethod
    def getsubcls(cls, data: dict) -> JSTVEventType | None:
        discriminator = data.get("type")
        if discriminator is None:
            return None
        return cls.__subclsmap.get(discriminator)

class JSTVPingEvent(JSTVControlEvent):
    discriminator = "ping"

    message: int

    @property
    def time(self) -> datetime:
        return datetime.fromtimestamp(self.message)

    def __str__(self) -> str:
        return f"ping at {self.time}"

class JSTVWelcomeEvent(JSTVControlEvent):
    discriminator = "welcome"

class JSTVConfirmSubscriptionEvent(JSTVControlEvent):
    discriminator = "confirm_subscription"

    identifier: ParsedJSON[JSTVIdentifier]

class JSTVRejectSubscriptionEvent(JSTVControlEvent):
    discriminator = "reject_subscription"

    identifier: ParsedJSON[JSTVIdentifier]
