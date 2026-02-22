from typing import TypeVar, Annotated, ClassVar
import logging
import json

from pydantic import BaseModel, ConfigDict, BeforeValidator

logger = logging.getLogger(__name__)


# ==============================================================================
# Helpers

def _parse_str_or_dict(v):
    if isinstance(v, str):
        return json.loads(v)
    return v

T = TypeVar("T")
ParsedJSON = Annotated[T, BeforeValidator(_parse_str_or_dict)]


# ==============================================================================
# Models

class FrozenBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True)

class LoggedBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    logger: ClassVar[logging.Logger] = logger

    def model_post_init(self, __context):
        if self.model_extra:
            self.logger.warning(
                "%s received unexpected fields: %s",
                self.__class__.__name__,
                list(self.model_extra.items())
            )
