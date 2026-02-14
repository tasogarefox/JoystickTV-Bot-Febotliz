from typing import TypeVar, Annotated, ClassVar
import logging
import json

from pydantic import BaseModel, ConfigDict, BeforeValidator, ValidationError

from ..events import Event

from .errors import JSTVParseError, JSTVValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "JSTVEvent",
    "JSTVIdentifier",
]


# ==============================================================================
# Helpers

def _parse_str_or_dict(v):
    if isinstance(v, str):
        return json.loads(v)
    return v

T = TypeVar("T")
ParsedJSON = Annotated[T, BeforeValidator(_parse_str_or_dict)]


# ==============================================================================
# Data

class JSTVBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        frozen=True,
    )

class LoggedModel(JSTVBaseModel):
    def model_post_init(self, __context):
        if self.model_extra:
            logger.warning(
                "%s received unexpected fields: %s",
                self.__class__.__name__,
                list(self.model_extra.keys())
            )

class JSTVIdentifier(LoggedModel):
    channel: str


# ==============================================================================
# Events

class JSTVEvent(Event, BaseModel):
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
