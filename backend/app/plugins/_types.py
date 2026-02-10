from typing import TypeAlias, NamedTuple
from pathlib import Path, PurePath

__all__ = [
    "PluginSource",
    "AnyPluginSource",
    "PluginPart",
    "PluginParts",
    "PluginPathInfo",
]

PluginSource: TypeAlias = Path
AnyPluginSource: TypeAlias = PluginSource | PurePath | str

PluginPart: TypeAlias = str

PluginPartsTuple: TypeAlias = tuple[PluginPart, ...]


# ==============================================================================
# PluginParts

class PluginParts(PluginPartsTuple):
    """
    Immutable sequence of plugin name parts with helpers for
    safe composition and module-name conversion.
    """

    def __str__(self) -> str:
        return ".".join(self)

    def appended(self, other: PluginPartsTuple | PluginPart) -> "PluginParts":
        """Return a new PluginParts with additional part(s) appended."""
        if isinstance(other, PluginPart):
            other = (other,)
        return PluginParts(self + other)

    @classmethod
    def from_plugin_path(cls, plugin_path: str | None) -> "PluginParts":
        """Create PluginParts from a dotted plugin path string."""
        return cls(plugin_path.split(".")) if plugin_path else cls()

    @staticmethod
    def validate_part(part: PluginPart) -> None:
        """
        Validate a plugin part.
        Raise ValueError if it is invalid.
        """
        if not part:
            raise ValueError(f"empty plugin part")

        for char in [".", "/", "\\"]:
            if char in part:
                raise ValueError(
                    f"invalid character {char!r} in plugin part: {part}"
                )

        if part.startswith("__"):
            raise ValueError(
                f"plugin parts must not start with a double underscore \"__\": {part}"
            )

    def validate(self) -> None:
        """
        Validate the plugin parts.
        Raise ValueError if it is invalid.
        """
        for part in self:
            self.validate_part(part)

    def startswith(self, other: "PluginParts") -> bool:
        """Return True if self starts with other."""
        return self[:len(other)] == other

    def removed_prefix(self, prefix: "PluginParts") -> "PluginParts":
        """
        Return a new PluginParts with the prefix removed.
        Raise ValueError if the prefix does not match.
        """
        if not self.startswith(prefix):
            raise ValueError(f"invalid prefix {prefix} for {self}")
        return PluginParts(self[len(prefix):])


# ==============================================================================
# PluginPathInfo

class PluginPathInfo(NamedTuple):
    """A namedtuple with minimal info about a plugin."""
    parts: PluginParts
    ispkg: bool
    source: PluginSource

    @property
    def plugin_name(self) -> str:
        """Return the final part of the plugin name."""
        return self.parts[-1]

    @property
    def plugin_path(self) -> str:
        """Return the dotted plugin name."""
        return ".".join(self.parts)

    @property
    def plugin_package(self) -> str:
        """Return the dotted plugin package name."""
        return ".".join(self.parts[:-1])

    @property
    def file(self) -> str:
        """Return the source path as string."""
        return str(self.source)
