from typing import Generic, TypeVar, ClassVar, Any, Generator, overload
from dataclasses import dataclass

from app.utils import reqcls

T = TypeVar("T")

SettingsT = TypeVar("SettingsT", bound="BaseHandlerSettings")
ContextT = TypeVar("ContextT", bound="BaseHandlerContext")


# ==============================================================================
# Constants

MISSING = object()


# ==============================================================================
# Handler Settings

@dataclass(frozen=True, slots=True)
class BaseHandlerSettings:
    pass


# ==============================================================================
# Handler Context

@dataclass(frozen=True, slots=True)
class BaseHandlerContext(Generic[SettingsT]):
    settings: SettingsT


# ==============================================================================
# Handler

class BaseHandler(
    reqcls.ReqCls,
    Generic[ContextT, SettingsT],
    reqcls_check=False,
):
    __slots__ = ()

    _subclasses: ClassVar[dict[str, type["BaseHandler[Any, Any]"]]] = reqcls.required_field()

    key: ClassVar[str] = reqcls.required_field()
    title: ClassVar[str] = reqcls.required_field()
    description: ClassVar[str] = reqcls.required_field()

    settings: SettingsT = reqcls.required_field()

    # prevent instantiation
    def __new__(cls, *args, **kwargs):
        raise TypeError(f"{cls.__name__} cannot be instantiated")

    def __init_subclass__(cls):
        super().__init_subclass__()

        if not reqcls.is_implemented(cls):
            cls._subclasses = {}
            return

        key: str | None = cls.__dict__.get("key")
        if key is None:
            return

        subclasses = cls._subclasses

        if key in subclasses:
            raise TypeError(f"Same key in {cls.__name__} and {subclasses[key].__name__}: {key}")

        subclasses[key] = cls

    @classmethod
    def is_implemented(cls) -> bool:
        return reqcls.is_implemented(cls)

    @overload
    @classmethod
    def get_handler(cls, key: str) -> type["BaseHandler[ContextT, SettingsT]"]: ...

    @overload
    @classmethod
    def get_handler(cls, key: str, default: T) -> type["BaseHandler[ContextT, SettingsT]"] | T: ...

    @classmethod
    def get_handler(cls, key: str, default: T = MISSING) -> type["BaseHandler[ContextT, SettingsT]"] | T:
        try:
            return cls._subclasses[key]
        except KeyError as e:
            if default is MISSING:
                raise e
            return default

    @classmethod
    def iter_handlers(cls) -> Generator[tuple[str, type["BaseHandler"]], None, None]:
        yield from cls._subclasses.items()

    @classmethod
    @reqcls.required_method
    async def handle(cls, ctx: ContextT) -> bool:
        """
        Handle an event or message.

        :return: True to stop processing further handlers; False to continue.
        :rtype: bool
        """
        ...
