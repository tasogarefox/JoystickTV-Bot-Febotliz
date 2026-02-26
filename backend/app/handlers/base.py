from typing import Generic, TypeVar, ClassVar, Any
from types import MappingProxyType
from dataclasses import dataclass, field
import enum

from app.utils import reqcls

T = TypeVar("T")
MemoryT = TypeVar("MemoryT")
CacheT = TypeVar("CacheT")
SettingsT = TypeVar("SettingsT", bound="BaseHandlerSettings")
ContextT = TypeVar("ContextT", bound="BaseHandlerContext")

MISSING = object()


# ==============================================================================
# Handler Settings

@dataclass(frozen=True, slots=True)
class BaseHandlerSettings:
    pass


# ==============================================================================
# Handler Context

@dataclass(frozen=True, slots=True)
class BaseHandlerContext(
    Generic[SettingsT, MemoryT, CacheT],
):
    settings: SettingsT

    memory: MemoryT | None = field(default=None, init=False)
    cache: CacheT | None = field(default=None, init=False)

    def set_cache(self, value: CacheT | None) -> None:
        """Set cache value, bypassing freeze."""
        object.__setattr__(self, "cache", value)

    def set_memory(self, value: MemoryT | None) -> None:
        """Set memory value, bypassing freeze."""
        object.__setattr__(self, "memory", value)


# ==============================================================================
# Handler

class BaseHandler(
    reqcls.ReqCls,
    Generic[ContextT, SettingsT],
):
    __slots__ = ()
    __reqcheck__ = False

    _subclasses: ClassVar[dict[str, type["BaseHandler[Any, Any]"]]]
    handlers: ClassVar[MappingProxyType[str, type["BaseHandler[Any, Any]"]]]

    key: ClassVar[str] = reqcls.required_field()
    title: ClassVar[str] = reqcls.required_field()
    description: ClassVar[str] = reqcls.required_field()
    disabled: ClassVar[bool] = False
    priority: ClassVar[int] = 100
    tags: ClassVar[frozenset[str]] = frozenset()

    settings: SettingsT = reqcls.required_field()

    # prevent instantiation
    def __new__(cls, *args, **kwargs):
        raise TypeError(f"{cls.__name__} cannot be instantiated")

    def __init_subclass__(cls):
        super().__init_subclass__()

        # Skip if not implemented
        if not reqcls.is_implemented(cls):
            cls._subclasses = {}
            cls.handlers = MappingProxyType(cls._subclasses)
            return

        # Ensure key has been overridden
        key: str | None = cls.__dict__.get("key")

        if not key:
            raise TypeError(f"Missing key override in {cls.__name__}")

        key_fold = key.casefold()
        subclasses = cls._subclasses

        # Ensure key is unique
        other = subclasses.get(key_fold)
        if other is not None:
            raise TypeError(f"Same key in {cls.__name__} and {other.__name__}: {key}")

        subclasses[key_fold] = cls

    @classmethod
    async def prepare(cls, ctx: ContextT) -> bool:
        """
        Prepare to handle an event or message.

        :return: True if the event or message should be handled; False otherwise.
        :rtype: bool
        """
        return True

    @classmethod
    @reqcls.required_method
    async def handle(cls, ctx: ContextT) -> bool:
        """
        Handle an event or message.

        :return: True to stop processing further handlers; False to continue.
        :rtype: bool
        """
        ...
