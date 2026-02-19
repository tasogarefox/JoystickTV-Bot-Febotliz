from typing import Any
import logging

from ..plugin_finder import iter_load_sub_plugins
from .handler import JSTVCommand

__all__ = [
    "get",
    "get_by_alias",
    "initialize",
]

HANDLERS: dict[str, type[JSTVCommand[Any]]] = {}
HANDLERS_BY_ALIAS: dict[str, type[JSTVCommand[Any]]] = {}

logger = logging.getLogger(__package__ or __name__)


# ==============================================================================
# Interface

get = HANDLERS.get

def get_by_alias(alias: str) -> type[JSTVCommand[Any]] | None:
    return HANDLERS_BY_ALIAS.get(alias.casefold())

def initialize() -> None:
    for plugin in iter_load_sub_plugins("commands"):
        name = plugin.__name__

        try:
            for handler in plugin.__dict__.values():
                if (
                    not isinstance(handler, type) or
                    not issubclass(handler, JSTVCommand)
                    or not handler.is_implemented()
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

def register(handler: type[JSTVCommand[Any]]) -> None:
    if handler.key in HANDLERS:
        raise ValueError(f"Handler already registered: {handler.key}")

    HANDLERS[handler.key] = handler

    for alias in handler.aliases:
        alias = alias.casefold()
        if alias not in HANDLERS_BY_ALIAS:
            HANDLERS_BY_ALIAS[alias] = handler

    logger.info("Registered handler %r", handler.key)
