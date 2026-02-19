from importlib.abc import SourceLoader

from ._types import PluginSource
from .exceptions import PluginImportError

__all__ = [
    "PluginLoader",
]


# ==============================================================================
# PluginLoader

class PluginLoader(SourceLoader):
    """
    Loader for plugins.
    """
    fullname: str
    source: PluginSource

    def __init__(self, fullname: str, source: PluginSource) -> None:
        self.fullname = fullname
        self.source = source

    def get_filename(self, fullname: str) -> str:
        if fullname != self.fullname:
            raise PluginImportError()
        return str(self.source)

    def get_data(self, path: str) -> bytes:
        try:
            if not self.source.samefile(path):
                raise OSError(f"File not found: {path}")

            with self.source.open("rb") as fh:
                data = fh.read()
                assert isinstance(data, bytes)
                return data

        except FileNotFoundError as e:
            raise OSError(f"File not found: {path}") from e
