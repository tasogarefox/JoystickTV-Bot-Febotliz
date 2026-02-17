from typing import Any
import logging

from app.events import jstv as evjstv

from ..plugin_finder import iter_load_sub_plugins
from .handler import JSTVEventHandler

__all__ = [
    "get",
    "iter_by_type",
    "initialize",
]

HANDLERS: dict[str, type[JSTVEventHandler[Any]]] = {}
HANDLERS_BY_TYPE: dict[type[evjstv.JSTVMessage], list[type[JSTVEventHandler[Any]]]] = {}

logger = logging.getLogger(__package__ or __name__)


# ==============================================================================
# Interface

get = HANDLERS.get

def iter_by_type(msgtype: type[evjstv.JSTVMessage]):
    return iter(HANDLERS_BY_TYPE.get(msgtype, ()))

def initialize() -> None:
    for plugin in iter_load_sub_plugins("events"):
        name = plugin.__name__

        try:
            for handler in plugin.__dict__.values():
                if (
                    handler is JSTVEventHandler or
                    not isinstance(handler, type) or
                    not issubclass(handler, JSTVEventHandler)
                ):
                    continue

                try:
                    register(handler)
                except ValueError as e:
                    logger.exception("Failed to register handler %r: %s", handler.key, e)
                    continue

        except Exception:
            logger.exception("Failed to initialize plugin %r", name)
            continue

        logger.info("Initialized plugin %r", name)

def register(handler: type[JSTVEventHandler[Any]]) -> None:
    if handler.key in HANDLERS:
        raise ValueError(f"Handler already registered: {handler.key}")

    HANDLERS[handler.key] = handler
    HANDLERS_BY_TYPE.setdefault(handler.msgtype, []).append(handler)

    logger.info("Registered handler %r", handler.key)
