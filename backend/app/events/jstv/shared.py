from typing import ClassVar
import logging

from pydantic import ValidationError

from app.utils.pydantic import FrozenBaseModel, LoggedBaseModel

from ..events import Event

from .errors import JSTVParseError, JSTVValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "JSTVEvent",
    "JSTVIdentifier",
]


# ==============================================================================
# Models

class JSTVLoggedModel(FrozenBaseModel, LoggedBaseModel):
    logger = logger

class JSTVIdentifier(JSTVLoggedModel):
    channel: str


# ==============================================================================
# Events

class JSTVEvent(Event, FrozenBaseModel):
    __subclslist: ClassVar[list[type["JSTVEvent"]]] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__subclslist.append(cls)

    @classmethod
    def parse(cls, data: dict) -> "JSTVEvent":
        subcls: type["JSTVEvent"] | None = None
        for isubcls in cls.__subclslist:
            subcls = isubcls.getsubcls(data)
            if subcls is not None:
                break
        else:
            logging.error((
                "Unknown JSTV payload shape:"
                "\nInput: %s"
            ), data)
            raise JSTVParseError("Unknown JSTV payload shape")

        try:
            return subcls(**data)
        except ValidationError as e:
            logger.error((
                "Failed to parse JSTV event:"
                "\n%s"
                "\nInput: %s"
            ), e, data)
            raise JSTVValidationError(e) from e

    @classmethod
    def getsubcls(cls, data: dict) -> type["JSTVEvent"] | None:
        return None
