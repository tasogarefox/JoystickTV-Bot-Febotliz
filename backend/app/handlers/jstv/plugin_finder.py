from typing import Generator, Callable
from types import ModuleType
import logging

from app import paths
from app.plugins import PluginFinder

__all__ = [
    "plugin_finder",
    "install",
    "iter_load_sub_plugins",
]

PLUGIN_NAME = "jstv"
PLUGIN_DIRS = (
    paths.BACKEND_DIR / "plugins" / PLUGIN_NAME,
)

logger = logging.getLogger(__package__ or __name__)

plugin_finder = PluginFinder(PLUGIN_NAME, PLUGIN_DIRS)


# ==============================================================================
# Interface

install = plugin_finder.install

def default_plugin_filter(fullname: str, ispkg: bool) -> bool:
    return not fullname.rpartition(".")[2].startswith("_")

def iter_load_sub_plugins(
    plugin_package: str,
    filter: Callable[[str, bool], bool] = default_plugin_filter,
) -> Generator[ModuleType, None, None]:
    for fullname, ispkg in plugin_finder.iter_plugins(plugin_package):
        if filter is not None and not filter(fullname, ispkg):
            continue

        try:
            plugin = plugin_finder.import_plugin(fullname)
        except ImportError:
            logger.exception("Failed to import plugin %r", fullname)
            continue

        # logger.info("Loaded plugin %r", fullname)
        yield plugin
