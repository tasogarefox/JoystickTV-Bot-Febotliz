from typing import ClassVar, Generator
from dataclasses import dataclass

from app.connector import BaseConnector
from app.events import jstv as evjstv
from app.db.models import Channel, User, Viewer
from app.db.enums import CommandAccessLevel

__all__ = [
    "CommandSettings",
    "CommandContext",
    "Command",
]


# ==============================================================================
# CommandContext

@dataclass(frozen=True, slots=True)
class CommandContext:
    connector: BaseConnector
    evmsg: evjstv.JSTVMessage

    channel: Channel
    user: User
    viewer: Viewer

    settings: "CommandSettings"

    fields: dict


# ==============================================================================
# CommandDefaults

@dataclass(frozen=True, slots=True)
class CommandSettings:
    min_access_level: CommandAccessLevel = CommandAccessLevel.viewer

    point_cost: int = 0

    channel_cooldown: int = 0
    channel_limit: int = 0

    viewer_cooldown: int = 0
    viewer_limit: int = 0


# ==============================================================================
# Command

class Command:
    __slots__ = ()

    __subclasses: ClassVar[dict[str, type["Command"]]] = {}
    __CHECK_ATTRIBUTES: ClassVar[tuple[str, ...]] = (
        "key", "description",
        "name", "aliases",
        "settings",
    )
    __CHECK_METHODS: ClassVar[tuple[str, ...]] = (
        "handle",
    )

    key: ClassVar[str]
    description: ClassVar[str]

    name: ClassVar[str]
    aliases: ClassVar[tuple[str, ...]]

    settings: ClassVar[CommandSettings]

    # prevent instantiation
    def __new__(cls, *args, **kwargs):
        raise TypeError(f"{cls.__name__} cannot be instantiated")

    def __init_subclass__(cls):
        super().__init_subclass__()

        # Required class attributes
        missing = [f for f in Command.__CHECK_ATTRIBUTES if not hasattr(cls, f)]

        # Abstract methods implemented?
        for method in Command.__CHECK_METHODS:
            if method not in cls.__dict__:
                missing.append(method)

        if missing:
            raise TypeError(f"{cls.__name__} missing required items: {', '.join(missing)}")

        if cls.key in cls.__subclasses:
            raise TypeError(f"Duplicate command key: {cls.key}")

        cls.__subclasses[cls.key] = cls

    @classmethod
    def get_command(cls, key: str) -> type["Command"]:
        return cls.__subclasses[key]

    @classmethod
    def iter_commands(cls) -> Generator[tuple[str, type["Command"]], None, None]:
        yield from cls.__subclasses.items()

    @classmethod
    async def handle(cls, ctx: CommandContext) -> bool:
        ...
