from importlib.abc import SourceLoader

from .exceptions import PluginImportError

__all__ = [
    "PluginLoader",
]


# ==============================================================================
# PluginLoader

class PluginLoader(SourceLoader):
    """
    Loader for plugin files.
    """
    fullname: str
    file: str

    def __init__(self, fullname: str, file: str) -> None:
        self.fullname = fullname
        self.file = file

    def get_filename(self, fullname: str) -> str:
        if fullname != self.fullname:
            raise PluginImportError()
        return self.file

    def get_data(self, path: str) -> bytes:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
                assert isinstance(data, bytes)
                return data
        except FileNotFoundError as e:
            raise OSError(f"File not found: {path}") from e
